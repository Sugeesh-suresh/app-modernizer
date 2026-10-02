"""
Model traffic: what each request costs, keeping it small, and keeping the
per-minute rate under the quota — so 429s are avoided rather than retried.

One ADK plugin (`LlmTrafficPlugin`, registered on every runner) does three
things around every model call:

1. Masking old tool output (before the call). An agent resends its whole
   conversation on every call: every file it read, every build log. Ported
   from Gemini CLI's ToolOutputMaskingService (packages/core/src/context/
   toolOutputMaskingService.ts): the latest turn and the newest
   CONTEXT_PROTECT_TOKENS of tool output stay verbatim; once more than
   CONTEXT_MIN_PRUNABLE_TOKENS of older output has accumulated, those outputs
   are replaced by a short pointer. Nothing is lost: the files are on the
   local disk, so the agent re-reads one if it needs it again. Skill loads are
   never masked (they are instructions, not data). Only the request is
   changed — the session's own history is untouched.
2. Pacing (before the call). A sliding 60-second window per model of input
   tokens and requests. When sending would exceed LLM_MAX_TPM / LLM_MAX_RPM
   (or the model's LLM_LIMITS entry), the call waits for the window to free
   up instead of being rejected with 429. Estimates (chars / 4) are
   calibrated per model from the real token counts Gemini returns.
3. Telemetry (after the call). One log line per call: model, agent, input and
   output tokens, tokens masked, seconds waited, and the model's last-60s
   totals — so a run shows how close it gets to the quota.
"""
import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from typing import Callable, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from .. import config

log = logging.getLogger("modernizer.llm")

#: Tool outputs that are instructions, not data — never masked.
EXEMPT_TOOLS = frozenset({"load_skill", "load_skill_resource", "list_skills", "search_skills",
                          "signal_build_success"})
MASK_TAG = "[output masked to save tokens]"
_WINDOW = 60.0


# ---------------------------------------------------------------------------
# Size estimates
# ---------------------------------------------------------------------------

def _part_chars(part: types.Part) -> int:
    n = len(part.text or "")
    if part.function_call:
        n += len(part.function_call.name or "") + len(json.dumps(part.function_call.args or {}, default=str))
    if part.function_response:
        n += len(json.dumps(part.function_response.response or {}, default=str))
    return n


def request_chars(llm_request: LlmRequest) -> int:
    n = sum(_part_chars(p) for c in llm_request.contents or [] for p in (c.parts or []))
    si = llm_request.config.system_instruction if llm_request.config else None
    if si is not None:
        n += len(si) if isinstance(si, str) else sum(_part_chars(p) for p in (getattr(si, "parts", None) or []))
    return n


