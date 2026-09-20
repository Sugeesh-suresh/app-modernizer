"""
Shared ADK agent callbacks for the Stella Modernizer pipeline.
"""
import contextlib
import fcntl
import json
import os
import pathlib
import re
from datetime import datetime
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


#: Learned-pattern entries kept per skill. Without a cap the section grows on
#: every failed build, and it is prompt text every later run pays for.
MAX_LEARNED_ENTRIES = 20

#: Set to "0"/"false" to stop the pipeline writing to its own skill files —
#: appropriate wherever the checkout is read-only or shared between deployments.
_LEARNING_ENABLED = os.getenv("MODERNIZER_SKILL_LEARNING", "1").lower() not in {"0", "false", "no"}

_LEARNED_HEADING = "## Learned Patterns"


@contextlib.contextmanager
def _locked(path: pathlib.Path):
    """Exclusive advisory lock around a skill file's read-modify-write.

    Concurrent sessions share one skills directory, so without this two runs
    read the same content and the second write silently discards the first —
    or interleaves into a file every later run then loads as its prompt.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    handle = None
    try:
        handle = open(lock_path, "w")
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    except OSError:
        # A lock we cannot take must not fail the migration; the write is skipped.
        yield
    finally:
        if handle is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(handle, fcntl.LOCK_UN)
                handle.close()


def _prune_learned(content: str, max_entries: int = MAX_LEARNED_ENTRIES) -> str:
    """Keep only the most recent *max_entries* `### ` blocks under the
    Learned Patterns heading."""
    head, sep, tail = content.partition(_LEARNED_HEADING)
    if not sep:
        return content
    blocks = re.split(r"(?=^### )", tail, flags=re.MULTILINE)
    lead, entries = blocks[0], [b for b in blocks[1:] if b.strip()]
    if len(entries) <= max_entries:
        return content
    return head + sep + lead + "".join(entries[-max_entries:])


def make_skill_update_callback(
    validation_key: str,
    skill_md_path: pathlib.Path,
    section_header: str,
):
    """Return an after_agent_callback that appends newly observed error patterns
    to the agent's own SKILL.md under a '## Learned Patterns' section.

    Called after each validate or fix iteration.  Only errors not already
    present in the file are appended, so the section grows incrementally
    across runs without duplication.  Returns None — it is a pure side-effect
    callback that does not alter the agent's output content.

    Args:
        validation_key:  Session-state key holding the JSON validation result
                         (e.g. "validation_result").
        skill_md_path:   Absolute path to the SKILL.md file to update.
        section_header:  Short label used as the sub-heading for each batch of
                         new learnings (e.g. "Validation Pass" or "Fix Pass").
    """

    def _update_skill(callback_context: CallbackContext) -> Optional[genai_types.Content]:
        if not _LEARNING_ENABLED:
            return None
        raw = (callback_context.state or {}).get(validation_key, "")
        if not raw:
            return None

        result = _parse_json_safely(raw)
        # Nothing to learn when the build is already clean.
        if result.get("passed") or not result.get("errors"):
            return None

        errors: list[str] = result["errors"]
        summary: str = result.get("summary", "")

        if not skill_md_path.exists():
            return None

        with _locked(skill_md_path):
            _append_learned(skill_md_path, errors, summary, section_header)
        return None

    def _append_learned(skill_md_path, errors, summary, section_header) -> None:
        try:
            content = skill_md_path.read_text(encoding="utf-8")
        except OSError:
            return

        # Skip errors the file already mentions (simple substring check).
        new_errors = [e for e in errors if e.strip() and e.strip() not in content]
        if not new_errors:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry_lines: list[str] = [f"\n### {section_header} — {timestamp}"]
        if summary:
            entry_lines.append(f"> {summary}")
        entry_lines.append("")
        for err in new_errors:
            entry_lines.append(f"- {err}")
        entry = "\n".join(entry_lines) + "\n"

        # Create the top-level section heading on first write.
        if _LEARNED_HEADING not in content:
            entry = "\n---\n\n" + _LEARNED_HEADING + "\n" + entry

        try:
            skill_md_path.write_text(_prune_learned(content + entry), encoding="utf-8")
        except OSError:
            return

    return _update_skill
