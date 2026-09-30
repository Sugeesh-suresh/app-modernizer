"""
Learned fixes: build errors a run hit, and the change that resolved them, fed
back into the skills of the agents that write the code — so the next run of the
same pattern avoids the error instead of rediscovering it.

The older mechanism (callbacks.make_skill_update_callback) appends the raw error
text to the validate / fix skills. That records *that* something failed — with
this repository's paths — but not how it was fixed, and it never reaches the
modifier, the one agent that could have avoided it.

Here, in three steps:

1. Capture (after each fix pass). The fixer's skill asks it to state, for each
   issue it fixed, the error verbatim, the cause and a resolution written for
   any codebase (a `## Lessons` block in its output). Only lessons whose error
   is one the validator actually reported are kept; they are held as pending.
2. Verify (after the next validation). A pending lesson is published only if
   that validation no longer reports its error, or the build passed. A
   resolution that did not work is dropped — an unverified guess is never
   written into a skill.
3. Publish. Verified lessons go under `## Learned Fixes` in the pattern's
   modifier / generator skill and in its fix skill: paths and line numbers
   removed, one entry per distinct error, newest kept, capped.

MODERNIZER_SKILL_LEARNING=0 turns publishing off, as it does for the older one.
"""
import json
import pathlib
import re
from datetime import datetime
from typing import Callable, Optional

from google.adk.agents.callback_context import CallbackContext
from google.genai import types as genai_types

from .callbacks import _LEARNING_ENABLED, _locked, _parse_json_safely

HEADING = "## Learned Fixes"
INTRO = (
    "_Written automatically after verified fixes. Each entry is a build error a previous run of this "
    "pattern hit after this step, and the change that made the next build stop reporting it. Apply the "
    "resolution up front wherever the same situation occurs; it is not specific to any one repository._"
)
MAX_ENTRIES = 25
_FIELD_MAX = 500

