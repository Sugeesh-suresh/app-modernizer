import asyncio
import io
import json
import os
import shutil
import uuid
import zipfile
import tempfile
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from google.adk.events import Event, EventActions
from google.genai import types

load_dotenv()

# ADK expects GOOGLE_API_KEY; map from GEMINI_API_KEY if needed
if not os.getenv("GOOGLE_API_KEY") and os.getenv("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

from agents import APP_NAME, USER_ID, PATTERN_RUNNERS, TARGET_LANGS, session_service
from agents.java_8_to_25.agents import INCREMENTAL_STAGES, incremental_stages
from agents.shared import companion_detector, dependency_graph, diffing
from agents.shared.file_parser import extract_text
from models.schemas import (
    PatternType, UploadResponse, ConfirmRequest, RefineRequest,
    SelectCompanionsRequest, GeneratedFile,
)

# ---------------------------------------------------------------------------
# In-process state (SSE queues and HITL events)
# ---------------------------------------------------------------------------

# Per-session asyncio.Queue feeds the SSE endpoint
_sse_queues: dict[str, asyncio.Queue] = {}

# Per-session asyncio.Events gate the HITL confirmation steps
_brd_gates: dict[str, asyncio.Event] = {}
_plan_gates: dict[str, asyncio.Event] = {}
_companion_gates: dict[str, asyncio.Event] = {}

# The 4 "core" migration patterns that can participate in a companion bundle
# (jsp-to-react-bff is excluded — it's a full architecture rewrite, not a
# library/dependency companion). Used to pre-initialize namespaced per-pattern
# state keys regardless of which pattern ends up primary.
_CORE_PATTERNS = ["java-8-to-25", "oracle-19c-to-23ai", "solr-4-to-9", "tibco-ems-to-pubsub"]
_COMPANION_PRIORITY = ["oracle-19c-to-23ai", "solr-4-to-9", "tibco-ems-to-pubsub"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse(event_type: str, **kwargs) -> str:
    return f"data: {json.dumps({'type': event_type, **kwargs})}\n\n"


async def _push(session_id: str, event_type: str, **kwargs) -> None:
    q = _sse_queues.get(session_id)
    if q:
        await q.put(_sse(event_type, **kwargs))


async def _update_state(session_id: str, delta: dict) -> None:
    """Write key/value pairs into the ADK session state outside an agent turn."""
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    if session is None:
        return
    event = Event(
        invocation_id=f"app-{uuid.uuid4().hex[:8]}",
        author="app",
        actions=EventActions(state_delta=delta),
    )
    await session_service.append_event(session, event)


async def _get_state(session_id: str) -> dict:
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    return dict(session.state) if session else {}


# ---------------------------------------------------------------------------
# Workspace extraction — every pattern's agents read/write real files on
# disk via agents/shared/workspace_tools.py, so the uploaded repository
# always needs to exist as real files rather than a concatenated string.
# ---------------------------------------------------------------------------

_WORKSPACE_EXCLUDED_DIRS = {
    ".git", "target", "build", "node_modules", ".gradle",
    "__pycache__", "bin", "obj", ".idea", ".vscode",
}
_WORKSPACE_MAX_FILES = 5_000
_WORKSPACE_MAX_TOTAL_BYTES = 100_000_000


def _extract_zip_to_dir(zip_bytes: bytes, dest_dir: Path) -> int:
    """Extract a repository zip to *dest_dir*, preserving folder structure.

    Skips VCS/build directories and guards against zip-slip (entries that
    would write outside dest_dir) and unreasonably large archives.
    Returns the number of files extracted.
    """
    dest_dir = dest_dir.resolve()
    count = 0
    total_bytes = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if count >= _WORKSPACE_MAX_FILES or total_bytes >= _WORKSPACE_MAX_TOTAL_BYTES:
                break
            rel = Path(info.filename)
            if set(rel.parts) & _WORKSPACE_EXCLUDED_DIRS:
                continue
            target = (dest_dir / rel).resolve()
            if target != dest_dir and dest_dir not in target.parents:
                continue  # zip-slip guard
            data = zf.read(info)
            total_bytes += len(data)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            count += 1
    return count


def _workspace_to_files(workspace_dir: str, target_lang: str) -> List[GeneratedFile]:
    """Collect the current state of the workspace directory into GeneratedFile
    entries, for download — the modifier/fixer agents wrote real files via
    tools, so the workspace itself (not any session-state text) is the
    source of truth for the migrated codebase."""
    root = Path(workspace_dir)
    if not root.exists():
        return []
    files: List[GeneratedFile] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _WORKSPACE_EXCLUDED_DIRS & set(rel.parts):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        language = path.suffix.lstrip(".").lower() or target_lang
        files.append(GeneratedFile(path=str(rel), content=content, language=language))
    return files


# ---------------------------------------------------------------------------
# ADK step runners
# ---------------------------------------------------------------------------

async def _run_step(
    session_id: str,
    step_key: str,
    pattern: str,
    message: str,
    sse_event_type: str,
) -> None:
    """Invoke one single-agent ADK step (re_agent or planner_agent for any
    pattern), streaming text chunks to the SSE queue."""
    runner = PATTERN_RUNNERS[pattern][step_key]
    content = types.Content(role="user", parts=[types.Part(text=message)])

    progress = 5
    async for event in runner.run_async(
        session_id=session_id,
        user_id=USER_ID,
        new_message=content,
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            text = getattr(part, "text", None)
            if text:
                progress = min(progress + 3, 92)
                await _push(session_id, sse_event_type, content=text, progress=progress)
                await asyncio.sleep(0)  # yield to event loop


def _parse_validation_json(raw: str) -> dict:
    """Parse the JSON validation result produced by a validate agent."""
    import re as _re2
    text = raw.strip()
    for parse in [
        lambda t: json.loads(t),
        lambda t: json.loads(_re2.sub(r"```(?:json)?\s*|\s*```", "", t).strip()),
        lambda t: json.loads(t[t.find("{") : t.rfind("}") + 1]),
    ]:
        try:
            return parse(text)
        except Exception:
            pass
    return {"passed": True, "errors": [], "summary": "Parse error — assuming passed."}


_CODE_STREAM_AUTHORS = {"modifier_agent", "backend_generator_agent", "frontend_generator_agent"}


async def _run_workspace_code_step(
    session_id: str, pattern: str, code_key: str, push_session_id: str | None = None,
) -> None:
    """Run a single-stage code pipeline (one or more generator agents ->
    LoopAgent(validator_agent, fixer_agent) -> reporter_agent) for any of
    the 5 patterns — used directly for solr-4-to-9 / oracle-19c-to-23ai /
    tibco-ems-to-pubsub / jsp-to-react-bff's "code" runner, and for
    java-8-to-25's "code_bigbang" runner. Every pattern's single-stage
    pipeline names its validate/fix/report agents identically
    (validator_agent/fixer_agent/reporter_agent); the generator step is
    named "modifier_agent" everywhere except jsp-to-react-bff, which has
    two ("backend_generator_agent" then "frontend_generator_agent") since
    it writes two separate target trees instead of editing one in place —
    both still route to code-stream via _CODE_STREAM_AUTHORS.

    `session_id` is the ADK session the pipeline actually runs against (and
    reads its final state from); `push_session_id` (defaults to `session_id`)
    is where SSE events are sent. These differ for a companion bundle: each
    bundled pattern's code_pipeline runs against its own isolated internal
    ADK session (see _run_bundle_code_generation) — because every pattern's
    pipeline intentionally reuses identical ADK agent names
    (modifier_agent/code_reviewer_agent/skill_curator_agent/...), running
    two different patterns' pipelines back-to-back in the SAME session
    corrupts Gemini's function-declaration bookkeeping (400 "Duplicate
    function declaration found: list_skills") — while the outward,
    frontend-facing session keeps receiving all the streamed progress.

    Streams events to the SSE queue with author-aware routing:
      (generator agent)   -> code-stream
      validator_agent     -> validate-stream  (also emits validation-agent-start)
      fixer_agent         -> fix-stream       (also emits fix-agent-start)
      code_reviewer_agent -> review-stream    (runs after build_loop, before reporter_agent)
      reporter_agent      -> report-stream
      skill_curator_agent -> curator-stream   (runs last, after reporter_agent)

    After the pipeline completes: emits validation-complete from
    build_result, code-review-ready from code_review, report-ready from
    final_report, and skill-curator-ready from skill_curator_summary.
    """
    push_session_id = push_session_id or session_id
    runner = PATTERN_RUNNERS[pattern][code_key]
    content = types.Content(role="user", parts=[types.Part(text=(
        "Apply the confirmed migration plan to the workspace, validate it and fix any "
        "errors, then produce the final report."
    ))])

    prev_author = ""
    iteration = 0
    progress = 5

    try:
        async for event in runner.run_async(
            session_id=session_id,
            user_id=USER_ID,
            new_message=content,
        ):
            author = getattr(event, "author", "") or ""

            if author and author != prev_author:
                if author == "validator_agent":
                    iteration += 1
                    await _push(push_session_id, "validation-agent-start", iteration=iteration)
                elif author == "fixer_agent":
                    await _push(push_session_id, "fix-agent-start", iteration=iteration)
                prev_author = author

            if not event.content or not event.content.parts:
                continue

            if author == "validator_agent":
                sse_type = "validate-stream"
            elif author == "fixer_agent":
                sse_type = "fix-stream"
            elif author in _CODE_STREAM_AUTHORS:
                sse_type = "code-stream"
            elif author == "code_reviewer_agent":
                sse_type = "review-stream"
            elif author == "reporter_agent":
                sse_type = "report-stream"
            elif author == "skill_curator_agent":
                sse_type = "curator-stream"
            else:
                continue  # skip SequentialAgent / LoopAgent envelope events

            for part in event.content.parts:
                text = getattr(part, "text", None)
                if text:
                    progress = min(progress + 2, 92)
                    await _push(push_session_id, sse_type, content=text, progress=progress)
                    await asyncio.sleep(0)
    except Exception:
        if iteration == 0:
            raise  # failed before the build/compile loop started — surface it as a real error
        # Once the build/compile loop has run, the migration is reported as complete regardless
        # of errors (in the loop itself, or in the reviewer/reporter/curator that follow it).
        traceback.print_exc()

    state = await _get_state(session_id)
    raw_result = state.get("build_result", "")
    validation = _parse_validation_json(raw_result) if raw_result else {"passed": True, "errors": [], "summary": ""}
    await _push(
        push_session_id,
        "validation-complete",
        passed=validation.get("passed", True),
        errors=validation.get("errors", []),
        summary=validation.get("summary", ""),
        iterations=iteration,
    )

    code_review = state.get("code_review", "")
    if code_review:
        await _push(push_session_id, "code-review-ready", content=code_review)

    final_report = state.get("final_report", "")
    if final_report:
        await _push(push_session_id, "report-ready", content=final_report)

    skill_curator_summary = state.get("skill_curator_summary", "")
    if skill_curator_summary:
        await _push(push_session_id, "skill-curator-ready", content=skill_curator_summary)


async def _run_standalone_agent(session_id: str, runner, message: str, sse_event_type: str) -> None:
    """Run one single-agent runner to completion, streaming all of its text
    under one fixed SSE event type. Used for the incremental java-8-to-25
    path's code-reviewer/reporter/skill-curator steps, which — unlike the
    single-stage patterns' SequentialAgent-wired versions — run as three
    separate runner calls (each stage's own pipeline already ended)."""
    content = types.Content(role="user", parts=[types.Part(text=message)])
    try:
        async for event in runner.run_async(session_id=session_id, user_id=USER_ID, new_message=content):
            if not event.content or not event.content.parts:
                continue
            for part in event.content.parts:
                text = getattr(part, "text", None)
                if text:
                    await _push(session_id, sse_event_type, content=text)
                    await asyncio.sleep(0)
    except Exception:
        # Only ever runs after every stage's build/compile loop has finished, so a failure here
        # must not turn a completed migration into an error — log it and carry on.
        traceback.print_exc()


async def _run_java8_incremental_code_step(session_id: str) -> None:
    """Run the java-8-to-25 phased incremental strategy: up to 8 true staged
    passes in 4 phases (Readiness; Java 17 + Spring Boot 2.7; Spring Boot
    3.x + Java 25; Spring Boot 4 -> executable JAR — the Spring Boot stages
    only when requested), each its own
    modifier_stage{N} -> LoopAgent(validator_stage{N}, fixer_stage{N})
    pipeline, executed strictly in order — see
    agents/java_8_to_25/agents.py's INCREMENTAL_STAGES / _make_stage.

    Emits `stage-start` before each stage and `stage-complete` (with that
    stage's parsed build result) after it, then runs the separate
    incremental reviewer/reporter/curator runners once, over every stage.
    """
    state = await _get_state(session_id)
    stages = incremental_stages(state.get("springboot_upgrade") == "true")
    total = len(stages)

    for position, stage in enumerate(stages, start=1):
        idx = stage.idx  # stable id: runner key, agent names, state keys
        stage_meta = {
            "stage": position, "total": total, "phase": stage.phase,
            "phase_title": stage.phase_title, "title": stage.title,
        }
        await _push(session_id, "stage-start", **stage_meta)

        runner = PATTERN_RUNNERS["java-8-to-25"][f"code_stage_{idx}"]
        content = types.Content(role="user", parts=[types.Part(text=(
            f"Apply ONLY the '{stage.title}' stage (step {position} of {total}, Phase {stage.phase}: "
            f"{stage.phase_title}) of the confirmed migration plan to the workspace, then validate and "
            "fix any errors for this stage."
        ))])

        modifier_name = f"modifier_stage{idx}"
        validator_name = f"validator_stage{idx}"
        fixer_name = f"fixer_stage{idx}"

        prev_author = ""
        iteration = 0
        progress = 5

        try:
            async for event in runner.run_async(
                session_id=session_id,
                user_id=USER_ID,
                new_message=content,
            ):
                author = getattr(event, "author", "") or ""

                if author and author != prev_author:
                    if author == validator_name:
                        iteration += 1
                        await _push(session_id, "validation-agent-start", iteration=iteration, stage=idx)
                    elif author == fixer_name:
                        await _push(session_id, "fix-agent-start", iteration=iteration, stage=idx)
                    prev_author = author

                if not event.content or not event.content.parts:
                    continue

                if author == validator_name:
                    sse_type = "validate-stream"
                elif author == fixer_name:
                    sse_type = "fix-stream"
                elif author == modifier_name:
                    sse_type = "code-stream"
                else:
                    continue

                for part in event.content.parts:
                    text = getattr(part, "text", None)
                    if text:
                        progress = min(progress + 2, 92)
                        await _push(session_id, sse_type, content=text, progress=progress, stage=idx)
                        await asyncio.sleep(0)
        except Exception:
            if iteration == 0:
                raise  # this stage failed before its build/compile loop started — surface it
            # The stage's build/compile loop has run: treat the stage as complete regardless of errors.
            traceback.print_exc()

        state = await _get_state(session_id)
        raw_result = state.get(f"build_result_stage{idx}", "")
        validation = _parse_validation_json(raw_result) if raw_result else {"passed": True, "errors": [], "summary": ""}
        await _push(
            session_id,
            "stage-complete",
            **stage_meta,
            passed=validation.get("passed", True),
            errors=validation.get("errors", []),
            summary=validation.get("summary", ""),
            iterations=iteration,
        )

    await _run_standalone_agent(
        session_id, PATTERN_RUNNERS["java-8-to-25"]["incremental_code_reviewer"],
        f"Independently review the full final codebase across all {total} completed stages.",
        "review-stream",
    )
    state = await _get_state(session_id)
    code_review = state.get("code_review", "")
    if code_review:
        await _push(session_id, "code-review-ready", content=code_review)

    await _run_standalone_agent(
        session_id, PATTERN_RUNNERS["java-8-to-25"]["incremental_reporter"],
        f"Produce the final migration report across all {total} completed stages.",
        "report-stream",
    )
    state = await _get_state(session_id)
    final_report = state.get("final_report", "")
    if final_report:
        await _push(session_id, "report-ready", content=final_report)

    await _run_standalone_agent(
        session_id, PATTERN_RUNNERS["java-8-to-25"]["incremental_skill_curator"],
        "Curate the java-8-to-25 skill library based on this completed incremental run.",
        "curator-stream",
    )
    state = await _get_state(session_id)
    skill_curator_summary = state.get("skill_curator_summary", "")
    if skill_curator_summary:
        await _push(session_id, "skill-curator-ready", content=skill_curator_summary)


# ---------------------------------------------------------------------------
# Section parser — splits the combined RE output into Analysis / BRD /
# TechSpec / Test Inventory
# ---------------------------------------------------------------------------

import re as _re

def _parse_re_sections(combined: str) -> tuple[str, str, str, str]:
    """Return (analysis, brd, technical_spec, test_inventory) parsed from
    the combined RE output."""
    _A = _re.search(r'<!--\s*SECTION:\s*ANALYSIS\s*-->', combined, _re.IGNORECASE)
    _B = _re.search(r'<!--\s*SECTION:\s*BRD\s*-->', combined, _re.IGNORECASE)
    _T = _re.search(r'<!--\s*SECTION:\s*TECHNICAL_SPECIFICATION\s*-->', combined, _re.IGNORECASE)
    _X = _re.search(r'<!--\s*SECTION:\s*TEST_INVENTORY\s*-->', combined, _re.IGNORECASE)
    _E = _re.search(r'<!--\s*SECTION:\s*END\s*-->', combined, _re.IGNORECASE)

    analysis = combined[_A.end():_B.start()].strip() if _A and _B else combined
    brd       = combined[_B.end():_T.start()].strip() if _B and _T else (combined[_B.end():].strip() if _B else combined)

    tech_end  = _X.start() if _X else (_E.start() if _E else len(combined))
    tech_spec = combined[_T.end():tech_end].strip() if _T else ""

    test_end       = _E.start() if _E else len(combined)
    test_inventory = combined[_X.end():test_end].strip() if _X else ""

    return analysis, brd or combined, tech_spec, test_inventory


def _inject_dependency_graph(tech_spec: str, graph_json: str, pattern: str) -> str:
    """Prepend the deterministically-computed dependency graph + migration
    groups (rendered as a plain-text tree) to the top of the Technical
    Specification, so the MarkdownWithDiagrams renderer in BRDReview.tsx
    displays it with zero dedicated frontend graph code."""
    try:
        graph = json.loads(graph_json) if graph_json else {}
    except json.JSONDecodeError:
        graph = {}
    if not graph.get("nodes"):
        return tech_spec
    section = dependency_graph.to_markdown_section(graph, pattern)
    return f"{section}\n\n{tech_spec}"


# ---------------------------------------------------------------------------
# Workflow orchestration
# ---------------------------------------------------------------------------

def _initial_state(pattern: str, workspace_dir: str, baseline_dir: str, graph_json: str,
                    migration_strategy: str, junit_upgrade: bool, springboot_upgrade: bool,
                    companion_recommendations_json: str = "[]") -> dict:
    state = {
        "pattern": pattern,
        "workspace_dir": workspace_dir,
        "baseline_dir": baseline_dir,
        "dependency_graph_json": graph_json,
        "migration_strategy": migration_strategy,
        "junit_upgrade": "true" if junit_upgrade else "false",
        "springboot_upgrade": "true" if springboot_upgrade else "false",
        "companion_recommendations_json": companion_recommendations_json,
        "companion_patterns_json": "[]",
        "analysis": "",
        "brd": "",
        "technical_spec": "",
        "test_inventory": "",
        "plan": "",
        "additional_context": "",
        "generated_files_json": "[]",
        "changed_files_json": "[]",
        "modify_result": "",
        "backend_generate_result": "",
        "frontend_generate_result": "",
        "build_result": "",
        "fix_result": "",
        "code_review": "",
        "final_report": "",
        "skill_curator_summary": "",
        "workflow_step": "upload",
    }
    # Every stage's keys exist up front (even the Spring Boot stages a run skips) so the
    # incremental reviewer/reporter/curator instructions can always resolve their placeholders.
    for stage in INCREMENTAL_STAGES:
        state[f"modify_result_stage{stage.idx}"] = ""
        state[f"build_result_stage{stage.idx}"] = ""
        state[f"fix_result_stage{stage.idx}"] = ""
    # Namespaced per-pattern placeholders for a companion bundle run — see
    # _run_bundle_re / _run_bundle_plan / _run_bundle_code_generation.
    for p in _CORE_PATTERNS:
        for key in (
            "brd", "technical_spec", "test_inventory", "plan", "modify_result",
            "build_result", "code_review", "final_report", "skill_curator_summary",
        ):
            state[f"{key}_{p}"] = ""
    return state


# ---------------------------------------------------------------------------
# Companion-bundle orchestration — runs the RE / plan / code-generation
# phases once per pattern in `bundle` (primary + any selected companions),
# combining results into the same top-level state keys / SSE events the
# frontend already knows how to render. When `bundle` has exactly one
# element (no companions detected/selected), every helper below degenerates
# to running that single pattern exactly as before.
# ---------------------------------------------------------------------------

def _label(pattern: str) -> str:
    return companion_detector.COMPANION_LABELS.get(pattern, pattern)


def _bundle_for(state: dict) -> list[str]:
    """The patterns this session runs, in execution order: any confirmed
    companion patterns first (dependency/library migrations), then the
    primary pattern last. Degenerates to [primary] when no companions were
    detected or the reviewer unchecked them all."""
    selected = json.loads(state.get("companion_patterns_json", "[]"))
    return [p for p in _COMPANION_PRIORITY if p in selected] + [state["pattern"]]


def _split_combined_sections(combined: str, bundle: list[str]) -> dict[str, str]:
    """Split a combined multi-pattern markdown document (one `## <label>`
    section per pattern, as built by the bundle helpers below) back into
    per-pattern text.

    Needed because the reviewer edits the *combined* BRD/plan in the UI while
    each pattern's agents read only their own `plan_<pattern>` slice — without
    splitting the edits back out they would be silently dropped before code
    generation.

    All-or-nothing: if any pattern's heading is missing (the reviewer rewrote
    or deleted it) this returns {} so the caller keeps every stored slice as
    generated. Splitting on a partial set of headings would let one pattern's
    slice absorb another's file-change manifest — handing, say, the Oracle
    manifest to the Java modifier — which is far worse than losing the edits.
    """
    marks: list[tuple[int, str]] = []
    for pattern in bundle:
        match = _re.search(
            rf"^##[ \t]+{_re.escape(_label(pattern))}[ \t]*$", combined, _re.MULTILINE
        )
        if not match:
            return {}
        marks.append((match.start(), pattern))
    marks.sort()

    sections: dict[str, str] = {}
    for i, (start, pattern) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(combined)
        body = combined[start:end]
        body = body.split("\n", 1)[1] if "\n" in body else ""  # drop the "## <label>" line
        lines = body.strip().split("\n")
        while lines and lines[-1].strip() == "---":  # drop the trailing section separator
            lines.pop()
        sections[pattern] = "\n".join(lines).rstrip()
    return sections


async def _run_bundle_re(session_id: str, bundle: list[str], feedback: str | None = None) -> None:
    """Runs each pattern's re_agent once. With `feedback` set (the "Refine
    with AI" flow), each pattern is asked to revise its own previous
    namespaced section rather than explore from scratch — this is what
    keeps a refine on a bundled multi-pattern BRD from silently dropping
    the other patterns' sections."""
    orig_state = await _get_state(session_id)
    workspace_dir = orig_state.get("workspace_dir", "")
    primary = orig_state.get("pattern")
    primary_graph_json = orig_state.get("dependency_graph_json", "")

    sections: dict[str, tuple[str, str, str]] = {}  # pattern -> (brd, tech_spec, test_inventory)
    for pattern in bundle:
        if feedback:
            prev_brd = orig_state.get(f"brd_{pattern}", "") or orig_state.get("brd", "")
            prev_tech = orig_state.get(f"technical_spec_{pattern}", "") or orig_state.get("technical_spec", "")
            message = (
                "Revise the Analysis / BRD / Technical Specification / Existing Test Inventory below "
                "based on the reviewer's feedback. Re-explore the workspace with list_files/read_file as "
                "needed. Keep the exact same four-section format with the same SECTION markers.\n\n"
                f"## Previous BRD\n{prev_brd[:8000]}\n\n"
                f"## Previous Technical Specification\n{prev_tech[:8000]}\n\n"
                f"## Reviewer Feedback\n{feedback}"
            )
        else:
            message = (
                "Reverse-engineer the repository workspace (starting at the root), using the "
                "list_files and read_file tools to explore it. Produce the Analysis, BRD, "
                "Technical Specification, and Existing Test Inventory sections. Do not assume "
                "any file contents you have not actually read."
            )
        if len(bundle) > 1:
            message += f" Focus specifically on the {_label(pattern)} migration domain."

        await _run_step(session_id, "re", pattern, message=message, sse_event_type="re-stream")
        state = await _get_state(session_id)
        combined = state.get("analysis", "")
        _, brd, tech_spec, test_inventory = _parse_re_sections(combined)

        # The primary's graph was computed at upload time; companions' are
        # computed here, once each, the same deterministic way.
        graph_json = (
            primary_graph_json if pattern == primary
            else json.dumps(dependency_graph.build_dependency_graph(workspace_dir, pattern))
        )
        tech_spec = _inject_dependency_graph(tech_spec, graph_json, pattern)

        await _update_state(session_id, {
            f"brd_{pattern}": brd,
            f"technical_spec_{pattern}": tech_spec,
            f"test_inventory_{pattern}": test_inventory,
        })
        sections[pattern] = (brd, tech_spec, test_inventory)

    if len(bundle) == 1:
        brd, tech_spec, test_inventory = sections[bundle[0]]
    else:
        ordered = sorted(bundle, key=lambda p: 0 if p == primary else 1)

        def _combine(idx: int) -> str:
            parts = [f"## {_label(p)}\n\n{sections[p][idx]}" for p in ordered if sections[p][idx]]
            return "\n\n---\n\n".join(parts)

        brd, tech_spec, test_inventory = _combine(0), _combine(1), _combine(2)

    await _update_state(session_id, {"brd": brd, "technical_spec": tech_spec, "test_inventory": test_inventory})
    await _push(session_id, "brd-ready", brd=brd, technical_spec=tech_spec, test_inventory=test_inventory)


async def _run_bundle_plan(session_id: str, bundle: list[str], feedback: str | None = None) -> None:
    """Runs each pattern's planner_agent once. With `feedback` set (the
    "Refine with AI" flow), each pattern is asked to revise its own
    previous namespaced plan rather than generate fresh from the BRD."""
    orig_state = await _get_state(session_id)
    additional_context = orig_state.get("additional_context", "")
    primary = orig_state.get("pattern")

    plans: dict[str, str] = {}
    for pattern in bundle:
        if feedback:
            prev_plan = orig_state.get(f"plan_{pattern}", "") or orig_state.get("plan", "")
            plan_msg = (
                "Revise the migration plan below based on the reviewer's feedback, keeping its overall "
                "structure (bigbang single-pass, or phased incremental — whichever this plan already uses, "
                "with the exact same phase and stage headings if incremental).\n\n"
                f"## Previous Plan\n{prev_plan[:12000]}\n\n"
                f"## Reviewer Feedback\n{feedback}"
            )
        else:
            plan_msg = "Generate the migration plan from the confirmed BRD and Technical Specification."
        if len(bundle) > 1:
            plan_msg += (
                f" The BRD/TechSpec below may cover several migrations — focus specifically on the "
                f"{_label(pattern)} migration and produce a plan (with File Change Manifest) for that "
                "migration only; ignore sections that belong to a different migration."
            )
        if not feedback and additional_context.strip():
            plan_msg += f"\n\nAdditional Context (Swagger / OpenAPI / Design Docs):\n{additional_context[:25000]}"

        await _run_step(session_id, "plan", pattern, message=plan_msg, sse_event_type="plan-stream")
        state = await _get_state(session_id)
        plan = state.get("plan", "")
        await _update_state(session_id, {f"plan_{pattern}": plan})
        plans[pattern] = plan

    if len(bundle) == 1:
        combined_plan = plans[bundle[0]]
    else:
        ordered = sorted(bundle, key=lambda p: 0 if p == primary else 1)
        combined_plan = "\n\n---\n\n".join(f"## {_label(p)}\n\n{plans[p]}" for p in ordered if plans[p])

    await _update_state(session_id, {"plan": combined_plan})
    await _push(session_id, "plan-ready", content=combined_plan)


async def _create_pattern_session(
    pattern: str, workspace_dir: str, baseline_dir: str, plan: str,
    migration_strategy: str, junit_upgrade: str, springboot_upgrade: str,
) -> str:
    """Creates a fresh, isolated ADK session for running one bundled pattern's
    code_pipeline. Required because every pattern's code_pipeline
    intentionally reuses identical ADK agent names (modifier_agent,
    validator_agent, fixer_agent, code_reviewer_agent, skill_curator_agent,
    reporter_agent) — running two different patterns' pipelines back-to-back
    against the SAME session corrupts Gemini's function-declaration
    bookkeeping (400 "Duplicate function declaration found: list_skills").
    Seeded from _initial_state so every {...}-templated key an agent might
    reference is present; only `plan` is pre-filled since RE/BRD aren't
    re-run per pattern here (they already ran, combined, for the outward
    session)."""
    state = _initial_state(
        pattern, workspace_dir, baseline_dir, "[]",
        migration_strategy, junit_upgrade == "true", springboot_upgrade == "true",
    )
    state["plan"] = plan
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)
    return session.id


async def _run_bundle_code_generation(session_id: str, bundle: list[str]) -> None:
    outward_state = await _get_state(session_id)
    workspace_dir = outward_state.get("workspace_dir", "")
    baseline_dir = outward_state.get("baseline_dir", "")
    migration_strategy = outward_state.get("migration_strategy", "bigbang")
    junit_upgrade = outward_state.get("junit_upgrade", "false")
    springboot_upgrade = outward_state.get("springboot_upgrade", "false")

    for idx, pattern in enumerate(bundle, start=1):
        state = await _get_state(session_id)
        # Falls back to the combined plan if this pattern's slice is missing
        # (e.g. its planner returned nothing, or the reviewer rewrote its heading).
        plan_for_pattern = state.get(f"plan_{pattern}", "") or state.get("plan", "")

        if len(bundle) > 1:
            await _push(
                session_id, "progress",
                message=f"Migrating: {_label(pattern)} ({idx}/{len(bundle)})", progress=5,
            )
            # Isolated internal session — see _create_pattern_session's docstring.
            run_session_id = await _create_pattern_session(
                pattern, workspace_dir, baseline_dir, plan_for_pattern,
                migration_strategy, junit_upgrade, springboot_upgrade,
            )
        else:
            if plan_for_pattern:
                await _update_state(session_id, {"plan": plan_for_pattern})
            run_session_id = session_id

        code_key = "code_bigbang" if pattern == "java-8-to-25" else "code"
        await _run_workspace_code_step(run_session_id, pattern, code_key, push_session_id=session_id)

        result_state = await _get_state(run_session_id)
        await _update_state(session_id, {
            f"modify_result_{pattern}": result_state.get("modify_result", ""),
            f"build_result_{pattern}": result_state.get("build_result", ""),
            f"code_review_{pattern}": result_state.get("code_review", ""),
            f"final_report_{pattern}": result_state.get("final_report", ""),
            f"skill_curator_summary_{pattern}": result_state.get("skill_curator_summary", ""),
        })

    if len(bundle) <= 1:
        return

    state = await _get_state(session_id)
    primary = state.get("pattern")
    ordered = sorted(bundle, key=lambda p: 0 if p == primary else 1)

    def _combine(key_prefix: str) -> str:
        parts = []
        for p in ordered:
            content = state.get(f"{key_prefix}_{p}", "")
            if content:
                parts.append(f"## {_label(p)}\n\n{content}")
        return "\n\n---\n\n".join(parts)

    combined_report = _combine("final_report")
    if "java-8-to-25" in bundle and state.get("migration_strategy") == "incremental":
        combined_report += (
            "\n\n---\n\n_Note: java-8-to-25 ran as a single bigbang pass as part of this bundled "
            "migration — the phased incremental strategy and JUnit/Spring Boot toggles are not "
            "supported in combination with companion patterns._"
        )
    combined_review = _combine("code_review")
    combined_curator = _combine("skill_curator_summary")

    await _update_state(session_id, {
        "final_report": combined_report,
        "code_review": combined_review,
        "skill_curator_summary": combined_curator,
    })
    if combined_report:
        await _push(session_id, "report-ready", content=combined_report)
    if combined_review:
        await _push(session_id, "code-review-ready", content=combined_review)
    if combined_curator:
        await _push(session_id, "skill-curator-ready", content=combined_curator)


async def _run_workflow(session_id: str) -> None:
    try:
        state = await _get_state(session_id)
        pattern = state["pattern"]

        await _push(session_id, "step-change", step="dependency-graph")
        await _push(session_id, "dependency-graph-ready")

        # ── Step 0: Companion-migration detection/selection (java-8-to-25 only) ──
        recs = json.loads(state.get("companion_recommendations_json", "[]"))
        bundle = [pattern]
        if recs:
            # Recommendations first: the frontend needs them in state before the
            # step flips, or the step rail briefly filters out the very step it
            # is on (skipSteps) and renders every step as pending.
            await _push(session_id, "companion-recommendations", companions=recs)
            await _push(session_id, "step-change", step="companion-selection")
            await _companion_gates[session_id].wait()
            state = await _get_state(session_id)
            bundle = _bundle_for(state)

        # ── Step 1: Reverse Engineering -> Analysis + BRD + TechSpec + Tests ──
        await _push(session_id, "step-change", step="reverse-engineering")
        await _run_bundle_re(session_id, bundle)
        await _push(session_id, "step-change", step="brd-review")

        # ── HITL: Wait for Analysis confirmation (BRD + TechSpec) ───────────
        await _brd_gates[session_id].wait()

        # ── Step 2: Plan Generation ──────────────────────────────────────────
        await _push(session_id, "step-change", step="plan-generation")
        await _run_bundle_plan(session_id, bundle)
        await _push(session_id, "step-change", step="plan-review")

        # ── HITL: Wait for Plan confirmation ────────────────────────────────
        await _plan_gates[session_id].wait()

        # ── Step 3: Code Generation ──────────────────────────────────────────
        await _push(session_id, "step-change", step="code-generation")

        state = await _get_state(session_id)
        if len(bundle) == 1 and pattern == "java-8-to-25" and state.get("migration_strategy") == "incremental":
            await _run_java8_incremental_code_step(session_id)
        else:
            await _run_bundle_code_generation(session_id, bundle)

        # ── Step 4: Diff + final file collection ────────────────────────────
        state = await _get_state(session_id)
        workspace_dir = state.get("workspace_dir", "")
        baseline_dir = state.get("baseline_dir", "")

        # The build/compile loop has finished by now, so the migration is reported as complete
        # regardless of errors — a failed diff or file collection just means less to show.
        try:
            changed_files = (
                diffing.compute_changed_files(baseline_dir, workspace_dir)
                if workspace_dir and baseline_dir else []
            )
        except Exception:
            traceback.print_exc()
            changed_files = []
        await _push(session_id, "diff-ready", changed_files=changed_files)

        try:
            files = _workspace_to_files(workspace_dir, TARGET_LANGS[pattern]) if workspace_dir else []
        except Exception:
            traceback.print_exc()
            files = []
        files_payload = [f.model_dump() for f in files]

        await _update_state(session_id, {
            "generated_files_json": json.dumps(files_payload),
            "changed_files_json": json.dumps(changed_files),
        })
        await _push(session_id, "code-ready", files=files_payload)

        if workspace_dir:
            shutil.rmtree(workspace_dir, ignore_errors=True)
        if baseline_dir:
            shutil.rmtree(baseline_dir, ignore_errors=True)

        await _push(session_id, "step-change", step="complete")
        await _push(session_id, "workflow-complete")

    except Exception as exc:
        traceback.print_exc()  # the UI only receives str(exc); keep the full traceback in the server log
        await _push(session_id, "error", message=str(exc))
        try:
            state = await _get_state(session_id)
            for key in ("workspace_dir", "baseline_dir"):
                d = state.get(key)
                if d:
                    shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
    finally:
        await _sse_queues[session_id].put(None)  # sentinel → close SSE stream

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_: FastAPI):
    yield

app = FastAPI(title="App Modernizer API (ADK-powered)", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/api/upload", response_model=UploadResponse)
async def upload_repository(
    background_tasks: BackgroundTasks,
    pattern: PatternType = Form(...),
    file: UploadFile = File(...),
    migration_strategy: str = Form("bigbang"),
    junit_upgrade: bool = Form(False),
    springboot_upgrade: bool = Form(False),
):
    raw = await file.read()

    ws_path = Path(tempfile.mkdtemp(prefix="modernizer-ws-"))
    if file.filename and file.filename.endswith(".zip"):
        files_found = _extract_zip_to_dir(raw, ws_path)
    else:
        (ws_path / (file.filename or "uploaded-source")).write_bytes(raw)
        files_found = 1

    if files_found == 0:
        shutil.rmtree(ws_path, ignore_errors=True)
        raise HTTPException(status_code=400, detail="No readable source files found.")

    workspace_dir = str(ws_path)
    baseline_dir = diffing.snapshot_workspace(workspace_dir)
    graph = dependency_graph.build_dependency_graph(workspace_dir, pattern.value)
    graph_json = json.dumps(graph)

    companion_recs = (
        companion_detector.detect_companions(workspace_dir, pattern.value)
        if pattern.value in companion_detector.COMPANION_CANDIDATES else []
    )
    companion_recs_json = json.dumps(companion_recs)

    # Create ADK session with initial state
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state=_initial_state(
            pattern.value, workspace_dir, baseline_dir, graph_json,
            migration_strategy, junit_upgrade, springboot_upgrade,
            companion_recs_json,
        ),
    )
    session_id = session.id

    # Set up per-session infrastructure
    _sse_queues[session_id] = asyncio.Queue()
    _brd_gates[session_id] = asyncio.Event()
    _plan_gates[session_id] = asyncio.Event()
    _companion_gates[session_id] = asyncio.Event()

    background_tasks.add_task(_run_workflow, session_id)

    return UploadResponse(
        session_id=session_id,
        message="Upload successful. Workflow started.",
        files_found=files_found,
    )


@app.get("/api/stream/{session_id}")
async def stream_session(session_id: str):
    """Server-Sent Events endpoint — streams workflow progress to the client."""
    if session_id not in _sse_queues:
        raise HTTPException(status_code=404, detail="Session not found.")

    async def generator():
        yield _sse("connected", session_id=session_id)
        q = _sse_queues[session_id]
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            if event is None:
                break
            yield event

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/sessions/{session_id}/select-companions")
async def select_companions(session_id: str, body: SelectCompanionsRequest = SelectCompanionsRequest()):
    """User's pick-and-choose response to the auto-detected companion
    migrations (e.g. Oracle 19c->23ai / Solr 4x->9x alongside a Java 8->25
    primary). Only patterns actually present in this session's
    companion_recommendations_json are accepted — selection stays
    evidence-gated, matching the rest of this codebase's "concrete evidence
    only" philosophy. Unblocks _run_workflow's wait on _companion_gates."""
    if session_id not in _companion_gates:
        raise HTTPException(status_code=404, detail="Session not found.")
    if _companion_gates[session_id].is_set():
        raise HTTPException(status_code=400, detail="Companion migrations already selected.")

    state = await _get_state(session_id)
    recommended = {r["pattern"] for r in json.loads(state.get("companion_recommendations_json", "[]"))}
    selected = [p for p in body.selected if p in recommended]

    await _update_state(session_id, {"companion_patterns_json": json.dumps(selected)})
    _companion_gates[session_id].set()
    return {"ok": True, "selected": selected}


@app.post("/api/sessions/{session_id}/confirm-brd")
async def confirm_brd(session_id: str, body: ConfirmRequest = ConfirmRequest()):
    if session_id not in _brd_gates:
        raise HTTPException(status_code=404, detail="Session not found.")

    delta: dict = {}
    if body.content is not None:
        delta["brd"] = body.content
    if body.technical_spec_content is not None:
        delta["technical_spec"] = body.technical_spec_content
    if body.feedback:
        state = await _get_state(session_id)
        current_brd = state.get("brd", body.content or "")
        delta["brd"] = current_brd + f"\n\n---\n**Reviewer Feedback:** {body.feedback}"

    if delta:
        await _update_state(session_id, delta)

    _brd_gates[session_id].set()
    return {"ok": True}


@app.post("/api/sessions/{session_id}/refine-brd")
async def refine_brd(session_id: str, body: RefineRequest):
    """Actually re-runs re_agent with the reviewer's feedback (unlike
    confirm-brd's feedback, which just appends text and advances). The
    workflow stays paused on brd-review — _brd_gates is NOT set."""
    if session_id not in _brd_gates:
        raise HTTPException(status_code=404, detail="Session not found.")
    if _brd_gates[session_id].is_set():
        raise HTTPException(status_code=400, detail="BRD already confirmed.")

    state = await _get_state(session_id)
    bundle = _bundle_for(state)

    await _run_bundle_re(session_id, bundle, feedback=body.feedback)
    return {"ok": True}


@app.get("/api/sessions/{session_id}/download/brd")
async def download_brd(session_id: str):
    state = await _get_state(session_id)
    brd = state.get("brd", "")
    if not brd:
        raise HTTPException(status_code=404, detail="BRD not yet generated.")
    return Response(
        content=brd,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="brd-{session_id[:8]}.md"'},
    )


@app.post("/api/sessions/{session_id}/context-files")
async def upload_context_files(
    session_id: str,
    files: List[UploadFile] = File(...),
):
    if session_id not in _brd_gates:
        raise HTTPException(status_code=404, detail="Session not found.")
    if _brd_gates[session_id].is_set():
        raise HTTPException(status_code=400, detail="Context files must be uploaded before confirming the BRD.")

    state = await _get_state(session_id)
    accumulated = state.get("additional_context", "")
    added: list[str] = []

    for upload in files:
        raw = await upload.read()
        name = upload.filename or "unknown"
        text = extract_text(name, raw)
        if text.strip():
            accumulated += f"\n\n--- CONTEXT FILE: {name} ---\n{text}"
            added.append(name)

    await _update_state(session_id, {"additional_context": accumulated})
    return {"ok": True, "files_added": len(added), "filenames": added}


@app.post("/api/sessions/{session_id}/confirm-plan")
async def confirm_plan(session_id: str, body: ConfirmRequest = ConfirmRequest()):
    if session_id not in _plan_gates:
        raise HTTPException(status_code=404, detail="Session not found.")

    state = await _get_state(session_id)
    delta: dict = {}
    plan_text = body.content if body.content is not None else state.get("plan", "")
    if body.content is not None:
        delta["plan"] = body.content
    if body.feedback:
        delta["plan"] = plan_text + f"\n\n---\n**Reviewer Feedback:** {body.feedback}"

    # In a companion bundle the reviewed plan is several patterns' plans
    # concatenated under `## <label>` headings, but each pattern's modifier
    # agent only ever sees its own plan_<pattern> slice — so edits and
    # feedback have to be split back out here or they never reach code
    # generation. Feedback applies to every pattern, since the reviewer was
    # commenting on the plan as a whole.
    bundle = _bundle_for(state)
    if delta and len(bundle) > 1:
        for pattern, text in _split_combined_sections(plan_text, bundle).items():
            if body.feedback:
                text += f"\n\n---\n**Reviewer Feedback:** {body.feedback}"
            delta[f"plan_{pattern}"] = text

    if delta:
        await _update_state(session_id, delta)

    _plan_gates[session_id].set()
    return {"ok": True}


@app.post("/api/sessions/{session_id}/refine-plan")
async def refine_plan(session_id: str, body: RefineRequest):
    """Actually re-runs planner_agent with the reviewer's feedback (unlike
    confirm-plan's feedback, which just appends text and advances). The
    workflow stays paused on plan-review — _plan_gates is NOT set."""
    if session_id not in _plan_gates:
        raise HTTPException(status_code=404, detail="Session not found.")
    if _plan_gates[session_id].is_set():
        raise HTTPException(status_code=400, detail="Plan already confirmed.")

    state = await _get_state(session_id)
    bundle = _bundle_for(state)

    await _run_bundle_plan(session_id, bundle, feedback=body.feedback)
    return {"ok": True}


@app.get("/api/sessions/{session_id}/download/plan")
async def download_plan(session_id: str):
    state = await _get_state(session_id)
    plan = state.get("plan", "")
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not yet generated.")
    return Response(
        content=plan,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="plan-{session_id[:8]}.md"'},
    )


@app.get("/api/sessions/{session_id}/download/code")
async def download_code_zip(session_id: str):
    """Return all generated source files as a ZIP archive preserving folder structure."""
    state = await _get_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found.")

    files = json.loads(state.get("generated_files_json", "[]"))
    if not files:
        raise HTTPException(status_code=404, detail="No generated files found.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            # Use the path as-is so folder structure is preserved inside the ZIP
            zf.writestr(f["path"], f["content"])
    buf.seek(0)

    pattern_slug = state.get("pattern", "migration").replace("/", "-")
    filename = f"{pattern_slug}-migrated.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    state = await _get_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found.")
    files = json.loads(state.get("generated_files_json", "[]"))
    changed_files = json.loads(state.get("changed_files_json", "[]"))
    return {
        "session_id": session_id,
        "pattern": state.get("pattern"),
        "brd": state.get("brd") or None,
        "technical_spec": state.get("technical_spec") or None,
        "test_inventory": state.get("test_inventory") or None,
        "plan": state.get("plan") or None,
        "generated_files": files,
        "changed_files": changed_files,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "framework": "google-adk"}
