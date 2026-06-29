"""
Unit tests for make_validation_exit_callback.

Verifies that the after_agent_callback:
  - Returns Content + sets escalate=True when validation passes
  - Returns None + leaves escalate unset when validation fails
  - Handles edge cases: empty result, malformed JSON, missing keys,
    markdown-fenced JSON, and a custom result_key.
"""
import json
import pytest

from google.adk.events import EventActions
from google.genai import types as genai_types

from agents.shared.callbacks import make_validation_exit_callback, _parse_json_safely


# ---------------------------------------------------------------------------
# Minimal stub that mimics the parts of CallbackContext the callback uses
# ---------------------------------------------------------------------------

class _FakeState(dict):
    """dict subclass so .get() works normally."""


class _FakeCallbackContext:
    def __init__(self, state_dict: dict):
        self.state = _FakeState(state_dict)
        self.actions = EventActions()


def _make_ctx(validation_json: str, key: str = "validation_result") -> _FakeCallbackContext:
    return _FakeCallbackContext({key: validation_json})


# ---------------------------------------------------------------------------
# _parse_json_safely
# ---------------------------------------------------------------------------

class TestParseJsonSafely:
    def test_plain_json(self):
        raw = '{"passed": true, "errors": [], "summary": "ok"}'
        result = _parse_json_safely(raw)
        assert result == {"passed": True, "errors": [], "summary": "ok"}

    def test_markdown_fenced_json(self):
        raw = '```json\n{"passed": false, "errors": ["bad import"], "summary": "fail"}\n```'
        result = _parse_json_safely(raw)
        assert result["passed"] is False
        assert result["errors"] == ["bad import"]

    def test_json_embedded_in_prose(self):
        raw = 'Here is the result:\n{"passed": true, "errors": [], "summary": "clean"}\nDone.'
        result = _parse_json_safely(raw)
        assert result["passed"] is True

    def test_empty_string_returns_fallback(self):
        result = _parse_json_safely("")
        assert result["passed"] is True   # fallback assumes passed
        assert result["errors"] == []

    def test_completely_invalid_returns_fallback(self):
        result = _parse_json_safely("not json at all !!!")
        assert result["passed"] is True   # fallback assumes passed


# ---------------------------------------------------------------------------
# make_validation_exit_callback — pass scenarios
# ---------------------------------------------------------------------------

class TestValidationExitCallbackPass:
    def test_passed_true_returns_content(self):
        cb = make_validation_exit_callback("validation_result")
        ctx = _make_ctx('{"passed": true, "errors": [], "summary": "Code compiles cleanly."}')

        result = cb(callback_context=ctx)

        assert result is not None, "Must return Content so ADK emits the escalate event"
        assert isinstance(result, genai_types.Content)

    def test_passed_true_sets_escalate(self):
        cb = make_validation_exit_callback("validation_result")
        ctx = _make_ctx('{"passed": true, "errors": [], "summary": "Code compiles cleanly."}')

        cb(callback_context=ctx)

        assert ctx.actions.escalate is True, "LoopAgent reads escalate from the emitted event"

    def test_passed_true_content_has_text(self):
        cb = make_validation_exit_callback("validation_result")
        ctx = _make_ctx('{"passed": true, "errors": [], "summary": "Build OK."}')

        result = cb(callback_context=ctx)

        assert result.parts, "Content must have at least one part"
        assert result.parts[0].text, "Part must have non-empty text"

    def test_markdown_fenced_passed_true_escalates(self):
        """Validate agent sometimes wraps JSON in markdown fences."""
        raw = '```json\n{"passed": true, "errors": [], "summary": "Clean."}\n```'
        cb = make_validation_exit_callback("validation_result")
        ctx = _make_ctx(raw)

        result = cb(callback_context=ctx)

        assert result is not None
        assert ctx.actions.escalate is True

    def test_empty_result_key_escalates(self):
        """Empty string → fallback assumes passed → should escalate."""
        cb = make_validation_exit_callback("validation_result")
        ctx = _make_ctx("")

        result = cb(callback_context=ctx)

        assert result is not None
        assert ctx.actions.escalate is True

    def test_missing_result_key_escalates(self):
        """Key not in state → fallback assumes passed → should escalate."""
        cb = make_validation_exit_callback("validation_result")
        ctx = _FakeCallbackContext({})  # no validation_result key

        result = cb(callback_context=ctx)

        assert result is not None
        assert ctx.actions.escalate is True


# ---------------------------------------------------------------------------
# make_validation_exit_callback — fail scenarios
# ---------------------------------------------------------------------------

class TestValidationExitCallbackFail:
    def test_passed_false_returns_none(self):
        cb = make_validation_exit_callback("validation_result")
        ctx = _make_ctx('{"passed": false, "errors": ["missing import"], "summary": "Errors found."}')

        result = cb(callback_context=ctx)

        assert result is None, "Must return None so fix_agent runs next"

    def test_passed_false_does_not_set_escalate(self):
        cb = make_validation_exit_callback("validation_result")
        ctx = _make_ctx('{"passed": false, "errors": ["bad type"], "summary": "Type error."}')

        cb(callback_context=ctx)

        assert ctx.actions.escalate is None, "escalate must stay None so LoopAgent continues"

    def test_multiple_errors_no_escalate(self):
        errors = ["missing import A", "undefined class B", "wrong annotation C"]
        raw = json.dumps({"passed": False, "errors": errors, "summary": "3 errors."})
        cb = make_validation_exit_callback("validation_result")
        ctx = _make_ctx(raw)

        result = cb(callback_context=ctx)

        assert result is None
        assert ctx.actions.escalate is None


# ---------------------------------------------------------------------------
# Custom result_key
# ---------------------------------------------------------------------------

class TestCustomResultKey:
    def test_custom_key_pass(self):
        cb = make_validation_exit_callback("my_custom_key")
        ctx = _FakeCallbackContext({"my_custom_key": '{"passed": true, "errors": [], "summary": "ok"}'})

        result = cb(callback_context=ctx)

        assert result is not None
        assert ctx.actions.escalate is True

    def test_custom_key_fail(self):
        cb = make_validation_exit_callback("my_custom_key")
        ctx = _FakeCallbackContext({"my_custom_key": '{"passed": false, "errors": ["oops"], "summary": "fail"}'})

        result = cb(callback_context=ctx)

        assert result is None
        assert ctx.actions.escalate is None

    def test_wrong_key_not_in_state_escalates(self):
        """Wrong key → empty string → fallback → escalates."""
        cb = make_validation_exit_callback("my_custom_key")
        ctx = _FakeCallbackContext({"validation_result": '{"passed": false}'})  # wrong key

        result = cb(callback_context=ctx)

        assert result is not None   # fallback assumes passed
        assert ctx.actions.escalate is True
