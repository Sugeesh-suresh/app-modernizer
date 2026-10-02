"""
Model traffic: masking old tool output (Gemini CLI's approach), pacing per
model, per-role models, and the 429 fallback — tested through real ADK runners
with scripted models where it matters.
"""
import asyncio
import json

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.adk.models.google_llm import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types
from google.genai.errors import ClientError

from agents import MODEL_ASSIGNMENT, config
from agents.shared import llm_traffic as lt, model_config as mc
from agents.shared import workspace_tools


def _fr(name, text, id_=None):
    return types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id=id_, name=name, response={"result": text}))])


def _fc(name, args, id_):
    return types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(id=id_, name=name, args=args))])


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------

class TestMasking:
    def _history(self, n=6, size=40_000):
        out = [types.Content(role="user", parts=[types.Part(text="apply the task")])]
        for i in range(n):
            out += [_fc("read_file", {"path": f"F{i}.java"}, f"c{i}"), _fr("read_file", "x" * size, f"c{i}")]
        out.append(types.Content(role="model", parts=[types.Part(text="thinking about it")]))
        return out

    def test_old_outputs_are_masked_and_the_newest_kept(self):
        history = self._history()
        new, masked, saved = lt.mask_old_tool_output(history, protect_tokens=25_000, min_prunable_tokens=10_000)
        texts = [json.dumps(p.function_response.response) for c in new for p in c.parts or [] if p.function_response]
        assert masked == 4 and saved > 30_000
        assert all(lt.MASK_TAG in t for t in texts[:4]) and all(lt.MASK_TAG not in t for t in texts[4:])
        assert "read_file(path='F0.java')" in texts[0] and "read it again" in texts[0]
        # The caller's history is never mutated.
        assert all(lt.MASK_TAG not in json.dumps(p.function_response.response)
                   for c in history for p in c.parts or [] if p.function_response)

    def test_nothing_is_masked_below_the_prunable_threshold(self):
        new, masked, _ = lt.mask_old_tool_output(self._history(n=3, size=20_000), 10_000, 50_000)
        assert masked == 0

    def test_the_latest_turn_and_skill_loads_are_never_masked(self):
        history = [_fr("load_skill", "S" * 400_000), _fr("read_file", "x" * 400_000)]
        new, masked, _ = lt.mask_old_tool_output(history, 1, 1)
        assert masked == 0                               # skill exempt; read_file is the latest turn

    def test_masking_is_stable_when_reapplied(self):
        once, _, _ = lt.mask_old_tool_output(self._history(), 25_000, 10_000)
        twice, masked, _ = lt.mask_old_tool_output(once, 25_000, 10_000)
        assert masked == 0 and [c.parts for c in once] == [c.parts for c in twice]


# ---------------------------------------------------------------------------
# Pacing
# ---------------------------------------------------------------------------

class _Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def now(self):
        return self.t

    async def sleep(self, d):
        self.slept.append(d)
        self.t += d


