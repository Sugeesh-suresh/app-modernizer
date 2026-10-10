"""
`ToolContext` for the tool modules, with or without google-adk installed.

The tool functions only use it as a type: ADK reads the annotation to inject
the real context, and the Gemini CLI path (cli/mcp_server.py) passes its own
object with the same `state` / `actions` attributes. Importing it from here
lets the deterministic tools (and the skill-learning callbacks, which
only read `callback_context.state`) load in an environment that has no ADK at all.
"""
from typing import Any

try:
    from google.adk.tools import ToolContext
    from google.adk.agents.callback_context import CallbackContext
except ImportError:  # Gemini CLI install: requirements-cli.txt has no google-adk
    ToolContext = Any  # type: ignore[misc,assignment]
    CallbackContext = Any  # type: ignore[misc,assignment]

__all__ = ["CallbackContext", "ToolContext"]
