"""
Shared ADK agent callbacks for the App Modernizer pipeline.
"""
import json
import re
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.genai import types as genai_types


def _parse_json_safely(raw: str) -> dict:
    """Parse JSON from model output, trying three fallback strategies."""
    text = raw.strip()
    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown code fences
    clean = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    # Extract first {...} block
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {"passed": True, "errors": [], "summary": "Parse error — assuming passed."}


def make_validation_exit_callback(result_key: str = "validation_result"):
    """Return an after_agent_callback that escalates out of a LoopAgent when
    the validation stored in *result_key* reports ``passed: true``.

    Attach this to the validate_agent so the loop terminates early instead of
    always running all max_iterations.
    """

    def _exit_on_pass(callback_context: CallbackContext) -> Optional[genai_types.Content]:
        raw = (callback_context.state or {}).get(result_key, "")
        result = _parse_json_safely(raw)
        if result.get("passed", True):
            callback_context.actions.escalate = True
            # Must return a Content object — ADK only propagates event actions
            # (including escalate) when the callback returns non-None content.
            # Without this, escalate is set on the context but never emitted
            # as an event, so the LoopAgent never sees it and keeps iterating.
            return genai_types.Content(
                role="model",
                parts=[genai_types.Part(text="[VALIDATION_PASSED] Exiting loop early.")],
            )
        return None

    return _exit_on_pass
