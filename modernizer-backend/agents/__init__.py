"""
The Stella Modernizer agents package.

The ADK registry (runners, session service, model assignment) lives in
agents/registry.py and is loaded on first use, so `from agents import
PATTERN_RUNNERS` works exactly as before while `from agents.shared import ...`
and `from agents import config` no longer build every ADK agent. That is what
lets the Gemini CLI path (cli/mcp_server.py) use the deterministic tools in an
environment without google-adk installed.
"""
import importlib

_REGISTRY_NAMES = frozenset({
    "APP_NAME", "USER_ID", "PATTERN_RUNNERS", "TARGET_LANGS", "MODEL_ASSIGNMENT",
    "UNKNOWN_TOOL_GUARD", "LLM_TRAFFIC", "session_service", "_ROOT_AGENTS", "_runner",
})


def __getattr__(name: str):
    if name in _REGISTRY_NAMES:
        registry = importlib.import_module(".registry", __name__)
        value = getattr(registry, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