# A file location: a path whose last segment has an extension, or a bare file
# name — with an unambiguous source extension, or followed by a line reference
# (bare `jakarta.sql` or `javax.xml` are package names, not files). Line
# references: `:12`, `:12:8`, Maven's `:[12,8]`, tsc's `(12,8)`.
_REF = r"(?::\[\d+,\d+\]|\(\d+,\d+\)|:\d+(?::\d+)?)"
_PATH = re.compile(
    r"(?:[\w.\-$]+[/\\])+[\w\-$]+\.[A-Za-z]{1,10}" + _REF + "?"
    r"|\b[\w\-$]+\.(?:java|kt|kts|groovy|gradle|jsp|jspf|tsx?|jsx|scss|css|html|pks|pkb|plsql)\b" + _REF + "?"
    r"|\b[\w\-$]+\.[A-Za-z]{1,10}" + _REF
)
_LINE_REF = re.compile(r"\[\d+(?:,\d+)?\]|\bline \d+\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Text handling
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    """One line of plain text, safe to place in a markdown list: no headings,
    no HTML comments, bounded length."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = " ".join(text.split()).strip().strip("`").strip()
    text = re.sub(r"^#+\s*", "", text)
    return text[:_FIELD_MAX]


def generalise(error: str) -> str:
    """The error without this repository's location: a leading `<path>:<line> —`
    (including any directory prefix with spaces before it) is dropped, and any
    other path or line reference is replaced."""
    text = error.strip()
    first = _PATH.search(text)
    if first:
        rest = text[first.end():]
        after = re.match(r"\s*(?:[—–:\-]+|error:|\s)\s*", rest)
        message = rest[after.end():] if after else ""
        if after and len(message.strip()) >= 8:
            text = message
    text = _PATH.sub("<file>", text)
    text = _LINE_REF.sub("", text)
    text = re.sub(r"^\s*(?:\[[A-Za-z]+\]\s*)+", "", text)
    return _clean(text)


def key(error: str) -> str:
    """What two reports of the same error have in common."""
    text = generalise(error).lower()
    text = re.sub(r"<file>", " ", text)
    text = re.sub(r"[^a-z0-9._$]+", " ", text)
    return " ".join(text.split())


def parse_lessons(fix_output: str) -> list[dict]:
    """The `## Lessons` block of a fixer's output: `- Error:` items, each with
    `Cause:` and `Resolution:` fields, any of which may wrap onto more lines."""
    if not fix_output:
        return []
    _, sep, block = fix_output.partition("## Lessons")
    if not sep:
        return []
    block = re.split(r"^#{1,2} ", block, maxsplit=1, flags=re.MULTILINE)[0]
    out = []
    for item in re.split(r"^\s*[-*]\s*\**Error\**\s*:\**", block, flags=re.MULTILINE | re.IGNORECASE)[1:]:
        parts = re.split(r"^\s*[-*]?\s*\**(Cause|Resolution)\**\s*:\**", item, flags=re.MULTILINE | re.IGNORECASE)
        lesson = {"error": _clean(parts[0])}
        for name, text in zip(parts[1::2], parts[2::2]):
            lesson[name.lower()] = _clean(text)
        if all(lesson.get(k) for k in ("error", "cause", "resolution")):
            out.append(lesson)
    return out


def _errors(result: dict) -> list[str]:
    return [e for e in result.get("errors") or [] if isinstance(e, str) and e.strip()]


def _matches(lesson_key: str, error_keys: list[str]) -> bool:
    return any(lesson_key and (lesson_key in k or k in lesson_key) for k in error_keys if k)


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------

def _entry(lesson: dict, label: str) -> str:
    # Cleaned again here: whatever reaches a skill file must not be able to add
    # a heading or a comment to it, wherever the lesson came from.
    lesson = {k: _clean(str(lesson.get(k, ""))) for k in ("error", "cause", "resolution")}
    general = generalise(lesson["error"])
    title = general[:90] + ("…" if len(general) > 90 else "")
    return (
        f"### {title}\n"
        f"<!-- learned-fix: {key(lesson['error'])} -->\n"
        f"- **Error:** `{general.replace('`', chr(39))}`\n"
        f"- **Cause:** {lesson['cause']}\n"
        f"- **Resolution:** {lesson['resolution']}\n"
        f"- _Verified {datetime.now():%Y-%m-%d}: the next validation of a {label} run no longer reported it._\n"
    )


def publish(path: pathlib.Path, lessons: list[dict], label: str, max_entries: int = MAX_ENTRIES) -> int:
    """Add verified lessons to `path` under `## Learned Fixes`. An error already
    recorded is replaced by the newer resolution. Returns entries written."""
    if not lessons or not path.exists():
        return 0
    with _locked(path):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return 0
        head, sep, rest = content.partition(HEADING)
        if sep:
            # The section runs to the next `## ` heading; anything after it is kept as is.
            m = re.search(r"^## ", rest, flags=re.MULTILINE)
            section, tail = (rest[:m.start()], rest[m.start():]) if m else (rest, "")
        else:
            head, section, tail = content.rstrip("\n") + "\n\n---\n\n", "", ""
        entries = [e for e in re.split(r"(?=^### )", section, flags=re.MULTILINE) if e.startswith("### ")]
        new_keys = {key(l["error"]) for l in lessons}
        entries = [e for e in entries
                   if not (m := re.search(r"<!-- learned-fix: (.*?) -->", e)) or m.group(1) not in new_keys]
        seen: set[str] = set()
        for lesson in lessons:
            k = key(lesson["error"])
            if k and k not in seen:
                seen.add(k)
                entries.append(_entry(lesson, label))
        entries = entries[-max_entries:]
        body = HEADING + "\n\n" + INTRO + "\n\n" + "\n".join(e.rstrip("\n") + "\n" for e in entries)
        try:
            path.write_text(head + body + ("\n" + tail if tail else ""), encoding="utf-8")
        except OSError:
            return 0
    return len(seen)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def make_lesson_capture_callback(fix_key: str, validation_key: str, pending_key: str):
    """after_agent_callback for a fixer: hold its lessons as pending, keeping
    only those about an error the validator really reported."""

    def _capture(callback_context: CallbackContext) -> Optional[genai_types.Content]:
        state = callback_context.state
        reported = [key(e) for e in _errors(_parse_json_safely(state.get(validation_key, "") or ""))]
        lessons = [l for l in parse_lessons(state.get(fix_key, "") or "") if _matches(key(l["error"]), reported)]
        state[pending_key] = json.dumps(lessons)
        return None

    return _capture


def make_lesson_verify_callback(validation_key: str, pending_key: str,
                                targets: Callable[[dict], list[pathlib.Path]], label: str):
    """after_agent_callback for a validator: publish the pending lessons this
    validation proves — the build passed, or their error is no longer reported."""

    def _verify(callback_context: CallbackContext) -> Optional[genai_types.Content]:
        state = callback_context.state
        try:
            pending = json.loads(state.get(pending_key) or "[]")
        except (TypeError, json.JSONDecodeError):
            pending = []
        if not pending:
            return None
        state[pending_key] = "[]"
        raw = state.get(validation_key, "") or ""
        if not raw:
            return None
        result = _parse_json_safely(raw)
        remaining = [key(e) for e in _errors(result)]
        verified = pending if result.get("passed") else [
            l for l in pending if not _matches(key(l["error"]), remaining)]
        if not verified or not _LEARNING_ENABLED:
            return None
        by_path: dict[pathlib.Path, list[dict]] = {}
        for lesson in verified:
            for path in targets(lesson):
                by_path.setdefault(path, []).append(lesson)
        for path, lessons in by_path.items():
            publish(path, lessons, label)
        return None

    return _verify


def skill_targets(skills_dir: pathlib.Path, *names: str) -> Callable[[dict], list[pathlib.Path]]:
    """Every lesson goes to the same skills (the modifier's first)."""
    paths = [skills_dir / n / "SKILL.md" for n in names]
    return lambda lesson: paths


_FRONTEND = re.compile(r"\bfrontend\b|\.(?:tsx?|jsx?|css|scss)\b|package\.json|\bnpm\b|\bvite\b|\btsc\b|TS\d{4}",
                       re.IGNORECASE)


def jsp_targets(skills_dir: pathlib.Path) -> Callable[[dict], list[pathlib.Path]]:
    """JSP -> React writes two trees with two generators: a lesson goes to the
    generator of the tree its error came from, and to the fix skill."""
    def route(lesson: dict) -> list[pathlib.Path]:
        text = lesson["error"]
        generator = "react-frontend-generate" if _FRONTEND.search(text) else "spring-boot-bff-generate"
        return [skills_dir / generator / "SKILL.md", skills_dir / "jsp-to-react-bff-fix" / "SKILL.md"]
    return route
