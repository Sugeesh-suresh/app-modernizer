"""
A model calling a tool the app never declared -- `google:python_interpreter`,
which newer Gemini models reach for -- must not end the run.

Driven through a real ADK Runner with a scripted model, so this exercises the
same path as the production failure: `_get_tool` raising, the plugin's
on_tool_error_callback turning it into a tool response, and the model's next
turn receiving that response.
"""
import asyncio
from typing import AsyncGenerator

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types

from agents import PATTERN_RUNNERS, UNKNOWN_TOOL_GUARD
from agents.shared.unknown_tool_guard import UnknownToolGuard


def list_files() -> str:
    """List the workspace."""
    return "pom.xml"


class ScriptedModel(BaseLlm):
    """Calls `google:python_interpreter` `bad_calls` times, then answers. Records
    every function response it is shown."""
    bad_calls: int = 1
    seen: list = []

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        responses = [p.function_response for c in llm_request.contents for p in (c.parts or []) if p.function_response]
        self.seen[:] = [dict(r.response or {}) for r in responses]
        if len(responses) < self.bad_calls:
            part = types.Part(function_call=types.FunctionCall(name="google:python_interpreter", args={"code": "print(1)"}))
        else:
            part = types.Part(text="Analysis complete.")
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def _run(model: ScriptedModel, plugins: list) -> list[str]:
    agent = LlmAgent(name="re_agent", model=model, tools=[FunctionTool(list_files)], instruction="Analyse.")
    service = InMemorySessionService()
    runner = Runner(app=App(name="guardtest", root_agent=agent, plugins=plugins), session_service=service)

    async def go():
        session = await service.create_session(app_name="guardtest", user_id="u")
        texts = []
        async for event in runner.run_async(user_id="u", session_id=session.id,
                                            new_message=types.Content(role="user", parts=[types.Part(text="go")])):
            texts += [p.text for p in (event.content.parts if event.content else []) if p.text]
        return texts

    return asyncio.run(go())


def test_without_the_guard_the_run_dies_exactly_as_reported():
    with pytest.raises(ValueError, match="Tool 'google:python_interpreter' not found"):
        _run(ScriptedModel(model="scripted"), plugins=[])


def test_with_the_guard_the_model_is_told_and_the_run_completes():
    model = ScriptedModel(model="scripted")
    texts = _run(model, plugins=[UnknownToolGuard()])

    assert texts == ["Analysis complete."]
    error = model.seen[0]["error"]
    assert "'google:python_interpreter' does not exist" in error
    assert "no code interpreter" in error and "list_files" in error


def test_a_model_that_keeps_inventing_tools_is_stopped():
    with pytest.raises(ValueError, match="not found"):
        _run(ScriptedModel(model="scripted", bad_calls=10), plugins=[UnknownToolGuard(max_calls=3)])


def test_errors_inside_real_tools_are_not_swallowed():
    def broken() -> str:
        """Always fails."""
        raise RuntimeError("real tool failure")

    class CallsBroken(ScriptedModel):
        async def generate_content_async(self, llm_request, stream=False):
            yield LlmResponse(content=types.Content(role="model", parts=[
                types.Part(function_call=types.FunctionCall(name="broken", args={}))]))

    agent = LlmAgent(name="a", model=CallsBroken(model="scripted"), tools=[FunctionTool(broken)])
    service = InMemorySessionService()
    runner = Runner(app=App(name="guardtest", root_agent=agent, plugins=[UnknownToolGuard()]), session_service=service)

    async def go():
        session = await service.create_session(app_name="guardtest", user_id="u")
        async for _ in runner.run_async(user_id="u", session_id=session.id,
                                        new_message=types.Content(role="user", parts=[types.Part(text="go")])):
            pass

    with pytest.raises(RuntimeError, match="real tool failure"):
        asyncio.run(go())


def test_every_pipeline_runner_carries_the_guard():
    for pattern, runners in PATTERN_RUNNERS.items():
        for key, runner in runners.items():
            assert UNKNOWN_TOOL_GUARD in runner.plugin_manager.plugins, f"{pattern}/{key}"
