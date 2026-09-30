"""
Turns a call to a tool that does not exist into an error the model can read,
instead of an exception that kills the whole run.

Newer Gemini models sometimes call tools they were trained with but this app
never declared -- most often a code interpreter (`google:python_interpreter`,
`code_execution`). ADK raises `ValueError: Tool '...' not found` for that, and
the run ends mid reverse-engineering. Returned as a tool response instead, the
same model reads "that tool does not exist, these do" and carries on with the
real tools, which is what happens with any other tool error.

Installed once as a runner plugin (agents/__init__.py), so it covers every
agent in every pattern. Only unknown-tool errors are handled; an exception
raised inside a real tool propagates exactly as before. A model that keeps
inventing tools is stopped after `MAX_UNKNOWN_CALLS` in one run, so the guard
can never turn a hard failure into an endless, billable loop.
"""
import re
from collections import defaultdict
from typing import Any, Optional

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

#: Unknown-tool calls tolerated per invocation before the original error is raised.
MAX_UNKNOWN_CALLS = 5

_AVAILABLE = re.compile(r"Available tools:\s*(?P<tools>[^\n]*)")
_CODE_EXECUTION = re.compile(r"python|interpreter|code_?exec|run_?code|execute_?code|sandbox", re.IGNORECASE)


def is_unknown_tool_error(tool: BaseTool, error: Exception) -> bool:
    """ADK's own marker for a call to an undeclared tool (flows/llm_flows/functions.py)."""
    return isinstance(error, ValueError) and tool.description == "Tool not found" and "not found" in str(error)


def available_tools(error: Exception) -> list[str]:
    match = _AVAILABLE.search(str(error))
    return [t.strip() for t in match.group("tools").split(",") if t.strip()] if match else []


def unknown_tool_response(name: str, tools: list[str]) -> dict[str, Any]:
    """The tool result the model sees in place of the crash."""
    message = f"Tool '{name}' does not exist in this environment and was not run."
    if _CODE_EXECUTION.search(name):
        # Stated from the tools this agent really has: a validator holds
        # run_command, a reverse-engineering agent holds only read tools.
        message += " There is no code interpreter here."
        if "run_command" in tools:
            message += " The only commands you can run are the build commands run_command accepts."
        else:
            message += " You cannot run code or commands."
        inspect = [t for t in ("search_files", "list_files", "read_file") if t in tools]
        if inspect:
            message += " To inspect the repository use " + ", ".join(inspect) + "."
    if tools:
        message += " Call only these tools: " + ", ".join(tools) + "."
    return {"error": message}


class UnknownToolGuard(BasePlugin):
    def __init__(self, max_calls: int = MAX_UNKNOWN_CALLS) -> None:
        super().__init__(name="unknown_tool_guard")
        self.max_calls = max_calls
        self._counts: dict[str, int] = defaultdict(int)

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> Optional[dict]:
        if not is_unknown_tool_error(tool, error):
            return None
        key = tool_context.invocation_id
        self._counts[key] += 1
        if self._counts[key] > self.max_calls:
            print(f"[unknown-tool] '{tool.name}': limit of {self.max_calls} unknown tool calls reached — failing the run",
                  flush=True)
            return None  # ADK re-raises the original error
        print(f"[unknown-tool] model called undeclared tool '{tool.name}' "
              f"({self._counts[key]}/{self.max_calls}) — returned an error to the model", flush=True)
        return unknown_tool_response(tool.name, available_tools(error))

    async def after_run_callback(self, *, invocation_context) -> None:
        self._counts.pop(invocation_context.invocation_id, None)