class TestPacing:
    def test_waits_for_the_window_instead_of_exceeding_tpm(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_MAX_TPM", 100_000)
        monkeypatch.setattr(config, "LLM_MAX_RPM", 0)
        monkeypatch.setattr(config, "LLM_LIMITS", "")
        clock = _Clock()
        pacer = lt.Pacer(clock=clock.now, sleep=clock.sleep)
        asyncio.run(pacer.acquire("m", 60_000))
        clock.t += 10
        waited, _ = asyncio.run(pacer.acquire("m", 60_000))      # 120K > 100K in the window
        assert waited == pytest.approx(50.0) and pacer.usage("m") == (60_000, 1)

    def test_rpm_and_per_model_limits(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_LIMITS", "pro=tpm:0,rpm:2;flash=tpm:10")
        clock = _Clock()
        pacer = lt.Pacer(clock=clock.now, sleep=clock.sleep)
        for _ in range(2):
            assert asyncio.run(pacer.acquire("pro", 5))[0] == 0
        assert asyncio.run(pacer.acquire("pro", 5))[0] == pytest.approx(60.0)
        # A single request bigger than the limit never waits forever on an empty window.
        assert asyncio.run(pacer.acquire("flash", 50))[0] == 0

    def test_no_limits_means_no_waiting(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_MAX_TPM", 0)
        monkeypatch.setattr(config, "LLM_MAX_RPM", 0)
        monkeypatch.setattr(config, "LLM_LIMITS", "")
        pacer = lt.Pacer()
        assert all(asyncio.run(pacer.acquire("m", 10**9))[0] == 0 for _ in range(5))

    def test_calibration_learns_from_real_counts(self):
        pacer = lt.Pacer()
        slot = [1000]
        pacer.record_actual("m", slot, estimate=1000, actual=1500)
        assert slot == [1500] and pacer.calibrated("m", 1000) == 1500

    def test_parse_limits(self):
        assert lt.parse_limits("gemini-2.5-pro=tpm:400000,rpm:50; gemini-2.5-flash=tpm:1500000") == {
            "gemini-2.5-pro": (400000, 50), "gemini-2.5-flash": (1500000, 0)}


# ---------------------------------------------------------------------------
# Through a real ADK runner: an agent reading many large files
# ---------------------------------------------------------------------------

class _Reader(BaseLlm):
    """Reads F0..F5, re-reads F0 if it was masked, then finishes. Records what it was sent."""
    sizes: list = []
    saw_masked: list = []

    async def generate_content_async(self, req, stream=False):
        self.sizes.append(lt.request_chars(req))
        responses = [p.function_response for c in req.contents for p in c.parts or [] if p.function_response]
        self.saw_masked.append(sum(lt.MASK_TAG in json.dumps(r.response) for r in responses))
        n = len(responses)
        if n < 6:
            call = types.FunctionCall(name="read_file", args={"path": f"F{n}.java"})
        elif n == 6 and self.saw_masked[-1]:
            call = types.FunctionCall(name="read_file", args={"path": "F0.java"})      # re-read from disk
        else:
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="done")]),
                              usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=1))
            return
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]),
                          usage_metadata=types.GenerateContentResponseUsageMetadata(
                              prompt_token_count=lt.estimate_tokens(self.sizes[-1])))


