"""
429 RESOURCE_EXHAUSTED must be retried, not end the run.

Without retry options the Google GenAI SDK makes a single attempt
(google/genai/_api_client.py `retry_args`: None -> stop_after_attempt(1)), and
ADK builds `Gemini(retry_options=None)` from a plain model name — so the first
quota error from a large repository failed the step. These tests run a real ADK
agent over real HTTP against a local stand-in for the Gemini endpoint that
answers 429 before succeeding.
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import errors, types

from agents import PATTERN_RUNNERS, config
from agents.shared.model_config import make_model

OK = {"candidates": [{"content": {"role": "model", "parts": [{"text": "analysis done"}]}, "finishReason": "STOP"}]}
QUOTA = {"error": {"code": 429, "message": "Resource has been exhausted (e.g. check quota).", "status": "RESOURCE_EXHAUSTED"}}


@pytest.fixture
def gemini_stub():
    """A local endpoint that fails the first `fail` requests with 429."""
    state = {"fail": 0, "hits": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state["hits"] += 1
            code, body = (429, QUOTA) if state["hits"] <= state["fail"] else (200, OK)
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()


def _run(stub, monkeypatch, attempts: int) -> str:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.setattr(config, "LLM_RETRY_ATTEMPTS", attempts)
    monkeypatch.setattr(config, "LLM_RETRY_INITIAL_DELAY", 0.01)
    monkeypatch.setattr(config, "LLM_RETRY_MAX_DELAY", 0.05)
    model = make_model("gemini-2.5-pro").model_copy(update={"base_url": stub["url"]})
    agent = LlmAgent(name="re_agent", model=model, instruction="Analyse.")
    service = InMemorySessionService()
    runner = Runner(app=App(name="retrytest", root_agent=agent), session_service=service)

    async def go():
        session = await service.create_session(app_name="retrytest", user_id="u")
        out = []
        async for event in runner.run_async(user_id="u", session_id=session.id,
                                            new_message=types.Content(role="user", parts=[types.Part(text="go")])):
            out += [p.text for p in (event.content.parts if event.content else []) if p.text]
        return " ".join(out)

    return asyncio.run(go())


def test_quota_errors_are_retried_and_the_run_completes(gemini_stub, monkeypatch):
    gemini_stub["fail"] = 3
    assert _run(gemini_stub, monkeypatch, attempts=8) == "analysis done"
    assert gemini_stub["hits"] == 4  # three 429s, then the success


def test_with_retries_disabled_the_first_429_fails_as_reported(gemini_stub, monkeypatch):
    gemini_stub["fail"] = 1
    with pytest.raises(errors.ClientError) as exc:
        _run(gemini_stub, monkeypatch, attempts=1)
    assert exc.value.code == 429 and gemini_stub["hits"] == 1


def test_a_quota_that_never_clears_gives_up_after_the_configured_attempts(gemini_stub, monkeypatch):
    gemini_stub["fail"] = 100
    with pytest.raises(errors.ClientError):
        _run(gemini_stub, monkeypatch, attempts=4)
    assert gemini_stub["hits"] == 4


def test_every_agent_in_every_pipeline_has_retry_enabled():
    missing = []
    for pattern, runners in PATTERN_RUNNERS.items():
        for key, runner in runners.items():
            stack = [runner.agent]
            while stack:
                agent = stack.pop()
                stack += list(getattr(agent, "sub_agents", None) or [])
                if isinstance(agent, LlmAgent):
                    retry = agent.canonical_model.retry_options
                    if not retry or (retry.attempts or 0) < 2:
                        missing.append(f"{pattern}/{key}/{agent.name}")
    assert not missing, missing


def test_a_429_that_outlasts_the_retries_is_explained_to_the_user():
    import main
    exc = errors.ClientError(429, QUOTA)
    message = main._describe_error(exc)
    assert "429 RESOURCE_EXHAUSTED" in message and f"{config.LLM_RETRY_ATTEMPTS} attempts" in message
    assert main._describe_error(ValueError("other")) == "other"