def estimate_tokens(chars: int) -> int:
    return max(1, chars // 4)


# ---------------------------------------------------------------------------
# 1. Masking
# ---------------------------------------------------------------------------

def _describe_call(name: str, args: dict) -> str:
    shown = ", ".join(f"{k}={v!r}" for k, v in list((args or {}).items())[:3] if k != "content")
    return f"{name}({shown})"


def mask_old_tool_output(contents: list[types.Content], protect_tokens: int,
                         min_prunable_tokens: int) -> tuple[list[types.Content], int, int]:
    """(new contents, outputs masked, estimated tokens saved). The latest turn
    and the newest `protect_tokens` of tool output are kept; older outputs are
    masked only once they add up to `min_prunable_tokens`. New Content objects
    are built for changed turns, so the caller's history is never mutated."""
    if protect_tokens <= 0 or len(contents) < 2:
        return contents, 0, 0
    calls: dict[str, tuple[str, dict]] = {}
    for c in contents:
        for p in c.parts or []:
            if p.function_call and p.function_call.id:
                calls[p.function_call.id] = (p.function_call.name, dict(p.function_call.args or {}))

    seen_tokens = 0
    candidates: list[tuple[int, int, int]] = []   # (content index, part index, tokens)
    for ci in range(len(contents) - 2, -1, -1):   # the latest turn is always kept
        parts = contents[ci].parts or []
        for pi in range(len(parts) - 1, -1, -1):
            fr = parts[pi].function_response
            if not fr or fr.name in EXEMPT_TOOLS:
                continue
            text = json.dumps(fr.response or {}, default=str)
            if MASK_TAG in text:
                continue
            tokens = estimate_tokens(len(text))
            seen_tokens += tokens
            if seen_tokens > protect_tokens:
                candidates.append((ci, pi, tokens))
    prunable = sum(t for _, _, t in candidates)
    if prunable < min_prunable_tokens:
        return contents, 0, 0

    out = list(contents)
    by_content: dict[int, set[int]] = defaultdict(set)
    for ci, pi, _ in candidates:
        by_content[ci].add(pi)
    for ci, part_indexes in by_content.items():
        old = out[ci]
        new_parts = []
        for pi, part in enumerate(old.parts or []):
            if pi not in part_indexes:
                new_parts.append(part)
                continue
            fr = part.function_response
            name, args = calls.get(fr.id or "", (fr.name, {}))
            size = len(json.dumps(fr.response or {}, default=str))
            again = ("The file is on disk — read it again if you need it (it may have changed if you edited it)."
                     if name in ("read_file", "list_files", "search_files")
                     else "Call the tool again with the same arguments if you need this output.")
            marker = f"{MASK_TAG} {size:,} chars of {_describe_call(name, args)} output. {again}"
            new_parts.append(types.Part(function_response=types.FunctionResponse(
                id=fr.id, name=fr.name, response={"result": marker})))
        out[ci] = types.Content(role=old.role, parts=new_parts)
    return out, len(candidates), prunable


# ---------------------------------------------------------------------------
# 2. Pacing
# ---------------------------------------------------------------------------

def parse_limits(spec: str) -> dict[str, tuple[int, int]]:
    """"gemini-2.5-pro=tpm:400000,rpm:50;gemini-2.5-flash=tpm:1500000" -> {model: (tpm, rpm)}."""
    out: dict[str, tuple[int, int]] = {}
    for chunk in (spec or "").split(";"):
        if "=" not in chunk:
            continue
        model, _, rest = chunk.partition("=")
        vals = dict(kv.split(":", 1) for kv in rest.split(",") if ":" in kv)
        try:
            out[model.strip()] = (int(vals.get("tpm", 0)), int(vals.get("rpm", 0)))
        except ValueError:
            continue
    return out


class Pacer:
    """Sliding 60-second windows of input tokens and requests, per model."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, sleep=asyncio.sleep):
        self._clock, self._sleep = clock, sleep
        self._tokens: dict[str, deque] = defaultdict(deque)     # (time, [tokens])
        self._requests: dict[str, deque] = defaultdict(deque)   # time
        self._locks: dict[str, asyncio.Lock] = {}
        self._ratio: dict[str, float] = {}                      # actual / estimated tokens

    def limits(self, model: str) -> tuple[int, int]:
        return parse_limits(config.LLM_LIMITS).get(model, (config.LLM_MAX_TPM, config.LLM_MAX_RPM))

    def calibrated(self, model: str, estimate: int) -> int:
        return int(round(estimate * self._ratio.get(model, 1.0)))

    def _expire(self, model: str, now: float) -> None:
        for q, key in ((self._tokens[model], lambda e: e[0]), (self._requests[model], lambda e: e)):
            while q and now - key(q[0]) >= _WINDOW:
                q.popleft()

    def usage(self, model: str) -> tuple[int, int]:
        """(input tokens, requests) in the last 60 seconds."""
        self._expire(model, self._clock())
        return sum(e[1][0] for e in self._tokens[model]), len(self._requests[model])

    async def acquire(self, model: str, tokens: int) -> tuple[float, list]:
        """Wait until `tokens` more input tokens and one more request fit the
        model's limits. Returns (seconds waited, slot to correct later)."""
        tpm, rpm = self.limits(model)
        lock = self._locks.setdefault(model, asyncio.Lock())
        waited = 0.0
        async with lock:
            while True:
                now = self._clock()
                self._expire(model, now)
                used = sum(e[1][0] for e in self._tokens[model])
                count = len(self._requests[model])
                over_tokens = tpm and used + tokens > tpm and self._tokens[model]
                over_requests = rpm and count + 1 > rpm
                if not over_tokens and not over_requests:
                    break
                # Wait until the oldest entry that is in the way leaves the window.
                blocking = []
                if over_tokens:
                    blocking.append(self._tokens[model][0][0])
                if over_requests and self._requests[model]:
                    blocking.append(self._requests[model][0])
                oldest = min(blocking) if blocking else now
                delay = max(0.05, _WINDOW - (now - oldest))
                await self._sleep(delay)
                waited += delay
            slot = [tokens]
            self._tokens[model].append((now, slot))
            self._requests[model].append(now)
        return waited, slot

    def record_actual(self, model: str, slot: list, estimate: int, actual: int) -> None:
        """Replace the estimate in the window with the real count, and learn the ratio."""
        if actual <= 0:
            return
        slot[0] = actual
        if estimate > 0:
            prev = self._ratio.get(model, actual / estimate)
            self._ratio[model] = 0.7 * prev + 0.3 * (actual / estimate)


PACER = Pacer()


# ---------------------------------------------------------------------------
# The plugin
# ---------------------------------------------------------------------------

class LlmTrafficPlugin(BasePlugin):
    def __init__(self, pacer: Pacer | None = None):
        super().__init__(name="llm_traffic")
        self.pacer = pacer or PACER
        self._pending: dict[tuple, tuple] = {}

    @staticmethod
    def _key(ctx: CallbackContext) -> tuple:
        return (getattr(ctx, "invocation_id", ""), getattr(ctx, "agent_name", ""))

    async def before_model_callback(self, *, callback_context: CallbackContext,
                                    llm_request: LlmRequest) -> Optional[LlmResponse]:
        masked = saved = 0
        if config.CONTEXT_PROTECT_TOKENS > 0 and llm_request.contents:
            llm_request.contents, masked, saved = mask_old_tool_output(
                llm_request.contents, config.CONTEXT_PROTECT_TOKENS, config.CONTEXT_MIN_PRUNABLE_TOKENS)
        model = llm_request.model or ""
        estimate = estimate_tokens(request_chars(llm_request))
        waited, slot = await self.pacer.acquire(model, self.pacer.calibrated(model, estimate))
        self._pending[self._key(callback_context)] = (model, slot, estimate, masked, saved, waited)
        return None

    async def after_model_callback(self, *, callback_context: CallbackContext,
                                   llm_response: LlmResponse) -> Optional[LlmResponse]:
        pending = self._pending.pop(self._key(callback_context), None)
        if not pending:
            return None
        model, slot, estimate, masked, saved, waited = pending
        usage = llm_response.usage_metadata
        actual = (usage.prompt_token_count or 0) if usage else 0
        out = (usage.candidates_token_count or 0) if usage else 0
        self.pacer.record_actual(model, slot, estimate, actual)
        window_tokens, window_requests = self.pacer.usage(model)
        line = (f"[llm] {model} agent={getattr(callback_context, 'agent_name', '?')} in={actual or slot[0]:,} "
                f"out={out:,}" + (f" masked={masked} (~{saved:,} tok)" if masked else "")
                + (f" waited={waited:.1f}s" if waited else "")
                + f" | last 60s: {window_tokens:,} tok, {window_requests} req")
        log.info(line)
        print(line, flush=True)
        return None

    async def on_model_error_callback(self, *, callback_context: CallbackContext, llm_request: LlmRequest,
                                      error: Exception) -> Optional[LlmResponse]:
        self._pending.pop(self._key(callback_context), None)
        return None


LLM_TRAFFIC = LlmTrafficPlugin()