def test_a_real_agent_run_masks_old_reads_and_can_re_read(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONTEXT_PROTECT_TOKENS", 12_000)
    monkeypatch.setattr(config, "CONTEXT_MIN_PRUNABLE_TOKENS", 5_000)
    monkeypatch.setattr(config, "READ_FILE_MAX_CHARS", 30_000)
    for i in range(6):
        (tmp_path / f"F{i}.java").write_text("\n".join(f"// line {j} of file {i} " + "x" * 40 for j in range(500)))
    model = _Reader(model="scripted")
    model.sizes, model.saw_masked = [], []
    agent = LlmAgent(name="modifier_agent", model=model, instruction="go",
                     tools=[FunctionTool(workspace_tools.read_file)])
    service = InMemorySessionService()
    runner = Runner(app=App(name="t", root_agent=agent, plugins=[lt.LlmTrafficPlugin(lt.Pacer())]),
                    session_service=service)
    session = asyncio.run(service.create_session(app_name="t", user_id="u", state={"workspace_dir": str(tmp_path)}))

    async def run():
        async for _ in runner.run_async(user_id="u", session_id=session.id,
                                        new_message=types.Content(role="user", parts=[types.Part(text="go")])):
            pass
    asyncio.run(run())

    per_file = len((tmp_path / "F0.java").read_text())
    assert max(model.saw_masked) >= 3                                 # older reads were masked
    assert max(model.sizes) < 4 * per_file                            # never resent all six files
    assert len(model.sizes) == 8                                      # 6 reads + 1 re-read + final answer
    # The session keeps the full outputs: only the requests were trimmed.
    stored = asyncio.run(service.get_session(app_name="t", user_id="u", session_id=session.id))
    full = [e for e in stored.events for p in (e.content.parts if e.content else []) if p.function_response
            and lt.MASK_TAG not in json.dumps(p.function_response.response)]
    assert len(full) == 7


# ---------------------------------------------------------------------------
# Per-role models and the 429 fallback
# ---------------------------------------------------------------------------

def test_every_agent_has_a_role():
    assert MODEL_ASSIGNMENT and all(role for role, _ in MODEL_ASSIGNMENT.values())
    assert MODEL_ASSIGNMENT["java11_plan"][0] == "plan"
    assert MODEL_ASSIGNMENT["validator_stage3"][0] == "check"
    assert MODEL_ASSIGNMENT["backend_generator_agent"][0] == "code"
    assert MODEL_ASSIGNMENT["dependency_mapper"][0] == "analyse"


def test_role_models_come_from_settings(monkeypatch):
    monkeypatch.setattr(config, "MODEL_ROLES", {**config.MODEL_ROLES, "check": "gemini-2.5-flash", "plan": ""})
    monkeypatch.setattr(config, "GEMINI_MODEL", "gemini-2.5-pro")
    monkeypatch.setattr(config, "MODEL_FALLBACK", "")
    assert mc.make_model(role="check").model == "gemini-2.5-flash"
    assert mc.make_model(role="plan").model == "gemini-2.5-pro"
    assert type(mc.make_model(role="plan")) is Gemini


def test_a_429_falls_back_to_the_fallback_model_with_the_same_request(monkeypatch):
    monkeypatch.setattr(config, "MODEL_FALLBACK", "gemini-2.5-flash")
    sent = []

    async def fake(self, llm_request, stream=False):
        sent.append((llm_request.model, [p.text for c in llm_request.contents for p in c.parts],
                     [bool(p.thought_signature) for c in llm_request.contents for p in c.parts]))
        if llm_request.model == "gemini-2.5-pro":
            raise ClientError(429, {"error": {"code": 429, "message": "exhausted", "status": "RESOURCE_EXHAUSTED"}})
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="ok")]))

    monkeypatch.setattr(Gemini, "generate_content_async", fake)
    model = mc.make_model("gemini-2.5-pro")
    assert isinstance(model, mc.FallbackGemini) and isinstance(model, Gemini)
    req = LlmRequest(model="gemini-2.5-pro", contents=[
        types.Content(role="user", parts=[types.Part(text="task")]),
        types.Content(role="model", parts=[types.Part(text="reasoning", thought=True),
                                           types.Part(text="answer", thought_signature=b"sig")])])

    async def run():
        return [r async for r in model.generate_content_async(req)]
    responses = asyncio.run(run())
    assert [m for m, _, _ in sent] == ["gemini-2.5-pro", "gemini-2.5-flash"]
    assert sent[1][1] == ["task", "answer"] and not any(sent[1][2])        # same history, own reasoning dropped
    assert responses[0].custom_metadata["model_fallback"] == "gemini-2.5-pro -> gemini-2.5-flash"
    assert req.contents[1].parts[0].thought                                 # the original request untouched


def test_other_errors_do_not_fall_back(monkeypatch):
    monkeypatch.setattr(config, "MODEL_FALLBACK", "gemini-2.5-flash")

    async def fake(self, llm_request, stream=False):
        raise ClientError(400, {"error": {"code": 400, "message": "bad", "status": "INVALID_ARGUMENT"}})
        yield

    monkeypatch.setattr(Gemini, "generate_content_async", fake)

    async def run():
        return [r async for r in mc.make_model("gemini-2.5-pro").generate_content_async(LlmRequest(model="gemini-2.5-pro"))]
    with pytest.raises(ClientError):
        asyncio.run(run())
