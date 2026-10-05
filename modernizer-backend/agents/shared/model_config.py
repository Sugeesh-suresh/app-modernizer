import re
from typing import AsyncGenerator, Optional

from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from google.genai.errors import ClientError

from .. import config


def _retry(attempts: int) -> types.HttpRetryOptions:
    return types.HttpRetryOptions(attempts=max(1, attempts), initial_delay=config.LLM_RETRY_INITIAL_DELAY,
                                  max_delay=config.LLM_RETRY_MAX_DELAY)


def _for_another_model(llm_request: LlmRequest, model: str) -> LlmRequest:
    """The same request for a different model: identical instruction, history
    and tools. Thinking parts and thought signatures are dropped — they belong
    to the model that produced them; no file content or tool result is lost."""
    req = llm_request.model_copy(deep=True)
    req.model = model
    for content in req.contents or []:
        kept = []
        for part in content.parts or []:
            if part.thought:
                continue
            if part.thought_signature:
                part.thought_signature = None
            kept.append(part)
        content.parts = kept or [types.Part(text="")]
    return req


class FallbackGemini(Gemini):
    """A Gemini model that, when still rate-limited (429) after its own
    retries, sends the same request to `fallback_model` — the way Gemini CLI
    falls back from Pro to Flash (packages/core/src/fallback/handler.ts).
    Subclasses Gemini so ADK treats it exactly like one."""
    fallback_model: Optional[str] = None

    async def generate_content_async(self, llm_request: LlmRequest,
                                     stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        started = False
        try:
            async for response in super().generate_content_async(llm_request, stream):
                started = True
                yield response
            return
        except ClientError as exc:
            if exc.code != 429 or started or not self.fallback_model:
                raise
            primary = llm_request.model or self.model
        from .llm_traffic import PACER, estimate_tokens, request_chars
        req = _for_another_model(llm_request, self.fallback_model)
        estimate = estimate_tokens(request_chars(req))
        waited, slot = await PACER.acquire(self.fallback_model, PACER.calibrated(self.fallback_model, estimate))
        print(f"[llm] {primary} still rate-limited (429) after {config.LLM_FALLBACK_AFTER_ATTEMPTS} attempts — "
              f"this call falls back to {self.fallback_model}" + (f" (waited {waited:.1f}s)" if waited else ""),
              flush=True)
        fallback = Gemini(model=self.fallback_model, retry_options=_retry(config.LLM_RETRY_ATTEMPTS))
        async for response in fallback.generate_content_async(req, stream):
            usage = response.usage_metadata
            if usage and usage.prompt_token_count:
                PACER.record_actual(self.fallback_model, slot, estimate, usage.prompt_token_count)
            meta = dict(response.custom_metadata or {})
            meta["model_fallback"] = f"{primary} -> {self.fallback_model}"
            response.custom_metadata = meta
            yield response


# Which role an agent plays, from its name. Order matters: first match wins.
_ROLE_RULES: list[tuple[str, str]] = [
    (r"code_reviewer|reviewer", "review"),
    (r"skill_curator|curator|reporter", "report"),
    (r"plan", "plan"),
    (r"validator", "check"),
    (r"fixer", "fix"),
    (r"modifier|generator", "code"),
    (r"_re$|_re_|re_agent|module_re|findings|synthesis|mapper|classifier|^jsp_re|^discover_|^rule_extractor|^po_brd$|^ea_spec$|^ea_ui$", "analyse"),
]


def role_for(agent_name: str) -> str | None:
    for pattern, role in _ROLE_RULES:
        if re.search(pattern, agent_name):
            return role
    return None


def model_for_role(role: str | None) -> str:
    return (config.MODEL_ROLES.get(role or "", "") if role else "") or config.GEMINI_MODEL


def make_model(model_name: str | None = None, role: str | None = None) -> Gemini:
    """The model an agent uses: its role's model (MODEL_PLAN, MODEL_CHECK, …)
    or GEMINI_MODEL, with the SDK's retry enabled, and — when MODEL_FALLBACK
    is set and differs — a fallback for calls still rate-limited after
    LLM_FALLBACK_AFTER_ATTEMPTS.

    ADK turns a plain model-name string into `Gemini(retry_options=None)`, and
    the SDK treats None as "never retry" (google/genai/_api_client.py
    retry_args), so one 429 failed the whole step. The SDK's retry covers 408,
    429 and 5xx responses plus connection errors and timeouts.
    """
    name = model_name or model_for_role(role)
    fallback = config.MODEL_FALLBACK if config.MODEL_FALLBACK and config.MODEL_FALLBACK != name else None
    if fallback:
        return FallbackGemini(model=name, fallback_model=fallback,
                              retry_options=_retry(min(config.LLM_RETRY_ATTEMPTS, config.LLM_FALLBACK_AFTER_ATTEMPTS)))
    return Gemini(model=name, retry_options=_retry(config.LLM_RETRY_ATTEMPTS))


def assign_role_models(agents) -> dict[str, tuple[str | None, str]]:
    """Give every LlmAgent reachable from `agents` its role's model. Returns
    {agent name: (role, model)} — logged at startup so the mapping is visible."""
    from google.adk.agents import LlmAgent
    cache: dict[str | None, Gemini] = {}
    seen: set[int] = set()
    table: dict[str, tuple[str | None, str]] = {}

    def walk(agent) -> None:
        if id(agent) in seen:
            return
        seen.add(id(agent))
        if isinstance(agent, LlmAgent) and isinstance(agent.model, Gemini):
            role = role_for(agent.name)
            if role not in cache:
                cache[role] = make_model(role=role)
            agent.model = cache[role]
            table[agent.name] = (role, cache[role].model)
        for sub in getattr(agent, "sub_agents", None) or []:
            walk(sub)

    for agent in agents:
        walk(agent)
    return table


# Gemini's "thinking" budget is dynamic (unbounded) by default. Full-codebase
# generation agents ask for a large, mostly-mechanical text response (many
# files verbatim) rather than deep reasoning — left uncapped, the model can
# spend most or all of its output-token budget on thinking and hit
# MAX_TOKENS before emitting more than a couple of stray tokens of actual
# code. Capping the thinking budget guarantees the bulk of the token budget
# is reserved for the actual generated files.
CODE_GEN_CONFIG = types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_budget=8192),
)
