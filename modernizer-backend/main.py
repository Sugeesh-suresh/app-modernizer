import asyncio
import io
import json
import os
import shutil
import uuid
import zipfile
import tempfile
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, NamedTuple

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from google.adk.events import Event, EventActions
from google.genai import types

load_dotenv()

# Gemini API key or Vertex AI — decided from .env before any agent or model
# client exists, since the SDK reads the environment itself (see llm_auth.py).
import llm_auth  # noqa: E402

LLM_AUTH = llm_auth.apply()
print(f"[startup] {LLM_AUTH.summary()}", flush=True)
for _warning in LLM_AUTH.warnings:
    print(f"[startup] WARNING: {_warning}", flush=True)
if LLM_AUTH.error:
    print(f"[startup] ERROR: {LLM_AUTH.error} Uploads are refused until this is fixed.", flush=True)

# The SDK logs each retry (429 quota, 5xx) at INFO, which uvicorn's logging
# setup never shows, so a run waiting out a quota looked hung. Surface them.
import logging  # noqa: E402

_retry_log = logging.getLogger("google_genai._api_client")
_retry_log.setLevel(logging.INFO)
if not _retry_log.handlers:
    _retry_handler = logging.StreamHandler()
    _retry_handler.setFormatter(logging.Formatter("[llm] %(message)s"))
    _retry_log.addHandler(_retry_handler)

from agents import APP_NAME, USER_ID, PATTERN_RUNNERS, TARGET_LANGS, config, session_service
from agents.java_8_to_25.agents import INCREMENTAL_STAGES, incremental_stages
from agents.java_8_to_11 import inventory as java11_inventory
from agents.java_8_to_11.agents import STAGE_TITLE as JAVA11_STAGE_TITLE
from agents.shared import (
    companion_detector, dependency_graph, diffing, plan_tasks, re_units, scope_fence, stack_detector, ux_designs,
)
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

# The reverse-engineering-only pattern: maps whichever stacks are in the uploaded
# repo, runs each one's RE stage, and stops at the combined document. It has no
# planner and no code pipeline, so every plan/code branch below must exclude it.
_STACK_DISCOVERY = "stack-discovery"

# A JDK-only upgrade: one strategy, no Spring Boot or JUnit toggles, and a scope
# fence that freezes the JSP tier and the WildFly deployment.
_JAVA_8_TO_11 = "java-8-to-11"

# Every pattern whose `re` runner a stack-discovery fan-out can invoke — used to
# pre-initialize the namespaced per-stack state keys. Wider than _CORE_PATTERNS
# because discovery can reverse-engineer the JSP tier and WildFly too, neither of
# which can be a companion of a chosen primary.
_STACK_PATTERNS = stack_detector.STACK_ORDER

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


class ExtractionResult(NamedTuple):
    """What one upload actually unpacked, and what it could not.

    `truncated` files are the heart of this: the previous version hit its cap and
    `break`-ed out of the loop returning only a count, so a repository too large
    for the workspace produced a partial tree that looked like a successful
    upload. Every later stage -- the RE inventory, the plan's file manifest, the
    change audit's "is every untouched file genuinely irrelevant" check -- reasons
    about *the whole repository*, so a quietly partial workspace does not degrade
    those answers, it invalidates them while they still read as confident.
    """
    files: int
    total_bytes: int
    #: Files present in the archive that were not written because a cap was hit.
    truncated: int
    #: Archive entries rejected as zip-slip. Not a size problem; worth surfacing.
    unsafe: int

    @property
    def complete(self) -> bool:
        return self.truncated == 0

    def warning(self) -> str:
        """Reviewer-facing warning, or "" when the upload was complete."""
        notes: list[str] = []
        if self.truncated:
            notes.append(
                f"**{self.truncated:,} of {self.files + self.truncated:,} files were not unpacked** "
                f"because this server's ingestion limit was reached "
                f"({config.WORKSPACE_MAX_FILES:,} files / "
                f"{config.WORKSPACE_MAX_TOTAL_BYTES // 1_000_000:,} MB). Everything below was "
                "produced from a PARTIAL copy of the repository: any inventory, file manifest or "
                "coverage claim covers only the files that were unpacked, and cannot be read as a "
                "statement about the rest. Raise `WORKSPACE_MAX_FILES` / "
                "`WORKSPACE_MAX_TOTAL_BYTES` and re-run before relying on this."
            )
        if self.unsafe:
            notes.append(
                f"{self.unsafe:,} archive entries were rejected because they pointed outside the "
                "workspace directory."
            )
        return " ".join(notes)


def _extract_zip_to_dir(zip_bytes: bytes, dest_dir: Path) -> ExtractionResult:
    """Extract a repository zip to *dest_dir*, preserving folder structure.

    Skips VCS/build directories and guards against zip-slip (entries that would
    write outside dest_dir). Keeps counting past its caps rather than breaking
    out, so the caller can say how much was left behind instead of reporting a
    truncated tree as a whole repository.
    """
    dest_dir = dest_dir.resolve()
    count = 0
    total_bytes = 0
    truncated = 0
    unsafe = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = Path(info.filename)
            if set(rel.parts) & _WORKSPACE_EXCLUDED_DIRS:
                continue
            target = (dest_dir / rel).resolve()
            if target != dest_dir and dest_dir not in target.parents:
                unsafe += 1
                continue

            # Counted, not silently skipped. file_size is the archive's own
            # declared uncompressed size, so the remainder can be tallied
            # without inflating any of it.
            if count >= config.WORKSPACE_MAX_FILES or total_bytes >= config.WORKSPACE_MAX_TOTAL_BYTES:
                truncated += 1
                continue

            data = zf.read(info)
            total_bytes += len(data)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            count += 1

    return ExtractionResult(files=count, total_bytes=total_bytes, truncated=truncated, unsafe=unsafe)


def _archive_workspace(workspace_dir: str) -> str | None:
    """ZIP the finished workspace to a temp file and return its path.

    Written to disk before the workspace is deleted, so the download no longer
    depends on session state holding every file's content. On a large repository
    that state value was hundreds of MB of JSON — held in memory per session, and
    a single enormous row with DATABASE_URL set. The ZIP is always complete; only
    the browsable preview below is capped.
    """
    root = Path(workspace_dir)
    if not root.exists():
        return None
    fd, archive_path = tempfile.mkstemp(prefix="modernizer-result-", suffix=".zip")
    os.close(fd)
    wrote = 0
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if _WORKSPACE_EXCLUDED_DIRS & set(rel.parts):
                continue
            zf.write(path, rel.as_posix())
            wrote += 1
    if wrote == 0:
        Path(archive_path).unlink(missing_ok=True)
        return None
    return archive_path


def _workspace_to_files(workspace_dir: str, target_lang: str) -> tuple[List[GeneratedFile], int]:
    """The browsable slice of the finished workspace, plus how many files exist.

    Capped: this payload goes into session state and over SSE to populate the
    file browser, and a monorepo would otherwise put its entire source there.
    The complete result is in the ZIP from `_archive_workspace`, so nothing is
    lost — but the caller must say so, hence the total alongside the list.
    """
    root = Path(workspace_dir)
    if not root.exists():
        return [], 0

    files: List[GeneratedFile] = []
    total = 0
    used_bytes = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _WORKSPACE_EXCLUDED_DIRS & set(rel.parts):
            continue
        total += 1
        if len(files) >= config.RESULT_PREVIEW_MAX_FILES or used_bytes >= config.RESULT_PREVIEW_MAX_TOTAL_BYTES:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        used_bytes += len(content)
        language = path.suffix.lstrip(".").lower() or target_lang
        files.append(GeneratedFile(path=rel.as_posix(), content=content, language=language))
    return files, total


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


async def _run_java8_incremental_code_step(
    session_id: str, push_session_id: str | None = None,
) -> None:
    """Run the java-8-to-25 phased incremental strategy: up to 8 true staged
    passes in 4 phases (Readiness; Java 17 + Spring Boot 2.7; Spring Boot
    3.x + Java 25; Spring Boot 4 -> executable JAR — the Spring Boot stages
    only when requested), each its own
    modifier_stage{N} -> LoopAgent(validator_stage{N}, fixer_stage{N})
    pipeline, executed strictly in order — see
    agents/java_8_to_25/agents.py's INCREMENTAL_STAGES / _make_stage.

    Each stage's modifier runs once per plan task (`### Task <id>: ...` blocks
    parsed by agents/shared/plan_tasks.py), so its context holds only that
    task's files instead of the whole stage's — on a large repository a single
    pass would otherwise accumulate every file it reads and writes. The
    stage's build loop then runs once, over the finished stage.

    Emits `stage-start`/`stage-complete` per stage, `task-start`/`task-complete`
    per task, then runs the separate incremental reviewer/reporter/curator
    runners once, over every stage.
    """
    # Agents read/write `session_id`; SSE events go to the outward session, which is
    # a different one in a companion-bundle run (see _create_pattern_session).
    push_session_id = push_session_id or session_id
    state = await _get_state(session_id)
    stages = incremental_stages(state.get("springboot_upgrade") == "true")
    plan_text = state.get("plan", "")
    total = len(stages)

    for position, stage in enumerate(stages, start=1):
        idx = stage.idx  # stable id: runner key, agent names, state keys
        stage_meta = {
            "stage": position, "total": total, "phase": stage.phase,
            "phase_title": stage.phase_title, "title": stage.title,
        }
        await _push(push_session_id, "stage-start", **stage_meta)

        # One unit per task block; one whole-section unit when a hand-edited plan has
        # none; and NO units when the plan has no section for this stage at all.
        units, from_plan = plan_tasks.stage_units(plan_text, stage.title)
        if not units:
            # Never guess a missing stage's contents: the old fallback handed this
            # modifier the entire plan to apply under this stage's guardrail.
            note = (
                f"SKIPPED — the confirmed plan has no `## Stage <n>: {stage.title}` section, so there "
                "is nothing approved for this stage to apply. Nothing was changed. If this stage was "
                "meant to run, add its section to the plan and re-run."
            )
            print(f"[incremental] stage {idx} ({stage.title}): no plan section — skipped", flush=True)
            await _update_state(session_id, {f"modify_result_stage{idx}": f"## Modify Result\n{note}"})
            await _push(push_session_id, "code-stream", content=f"\n\n**{stage.title}** — {note}\n",
                        progress=100, stage=position)
            await _push(push_session_id, "stage-complete", **stage_meta, skipped=True)
            continue
        preamble = (
            f"You are applying the '{stage.title}' stage (step {position} of {total}, Phase "
            f"{stage.phase}: {stage.phase_title}) of the confirmed migration plan."
        )

        modifier_runner = PATTERN_RUNNERS["java-8-to-25"][f"code_stage_{idx}_modify"]
        modifier_name = f"modifier_stage{idx}"
        progress = 5
        summaries: list[str] = []

        for task_index, task in enumerate(units, start=1):
            task_meta = {
                "task_id": task.id, "task_title": task.title,
                "task_index": task_index, "task_total": len(units),
            }
            if from_plan:
                await _push(push_session_id, "task-start", **stage_meta, **task_meta)

            # Rendered into the modifier's instruction as {current_task}; a separate runner call
            # per task means each one starts with a fresh model context.
            await _update_state(session_id, {"current_task": f"{preamble}\n\n{task.body}"})
            message = types.Content(role="user", parts=[types.Part(text=(
                f"Apply task {task.id} ({task.title}) of the '{stage.title}' stage to the workspace."
            ))])

            try:
                async for event in modifier_runner.run_async(
                    session_id=session_id,
                    user_id=USER_ID,
                    new_message=message,
                ):
                    if (getattr(event, "author", "") or "") != modifier_name:
                        continue
                    if not event.content or not event.content.parts:
                        continue
                    for part in event.content.parts:
                        text = getattr(part, "text", None)
                        if text:
                            progress = min(progress + 2, 80)
                            await _push(push_session_id, "code-stream", content=text, progress=progress, stage=position)
                            await asyncio.sleep(0)
            except Exception:
                # One failed task must not abandon the rest of the stage — the build loop still runs.
                traceback.print_exc()
                summaries.append(f"### Task {task.id}: {task.title}\nFAILED — see the server log.")
                continue

            task_state = await _get_state(session_id)
            summaries.append(
                f"### Task {task.id}: {task.title}\n"
                f"{(task_state.get(f'modify_result_stage{idx}') or '').strip()}"
            )
            if from_plan:
                await _push(push_session_id, "task-complete", **stage_meta, **task_meta)

        # The reviewer, reporter and curator read one modify result per stage, not one per task.
        await _update_state(session_id, {f"modify_result_stage{idx}": "\n\n".join(summaries).strip()})

        build_runner = PATTERN_RUNNERS["java-8-to-25"][f"code_stage_{idx}_build"]
        validator_name = f"validator_stage{idx}"
        fixer_name = f"fixer_stage{idx}"
        build_message = types.Content(role="user", parts=[types.Part(text=(
            f"Build the workspace after the '{stage.title}' stage and fix any errors it reports."
        ))])

        prev_author = ""
        iteration = 0

        try:
            async for event in build_runner.run_async(
                session_id=session_id,
                user_id=USER_ID,
                new_message=build_message,
            ):
                author = getattr(event, "author", "") or ""

                if author and author != prev_author:
                    if author == validator_name:
                        iteration += 1
                        await _push(push_session_id, "validation-agent-start", iteration=iteration, stage=position)
                    elif author == fixer_name:
                        await _push(push_session_id, "fix-agent-start", iteration=iteration, stage=position)
                    prev_author = author

                if not event.content or not event.content.parts:
                    continue

                if author == validator_name:
                    sse_type = "validate-stream"
                elif author == fixer_name:
                    sse_type = "fix-stream"
                else:
                    continue

                for part in event.content.parts:
                    text = getattr(part, "text", None)
                    if text:
                        progress = min(progress + 2, 92)
                        await _push(push_session_id, sse_type, content=text, progress=progress, stage=position)
                        await asyncio.sleep(0)
        except Exception:
            if iteration == 0:
                raise  # the build/compile loop never started — surface it
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
        await _push(push_session_id, "code-review-ready", content=code_review)

    await _run_standalone_agent(
        session_id, PATTERN_RUNNERS["java-8-to-25"]["incremental_reporter"],
        f"Produce the final migration report across all {total} completed stages.",
        "report-stream",
    )
    state = await _get_state(session_id)
    final_report = state.get("final_report", "")
    if final_report:
        await _push(push_session_id, "report-ready", content=final_report)

    await _run_standalone_agent(
        session_id, PATTERN_RUNNERS["java-8-to-25"]["incremental_skill_curator"],
        "Curate the java-8-to-25 skill library based on this completed incremental run.",
        "curator-stream",
    )
    state = await _get_state(session_id)
    skill_curator_summary = state.get("skill_curator_summary", "")
    if skill_curator_summary:
        await _push(push_session_id, "skill-curator-ready", content=skill_curator_summary)


async def _run_java11_code_step(session_id: str, push_session_id: str | None = None) -> None:
    """Run the java-8-to-11 code phase: the modifier once per plan task, then
    the build loop, reviewer, reporter and curator once over the result.

    The plan's single `## Stage 1: Java 8 → Java 11` section is split into its
    `### Task` blocks (agents/shared/plan_tasks.py) and each is applied by its
    own `code_modify` run with a fresh context, so a large monolith never
    accumulates every file it touches in one model context. A hand-edited plan
    with no task blocks, or no stage heading at all, still runs — as one unit
    over the stage section or the whole plan. Unlike java-8-to-25's stages,
    there is nothing to skip: this pattern has exactly one stage, so a plan
    without its heading is still entirely that stage's work.

    Every write the modifier makes goes through the scope-fenced tools
    (agents/java_8_to_11/tools.py); the frozen-file backstop runs later, in
    _run_workflow, before the diff.
    """
    push_session_id = push_session_id or session_id
    state = await _get_state(session_id)
    plan_text = state.get("plan", "")

    units, from_plan = plan_tasks.stage_units(plan_text, JAVA11_STAGE_TITLE)
    if not units:
        units = [plan_tasks.PlanTask(id="all", title=JAVA11_STAGE_TITLE, body=plan_text)]
    preamble = f"You are applying the '{JAVA11_STAGE_TITLE}' migration plan, one task at a time."

    modifier_runner = PATTERN_RUNNERS[_JAVA_8_TO_11]["code_modify"]
    stage_meta = {"stage": 1, "total": 1}
    summaries: list[str] = []
    progress = 5

    for task_index, task in enumerate(units, start=1):
        task_meta = {
            "task_id": task.id, "task_title": task.title,
            "task_index": task_index, "task_total": len(units),
        }
        if from_plan:
            await _push(push_session_id, "task-start", **stage_meta, **task_meta)
        await _update_state(session_id, {"current_task": f"{preamble}\n\n{task.body}", "modify_result": ""})
        message = types.Content(role="user", parts=[types.Part(text=(
            f"Apply task {task.id} ({task.title}) of the confirmed plan to the workspace."
        ))])
        try:
            async for event in modifier_runner.run_async(
                session_id=session_id, user_id=USER_ID, new_message=message,
            ):
                if (getattr(event, "author", "") or "") != "modifier_agent":
                    continue
                if not event.content or not event.content.parts:
                    continue
                for part in event.content.parts:
                    text = getattr(part, "text", None)
                    if text:
                        progress = min(progress + 1, 60)
                        await _push(push_session_id, "code-stream", content=text, progress=progress)
                        await asyncio.sleep(0)
        except Exception:
            # One failed task must not abandon the rest — the build loop still runs.
            traceback.print_exc()
            summaries.append(f"### Task {task.id}: {task.title}\nFAILED — see the server log.")
            continue
        task_state = await _get_state(session_id)
        summaries.append(f"### Task {task.id}: {task.title}\n{(task_state.get('modify_result') or '').strip()}")
        if from_plan:
            await _push(push_session_id, "task-complete", **stage_meta, **task_meta)

    # The build loop, reviewer, reporter and curator read one modify result for the run.
    await _update_state(session_id, {"modify_result": "\n\n".join(summaries).strip(), "current_task": ""})
    await _run_workspace_code_step(session_id, _JAVA_8_TO_11, "code_finish", push_session_id=push_session_id)


async def _enforce_scope_fence(session_id: str) -> None:
    """Put every frozen file back exactly as uploaded, before the diff.

    The fenced tools already refuse agent writes inside the fence, so for an
    agent this is a no-op. It exists for what the tools cannot see: a build
    plugin run by `mvn` during validation rewriting a descriptor or a JSP. If
    anything was undone, the reviewer's audit had already flagged it (it ran on
    the pre-restore workspace), and the report gets a note saying so.
    """
    state = await _get_state(session_id)
    pattern = state.get("pattern", "")
    if not scope_fence.fence_for(pattern):
        return
    undone = scope_fence.restore_frozen(pattern, state.get("baseline_dir", ""), state.get("workspace_dir", ""))
    if not undone:
        return
    print(f"[scope-fence] {pattern}: undid {len(undone)} frozen-file change(s): {undone}", flush=True)
    note = (
        "\n\n---\n\n## Scope Fence Enforcement (automated)\n\n"
        f"{len(undone)} frozen file(s) differed from the upload after code generation and were put back "
        "exactly as uploaded before the result was assembled. The delivered workspace does not contain "
        "these changes; the independent review above saw them before they were undone.\n\n"
        + "\n".join(f"- `{path}` — {action}" for path, action in undone)
    )
    final_report = (state.get("final_report", "") or "") + note
    await _update_state(session_id, {"final_report": final_report})
    await _push(session_id, "report-ready", content=final_report)


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

    # A dropped marker used to fail silently, and the damage is asymmetric: the
    # plan's Evidence Plan and Coverage Gaps are answered from test_inventory,
    # so losing it produces a plan that quietly claims full coverage. Fall back
    # to the section's own heading, and say so where a human will read it.
    if not test_inventory:
        heading = _re.search(
            r'^#{1,4}\s*(?:SECTION\s*4\s*[—:-]*\s*)?(?:EXISTING\s+)?TEST\s+INVENTORY\b.*$',
            tech_spec, _re.IGNORECASE | _re.MULTILINE,
        )
        if heading:
            test_inventory = tech_spec[heading.start():].strip()
            tech_spec = tech_spec[:heading.start()].strip()

    missing = [name for name, found in (
        ("ANALYSIS", _A), ("BRD", _B), ("TECHNICAL_SPECIFICATION", _T), ("TEST_INVENTORY", _X),
    ) if not found]
    # A marker in the wrong place is as damaging as a missing one and far quieter:
    # emit all five consecutively and every section parses EMPTY while the
    # missing-marker check above stays silent, because the markers are all there.
    empty = [name for name, found, body in (
        ("ANALYSIS", _A, analysis), ("BRD", _B, brd),
        ("TECHNICAL_SPECIFICATION", _T, tech_spec), ("TEST_INVENTORY", _X, test_inventory),
    ) if found and not body.strip()]

    if missing or empty:
        detail = []
        if missing:
            detail.append(f"missing marker(s): {', '.join(missing)}")
        if empty:
            detail.append(f"empty section(s): {', '.join(empty)}")
        print(f"[re] WARNING: RE output {'; '.join(detail)}", flush=True)

        reasons = []
        if missing:
            reasons.append(
                f"did not emit the {', '.join('`' + m + '`' for m in missing)} section marker(s)"
            )
        if empty:
            reasons.append(
                f"left {', '.join('`' + e + '`' for e in empty)} empty — usually because the "
                "markers were emitted together instead of as separators, with the content after "
                "them"
            )
        warning = (
            "> **Automated warning — incomplete reverse-engineering output.** The analysis "
            + " and ".join(reasons)
            + ". Check this document before confirming: the plan is built from these sections, and "
            "an empty Technical Specification or Test Inventory makes the plan's Coverage Gaps look "
            "clean when they are simply unknown.\n"
        )
        brd = warning + "\n" + (brd or combined)
        if not test_inventory.strip():
            test_inventory = warning

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
    # Valid JSON of the wrong shape was not guarded, and `"[]"` is a real value
    # here -- _create_pattern_session seeds it for a bundled code-generation
    # session. Nothing calls this with that session today, so this was latent
    # rather than live, but an AttributeError mid-run is a poor way to find out.
    if not isinstance(graph, dict):
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
                    companion_recommendations_json: str = "[]", ux_designs_json: str = "[]",
                    ingestion_warning: str = "") -> dict:
    state = {
        "pattern": pattern,
        # Non-empty when the upload could not be unpacked in full. Prepended to
        # the BRD so it cannot be missed by whoever approves the document, since
        # everything in it then describes only part of the repository.
        "ingestion_warning": ingestion_warning,
        "workspace_dir": workspace_dir,
        "baseline_dir": baseline_dir,
        "dependency_graph_json": graph_json,
        "migration_strategy": migration_strategy,
        "junit_upgrade": "true" if junit_upgrade else "false",
        "springboot_upgrade": "true" if springboot_upgrade else "false",
        "companion_recommendations_json": companion_recommendations_json,
        # stack-discovery only: the dependency mapper's two passes. `stack_prescan`
        # and `stack_known` are rendered into the mapper agent's instruction, so
        # they must exist before it runs; `stack_inventory` is its raw output and
        # `stack_inventory_markdown` the reconciled section that opens the document.
        "stack_prescan": "",
        "stack_known": "",
        "stack_inventory": "",
        "stack_inventory_markdown": "",
        # JSP -> React only: manifest of the user's UX design files (see agents/shared/ux_designs.py).
        ux_designs.STATE_KEY: ux_designs_json,
        "companion_patterns_json": "[]",
        "analysis": "",
        "brd": "",
        "technical_spec": "",
        "test_inventory": "",
        "plan": "",
        # One plan task at a time, rendered into the stage modifier's instruction (see plan_tasks).
        "current_task": "",
        # java-8-to-11 chunked reverse engineering (see _run_java11_re): the unit
        # being analysed, its findings, and the findings the merge/combine steps read.
        "re_scope": "",
        "module_findings": "",
        "merged_findings": "",
        "re_findings": "",
        "re_findings_json": "[]",
        "additional_context": "",
        "generated_files_json": "[]",
        # Browsable preview vs the complete result: `generated_files_json` is
        # capped for state size, `result_total_files` says how many files really
        # exist, and `result_archive_path` points at the full ZIP on disk.
        "result_total_files": "0",
        "result_archive_path": "",
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
    # _run_bundle_re / _run_bundle_plan / _run_bundle_code_generation. The
    # stack-discovery fan-out reaches patterns a companion bundle cannot (the JSP
    # tier, wildfly), so its keys are seeded here too.
    for p in dict.fromkeys(_CORE_PATTERNS + _STACK_PATTERNS):
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
    """The `## <label>` heading a pattern's slice gets in a combined document.

    Falls through to the stack labels so the two stack-discovery-only legs
    (`wildfly`, and the JSP tier under its stack name rather than its migration
    name) get a readable heading instead of their raw pattern id. Must stay the
    single source of these headings: _split_combined_sections finds a reviewer's
    edits by searching for exactly this string.
    """
    return (
        companion_detector.COMPANION_LABELS.get(pattern)
        or stack_detector.STACK_LABELS.get(pattern)
        or pattern
    )


def _reject_if_discovery(state: dict, action: str) -> None:
    """400 on a plan/code action against a stack-discovery session.

    The gates and state keys all exist for this pattern (it is seeded from the
    same _initial_state), so these endpoints would otherwise half-work: setting
    a gate nothing waits on, or running a planner for a pattern that has none.
    Failing loudly beats a request that returns ok and does nothing.
    """
    if state.get("pattern") == _STACK_DISCOVERY:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This session is a stack-discovery run — reverse engineering only. There is no "
                f"plan or generated code to {action}. Download the reverse-engineering document "
                f"instead."
            ),
        )


def _bundle_for(state: dict) -> list[str]:
    """The patterns this session runs, in execution order: any confirmed
    companion patterns first (dependency/library migrations), then the
    primary pattern last. Degenerates to [primary] when no companions were
    detected or the reviewer unchecked them all.

    stack-discovery is the exception. There is no primary to run last — the
    pattern itself has no `re` runner, only the stacks found in the repo do — so
    the bundle is exactly the confirmed stacks, in stack_detector.STACK_ORDER.
    Appending the pattern here would send the fan-out looking for
    PATTERN_RUNNERS["stack-discovery"]["re"], which does not exist.
    """
    selected = json.loads(state.get("companion_patterns_json", "[]"))
    if state.get("pattern") == _STACK_DISCOVERY:
        return [p for p in _STACK_PATTERNS if p in selected]
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


def _parse_mapper_json(raw: str) -> dict:
    """Extract the dependency mapper's trailing ```json block.

    Deliberately not _parse_validation_json: that one falls back to scanning from
    the first `{` to the last `}`, which here would start inside the prose
    inventory (a JNDI name, a `${...}` property, a code excerpt) and capture
    nothing valid. The mapper's contract puts the block last, so the last fenced
    block wins, and a bare object anywhere is only the final fallback.
    """
    text = (raw or "").strip()
    if not text:
        return {}

    blocks = _re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, _re.DOTALL)
    for block in reversed(blocks):
        try:
            return json.loads(block)
        except Exception:
            continue

    # Unfenced: take the widest object that parses, searching from the end since
    # that is where the contract puts it.
    for start in sorted((m.start() for m in _re.finditer(r"\{", text)), reverse=True):
        candidate = text[start : text.rfind("}") + 1]
        if '"stacks"' not in candidate:
            continue
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return {}


def _merge_mapper_result(prescan: list[dict], raw: str) -> tuple[list[dict], list[str]]:
    """Reconcile the LLM mapper's JSON block against the deterministic pre-scan.

    Returns `(stacks, notes)` — the stacks to reverse-engineer, and any notes to
    surface to the reviewer about what was dropped and why.

    The pre-scan is the floor. The mapper may enrich a stack's evidence, reject
    one with a stated reason, or add one it found, but three things are enforced
    here rather than trusted to the prompt:

    - **A stack with no evidence is dropped.** Uncited is indistinguishable from
      invented, and this document is downloaded and relied on.
    - **An added stack must be a pattern we can actually run.** An unknown
      identifier is recorded as a note for the reviewer, not silently turned into
      a fan-out leg that would KeyError on PATTERN_RUNNERS.
    - **A rejection needs a reason.** Rejecting a deterministic finding is the one
      move here that removes evidence from the document, so it has to be argued;
      a bare rejection leaves the pre-scan's finding standing.
    """
    by_pattern: dict[str, dict] = {s["pattern"]: dict(s) for s in prescan}
    notes: list[str] = []

    parsed = _parse_mapper_json(raw)
    # An unparseable reply must not read as "no stacks found" — that would
    # silently discard the deterministic findings and produce an empty document.
    if not isinstance(parsed, dict) or "stacks" not in parsed:
        notes.append(
            "The dependency mapper's machine-readable block could not be parsed, so the "
            "deterministic scan's findings are used as-is. Its written inventory is still in the "
            "document."
        )
        return list(by_pattern.values()), notes

    known = set(stack_detector.STACK_ORDER)

    for entry in parsed.get("stacks") or []:
        if not isinstance(entry, dict):
            continue
        pattern = str(entry.get("pattern") or "").strip()
        evidence = [str(e).strip() for e in (entry.get("evidence") or []) if str(e).strip()]
        if not pattern or not evidence:
            notes.append(
                f"Dropped a stack the mapper reported without evidence: `{pattern or 'unnamed'}`."
            )
            continue
        if pattern not in known:
            notes.append(
                f"The mapper reported `{pattern}` ({entry.get('label') or pattern}), which has no "
                f"RE skill in this pipeline — recorded here but not reverse engineered. "
                f"Evidence: {'; '.join(evidence[:3])}"
            )
            continue
        if pattern in by_pattern:
            # Confirmed. The mapper read the files, so prefer its citations and
            # keep the pre-scan's underneath as corroboration.
            existing = by_pattern[pattern]["evidence"]
            merged = evidence + [e for e in existing if e not in evidence]
            by_pattern[pattern]["evidence"] = merged[:6]
        else:
            by_pattern[pattern] = {
                "pattern": pattern,
                "label": str(entry.get("label") or stack_detector.STACK_LABELS.get(pattern, pattern)),
                "evidence": evidence[:6],
                "extraction_only": pattern in stack_detector.EXTRACTION_ONLY_PATTERNS,
            }

    for entry in parsed.get("rejected") or []:
        if not isinstance(entry, dict):
            continue
        pattern = str(entry.get("pattern") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        if pattern not in by_pattern:
            continue
        if not reason:
            notes.append(
                f"The mapper rejected `{pattern}` without a reason, so the deterministic scan's "
                "finding stands."
            )
            continue
        del by_pattern[pattern]
        notes.append(f"`{pattern}` was detected by the scan but rejected by the mapper: {reason}")

    ordered = [by_pattern[p] for p in stack_detector.STACK_ORDER if p in by_pattern]
    return ordered, notes


async def _run_stack_mapping(session_id: str) -> list[dict]:
    """Pass 2 of the dependency mapper: the LLM reads the build files and
    descriptors, with the deterministic pre-scan's findings in its prompt.

    Returns the reconciled stack list. The prose inventory it produced is stored
    for the combined document; the JSON block is merged by _merge_mapper_result.
    """
    state = await _get_state(session_id)
    prescan = json.loads(state.get("companion_recommendations_json", "[]"))

    await _update_state(session_id, {
        "stack_prescan": stack_detector.to_markdown(prescan) or "No stacks detected by the pre-scan.",
        "stack_known": "\n".join(
            f"- `{p}` — {stack_detector.STACK_LABELS.get(p, p)}"
            + ("  (extraction only, no migration target)" if p in stack_detector.EXTRACTION_ONLY_PATTERNS else "")
            for p in stack_detector.STACK_ORDER
        ),
    })

    await _run_step(
        session_id, "mapper", _STACK_DISCOVERY,
        message=(
            "Map every technology stack in this repository workspace, starting at the root. "
            "Confirm, reject or extend the pre-scan findings in your instructions, and end with "
            "the machine-readable JSON block."
        ),
        sse_event_type="mapper-stream",
    )

    state = await _get_state(session_id)
    raw = state.get("stack_inventory", "")
    stacks, notes = _merge_mapper_result(prescan, raw)

    # The prose inventory is the mapper's own; the table is regenerated from the
    # reconciled list so the document's inventory matches what actually ran.
    inventory = stack_detector.to_markdown(stacks, source="deterministic scan + dependency mapper")
    prose = raw.strip()
    if prose:
        inventory += "\n\n" + prose
    if notes:
        inventory += "\n\n### Mapper Reconciliation Notes\n\n" + "\n".join(f"- {n}" for n in notes)

    await _update_state(session_id, {
        "stack_inventory_markdown": inventory,
        "companion_recommendations_json": json.dumps(stacks),
    })
    return stacks


def _clip_findings(text: str, limit: int, label: str) -> str:
    """Findings cut to *limit* characters, with the cut stated where the
    document's reader and the combining agent will see it — never silently."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return (
        text[:limit].rstrip()
        + f"\n\n> ⚠ **Findings for {label} were cut at {limit:,} characters.** Rows after this point are "
        "missing from this document; raise RE_FINDINGS_MAX_CHARS / RE_SYNTHESIS_MAX_CHARS to keep them."
    )


def _batch_by_size(items: list[str], budget: int) -> list[list[str]]:
    """Consecutive batches whose joined size stays within *budget*."""
    batches: list[list[str]] = []
    size = 0
    for item in items:
        if batches and size + len(item) <= budget:
            batches[-1].append(item)
            size += len(item)
        else:
            batches.append([item])
            size = len(item)
    return batches


async def _run_java11_inventory(session_id: str, feedback: str | None = None) -> None:
    """java-8-to-11 analysis without a model: the deterministic Java 11 inventory
    (agents/java_8_to_11/inventory.py), written to state["analysis"] in the same
    four-section format the reverse-engineering agents produce, so the review
    screen, the planner and the code steps are unchanged. Uses no model tokens.

    The inventory is a function of the code, so "Refine with AI" cannot reword
    it: the reviewer's feedback is kept as Reviewer Notes at the top of the
    scope section, where the planner reads it.
    """
    state = await _get_state(session_id)
    workspace_dir = state.get("workspace_dir", "")
    await _push(session_id, "progress", message="Scanning every file for the Java 11 inventory", progress=10)
    started = time.monotonic()
    inventory = await asyncio.to_thread(java11_inventory.build, workspace_dir)
    document = java11_inventory.to_document(inventory, max_rows=config.INVENTORY_MAX_ROWS)
    if feedback:
        document = document.replace(
            "<!-- SECTION: BRD -->\n",
            "<!-- SECTION: BRD -->\n\n## Reviewer Notes\n\n" + feedback.strip() + "\n\n"
            "_Carried to the planner as written. The inventory itself is regenerated from the code; "
            "to change its content, edit the document before confirming._\n",
            1,
        )
    elapsed = time.monotonic() - started
    print(f"[inventory] {inventory.files_scanned:,} files / {inventory.lines_scanned:,} lines in {elapsed:.1f}s", flush=True)
    await _push(session_id, "re-stream", content=(
        f"**Java 11 inventory** — {inventory.files_scanned:,} files ({inventory.lines_scanned:,} lines) scanned "
        f"in {elapsed:.1f}s without a language model.\n"
    ))
    await _update_state(session_id, {"analysis": document})


async def _run_java11_re(session_id: str, message: str, refine: bool = False) -> None:
    """java-8-to-11 reverse engineering, chunked so that no single model request
    grows with the size of the repository.

    1. Split the repository into units (re_units.plan_units): each Maven/Gradle
       module, split further along its directories above RE_UNIT_MAX_FILES.
    2. Run `re_module` once per unit, each with a fresh context: it writes that
       unit's Module Findings.
    3. If all findings together exceed RE_SYNTHESIS_MAX_CHARS, merge them with
       `re_merge` in batches that fit, repeating until they do. Each merged result
       is capped at half the budget, so every round strictly reduces the count.
    4. `re_synthesize` writes the four-section document into state["analysis"],
       exactly where the single-pass agent put it, so everything downstream is
       unchanged.

    A refine ("Refine with AI") re-runs step 4 only, from the stored findings and
    the reviewer's feedback: re-analysing every unit to reword a document would
    cost the whole run again. RE_UNIT_MAX_FILES=0 falls back to the single-pass
    agent.
    """
    if config.RE_UNIT_MAX_FILES <= 0:
        await _run_step(session_id, "re", _JAVA_8_TO_11, message=message, sse_event_type="re-stream")
        return

    state = await _get_state(session_id)
    budget = max(config.RE_SYNTHESIS_MAX_CHARS, 2)
    per_unit = min(config.RE_FINDINGS_MAX_CHARS, budget // 2)
    stored = json.loads(state.get("re_findings_json") or "[]")

    if refine and stored:
        findings = stored
    else:
        units = re_units.plan_units(state.get("workspace_dir", ""), config.RE_UNIT_MAX_FILES)
        total = len(units)
        print(f"[re] {total} unit(s) of at most {config.RE_UNIT_MAX_FILES} files", flush=True)
        await _push(session_id, "re-stream", content=(
            f"\n**Large-repository mode:** analysing {total} unit(s) of at most "
            f"{config.RE_UNIT_MAX_FILES} files, each in its own run.\n"
        ))
        findings = []
        failed = 0
        for index, unit in enumerate(units, 1):
            await _push(session_id, "progress", message=f"Reverse engineering unit {index}/{total}: {unit.label}",
                        progress=int(5 + 80 * (index - 1) / max(total, 1)))
            await _push(session_id, "re-stream", content=f"\n\n### Unit {index}/{total}: {unit.label}\n")
            await _update_state(session_id, {"re_scope": unit.describe(), "module_findings": ""})
            error = ""
            try:
                await _run_step(
                    session_id, "re_module", _JAVA_8_TO_11,
                    message=f"Analyse unit {unit.id} ({unit.label}) and write its Module Findings.",
                    sse_event_type="re-stream",
                )
                text = (await _get_state(session_id)).get("module_findings", "")
            except Exception as exc:
                traceback.print_exc()
                failed += 1
                text = ""
                error = _describe_error(exc)
            if not text.strip():
                reason = error or "the run returned no findings"
                text = (f"## Unit {unit.id}: {unit.label}\n\n> ⚠ **Not analysed** — {reason}. "
                        "Nothing in this unit is covered by this document.")
            findings.append(_clip_findings(text, per_unit, f"unit {unit.id} ({unit.label})"))
        if units and failed == len(units):
            raise RuntimeError(f"Reverse engineering failed for every unit ({failed}). Last error: {findings[-1]}")
        await _update_state(session_id, {"re_findings_json": json.dumps(findings)})

    rounds = 0
    while sum(len(f) for f in findings) > budget and len(findings) > 1:
        rounds += 1
        merged: list[str] = []
        batches = _batch_by_size(findings, budget)
        for number, batch in enumerate(batches, 1):
            if len(batch) == 1:
                merged.append(batch[0])
                continue
            await _push(session_id, "progress", message=(
                f"Merging findings: round {rounds}, batch {number}/{len(batches)}"), progress=88)
            await _update_state(session_id, {"re_findings": "\n\n---\n\n".join(batch), "merged_findings": ""})
            await _run_step(session_id, "re_merge", _JAVA_8_TO_11,
                            message="Merge these Module Findings.", sse_event_type="re-stream")
            text = (await _get_state(session_id)).get("merged_findings", "")
            merged.append(_clip_findings(text, budget // 2, f"merged batch {rounds}.{number}"))
        findings = merged

    combined = _clip_findings("\n\n---\n\n".join(findings), budget, "the combined findings")
    await _push(session_id, "progress", message="Writing the analysis document from the findings", progress=92)
    await _update_state(session_id, {"re_findings": combined, "analysis": ""})
    await _run_step(session_id, "re_synthesize", _JAVA_8_TO_11, message=message, sse_event_type="re-stream")


async def _run_bundle_re(session_id: str, bundle: list[str], feedback: str | None = None) -> None:
    """Runs each pattern's re_agent once. With `feedback` set (the "Refine
    with AI" flow), each pattern is asked to revise its own previous
    namespaced section rather than explore from scratch — this is what
    keeps a refine on a bundled multi-pattern BRD from silently dropping
    the other patterns' sections.

    Serves stack-discovery too, where `bundle` is the confirmed stacks rather
    than a primary plus companions. The differences are that the per-stack
    instruction says stack rather than migration domain, and that the combined
    document opens with the stack inventory — see `discovery` below.
    """
    orig_state = await _get_state(session_id)
    workspace_dir = orig_state.get("workspace_dir", "")
    primary = orig_state.get("pattern")
    primary_graph_json = orig_state.get("dependency_graph_json", "")
    discovery = primary == _STACK_DISCOVERY

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
        if discovery:
            # "migration domain" would be a lie here: nothing is being migrated,
            # and one of these legs (wildfly) has no target platform at all.
            message += (
                f" Confine yourself to the {_label(pattern)} stack — other stacks in this "
                "repository are being reverse-engineered separately, so do not describe them. "
                "This is a discovery run with no migration attached: report what exists and do "
                "not recommend, sequence or estimate any migration work."
            )
        elif len(bundle) > 1:
            message += f" Focus specifically on the {_label(pattern)} migration domain."

        if pattern == _JAVA_8_TO_11 and config.JAVA11_ANALYSIS == "agent":
            await _run_java11_re(session_id, message, refine=bool(feedback))
        elif pattern == _JAVA_8_TO_11:
            await _run_java11_inventory(session_id, feedback)
        else:
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

    if len(bundle) == 1 and not discovery:
        brd, tech_spec, test_inventory = sections[bundle[0]]
    else:
        # `primary` is not in the bundle on a discovery run, so every pattern
        # sorts equal and Python's stable sort leaves stack_detector.STACK_ORDER
        # intact — which is the order we want there.
        ordered = sorted(bundle, key=lambda p: 0 if p == primary else 1)

        def _combine(idx: int) -> str:
            parts = [f"## {_label(p)}\n\n{sections[p][idx]}" for p in ordered if sections[p][idx]]
            return "\n\n---\n\n".join(parts)

        brd, tech_spec, test_inventory = _combine(0), _combine(1), _combine(2)

    if discovery:
        # The inventory leads the document: it is the answer to "what is in this
        # repo", and it carries the evidence for every section that follows. Kept
        # above the per-stack headings so _split_combined_sections still finds
        # them (it searches for `## <label>` lines, and the inventory's own
        # heading is not one of those).
        inventory = orig_state.get("stack_inventory_markdown", "")
        if inventory:
            brd = f"{inventory}\n\n---\n\n{brd}" if brd else inventory
        if not bundle:
            brd = (brd + "\n\n") if brd else ""
            brd += (
                "> **No stacks were reverse engineered.** Either nothing was detected, or every "
                "detected stack was unchecked at the confirmation step. The inventory above, if "
                "present, is the deterministic scan's finding only — no RE skill ran."
            )

    # A partial workspace invalidates every inventory and coverage claim below it,
    # so the warning leads the document rather than sitting in a log nobody reads.
    ingestion_warning = orig_state.get("ingestion_warning", "")
    if ingestion_warning:
        banner = f"> ⚠️ **Incomplete repository.** {ingestion_warning}\n"
        brd = f"{banner}\n{brd}" if brd else banner
        tech_spec = f"{banner}\n{tech_spec}" if tech_spec else banner

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
    ux_designs_json: str = "[]",
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
    state[ux_designs.STATE_KEY] = ux_designs_json
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
                outward_state.get(ux_designs.STATE_KEY, "[]"),
            )
        else:
            if plan_for_pattern:
                await _update_state(session_id, {"plan": plan_for_pattern})
            run_session_id = session_id

        # The strategy the user chose is honoured here too. Keying only on the
        # pattern silently ran a phased plan through the single-pass pipeline
        # whenever a companion migration was selected alongside it.
        if pattern == "java-8-to-25" and migration_strategy == "incremental":
            await _run_java8_incremental_code_step(run_session_id, push_session_id=session_id)
        elif pattern == _JAVA_8_TO_11:
            await _run_java11_code_step(run_session_id, push_session_id=session_id)
        else:
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


async def _run_stack_discovery_workflow(session_id: str) -> None:
    """The stack-discovery pipeline: map -> confirm -> reverse-engineer -> stop.

    Ends at brd-review. There is no plan step and no code generation, so the
    workspace is cleaned up as soon as the reviewer has confirmed the document —
    by then every agent that will ever read it has run.

    Raises on failure like the rest of _run_workflow's body; the caller owns the
    error push and the SSE sentinel.
    """
    await _push(session_id, "step-change", step="stack-mapping")
    stacks = await _run_stack_mapping(session_id)
    await _push(session_id, "stack-inventory-ready", stacks=stacks)

    if stacks:
        # Same event, gate and endpoint as the companion flow — from the
        # reviewer's side it is the same decision (which of these detected
        # things do you want worked on), so it gets the same UI.
        await _push(session_id, "companion-recommendations", companions=stacks)
        await _push(session_id, "step-change", step="companion-selection")
        await _companion_gates[session_id].wait()
    else:
        # Nothing to choose between. Gating here would park the run on a
        # confirmation screen with no options on it.
        _companion_gates[session_id].set()

    state = await _get_state(session_id)
    bundle = _bundle_for(state)

    await _push(session_id, "step-change", step="reverse-engineering")
    await _run_bundle_re(session_id, bundle)

    await _push(session_id, "step-change", step="brd-review")
    await _brd_gates[session_id].wait()

    state = await _get_state(session_id)
    for key in ("workspace_dir", "baseline_dir"):
        directory = state.get(key)
        if directory:
            shutil.rmtree(directory, ignore_errors=True)

    await _push(session_id, "step-change", step="complete")
    await _push(session_id, "workflow-complete")


def _describe_error(exc: Exception) -> str:
    """The message the UI shows for a failed run. A 429 that outlasted every
    retry gets an explanation of what to change, not just the raw API error."""
    if getattr(exc, "code", None) == 429:
        return (
            "The model quota was still exhausted (429 RESOURCE_EXHAUSTED) after "
            f"{config.LLM_RETRY_ATTEMPTS} attempts with backoff of up to {config.LLM_RETRY_MAX_DELAY:.0f}s. "
            "Wait for the quota window to reset and retry, raise the quota for this model (Vertex AI / "
            "Gemini API quotas page), avoid running several uploads at once, or raise LLM_RETRY_ATTEMPTS / "
            f"LLM_RETRY_MAX_DELAY in .env. Details: {exc}"
        )
    return str(exc)


async def _run_workflow(session_id: str) -> None:
    try:
        state = await _get_state(session_id)
        pattern = state["pattern"]

        await _push(session_id, "step-change", step="dependency-graph")
        await _push(session_id, "dependency-graph-ready")

        # ── stack-discovery: map the stacks, reverse-engineer each, then stop ──
        if pattern == _STACK_DISCOVERY:
            await _run_stack_discovery_workflow(session_id)
            return

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

        # ── Scope fence backstop: frozen files back to their uploaded bytes ─
        try:
            await _enforce_scope_fence(session_id)
        except Exception:
            traceback.print_exc()

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

        # The complete result goes to a ZIP on disk BEFORE the workspace is
        # deleted; session state only carries the capped browsable preview.
        try:
            archive_path = _archive_workspace(workspace_dir) if workspace_dir else None
        except Exception:
            traceback.print_exc()
            archive_path = None

        try:
            files, total_files = (
                _workspace_to_files(workspace_dir, TARGET_LANGS[pattern]) if workspace_dir else ([], 0)
            )
        except Exception:
            traceback.print_exc()
            files, total_files = [], 0
        files_payload = [f.model_dump() for f in files]

        await _update_state(session_id, {
            "generated_files_json": json.dumps(files_payload),
            "changed_files_json": json.dumps(changed_files),
            "result_total_files": str(total_files),
            "result_archive_path": archive_path or "",
        })
        # `total` lets the browser say "showing 2,000 of 18,412" instead of
        # presenting a capped list as if it were the whole result.
        await _push(session_id, "code-ready", files=files_payload, total=total_files)

        if workspace_dir:
            shutil.rmtree(workspace_dir, ignore_errors=True)
        if baseline_dir:
            shutil.rmtree(baseline_dir, ignore_errors=True)

        await _push(session_id, "step-change", step="complete")
        await _push(session_id, "workflow-complete")

    except Exception as exc:
        traceback.print_exc()  # the UI only receives str(exc); keep the full traceback in the server log
        await _push(session_id, "error", message=_describe_error(exc))
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

app = FastAPI(title="Stella Modernizer API (ADK-powered)", lifespan=lifespan)
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
    ux_files: list[UploadFile] | None = File(None),
):
    # Optional UX designs (JSP -> React only) — checked before any workspace is created.
    ux_uploads = [(u.filename or "design", await u.read()) for u in (ux_files or [])]
    if ux_uploads and pattern.value != "jsp-to-react-bff":
        raise HTTPException(status_code=400, detail="UX designs can only be attached to the JSP → React migration.")
    # stack-discovery generates nothing, so the code-generation options have
    # nothing to act on. Rejected rather than ignored: silently accepting
    # `incremental` here would tell the caller a phased build is going to happen.
    if pattern.value == _STACK_DISCOVERY and (
        migration_strategy != "bigbang" or junit_upgrade or springboot_upgrade
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Stack discovery is reverse-engineering only — it produces no plan and no code, so "
                "the migration strategy and the JUnit/Spring Boot upgrade toggles do not apply."
            ),
        )
    # The Java 11 upgrade has one strategy and changes the JDK only, so the
    # Java 8 -> 25 options would promise work the fence forbids (Spring Boot)
    # or a shape the pipeline does not have (a phased run). Rejected, not ignored.
    if pattern.value == _JAVA_8_TO_11 and (
        migration_strategy != "bigbang" or junit_upgrade or springboot_upgrade
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Java 8 → Java 11 is a JDK-only upgrade in a single pass — the phased strategy and the "
                "JUnit/Spring Boot upgrade toggles do not apply. JSP views and the WildFly deployment "
                "are left exactly as uploaded."
            ),
        )
    try:
        ux_designs.validate(ux_uploads)
    except ux_designs.UxDesignError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Checked before anything is unpacked: a repository is only worth ingesting
    # if the agents that read it can reach a model.
    if not LLM_AUTH.ok:
        raise HTTPException(status_code=503, detail=f"LLM access is not configured: {LLM_AUTH.error}")

    raw = await file.read()

    ws_path = Path(tempfile.mkdtemp(prefix="modernizer-ws-"))
    if file.filename and file.filename.endswith(".zip"):
        extraction = _extract_zip_to_dir(raw, ws_path)
    else:
        (ws_path / (file.filename or "uploaded-source")).write_bytes(raw)
        extraction = ExtractionResult(files=1, total_bytes=len(raw), truncated=0, unsafe=0)

    files_found = extraction.files
    if files_found == 0:
        shutil.rmtree(ws_path, ignore_errors=True)
        raise HTTPException(status_code=400, detail="No readable source files found.")

    # A partial workspace is reported, loudly and in three places: the upload
    # response, the server log, and the document the reviewer signs off on (see
    # _initial_state's ingestion_warning, prepended to the BRD by
    # _run_bundle_re). Carrying on quietly here is what made every downstream
    # answer confidently wrong.
    if not extraction.complete:
        print(
            f"[upload] WARNING: workspace truncated — unpacked {extraction.files:,} files, "
            f"left {extraction.truncated:,} behind (limits: {config.WORKSPACE_MAX_FILES:,} files / "
            f"{config.WORKSPACE_MAX_TOTAL_BYTES:,} bytes)",
            flush=True,
        )

    workspace_dir = str(ws_path)
    baseline_dir = diffing.snapshot_workspace(workspace_dir)
    # Stored outside the workspace, so the designs never show up in the code diff.
    ux_manifest = (
        ux_designs.save(ux_uploads, Path(tempfile.mkdtemp(prefix="modernizer-ux-"))) if ux_uploads else []
    )
    graph = dependency_graph.build_dependency_graph(workspace_dir, pattern.value)
    graph_json = json.dumps(graph)

    # Both detectors write to the same state key, because both answer "what else
    # is in here" and feed the same confirmation gate. Which one runs is the only
    # difference: companion detection needs a chosen primary and looks for that
    # primary's companions; stack discovery has no primary and looks for
    # everything, including the stacks that are a primary elsewhere.
    if pattern.value == _STACK_DISCOVERY:
        companion_recs = stack_detector.detect_stacks(workspace_dir)
    elif pattern.value in companion_detector.COMPANION_CANDIDATES:
        companion_recs = companion_detector.detect_companions(workspace_dir, pattern.value)
    else:
        companion_recs = []
    companion_recs_json = json.dumps(companion_recs)

    # Create ADK session with initial state
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state=_initial_state(
            pattern.value, workspace_dir, baseline_dir, graph_json,
            migration_strategy, junit_upgrade, springboot_upgrade,
            companion_recs_json,
            ux_designs_json=json.dumps(ux_manifest),
            ingestion_warning=extraction.warning(),
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
        message=(
            "Upload successful. Workflow started."
            if extraction.complete
            else f"Upload INCOMPLETE — {extraction.truncated:,} files exceeded this server's "
                 "ingestion limit and were not unpacked. The workflow started against a partial "
                 "copy of the repository."
        ),
        files_found=files_found,
        files_truncated=extraction.truncated,
        ux_designs=len(ux_manifest),
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


@app.get("/api/sessions/{session_id}/download/reverse-engineering")
async def download_reverse_engineering(session_id: str):
    """The full reverse-engineering document as one Markdown file.

    The existing /download/brd returns only the BRD slice, which is the right
    deliverable mid-migration but not here: for a stack-discovery run the whole
    document *is* the deliverable, and the Technical Specification carries the
    per-stack detail. Available for every pattern, since a migration run's
    reviewer may want the same thing.
    """
    state = await _get_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found.")

    brd = state.get("brd", "")
    tech_spec = state.get("technical_spec", "")
    test_inventory = state.get("test_inventory", "")
    if not any((brd, tech_spec, test_inventory)):
        raise HTTPException(status_code=404, detail="Reverse engineering has not produced a document yet.")

    parts = [f"# Reverse Engineering — {_label(state.get('pattern', ''))}", ""]
    for heading, body in (
        ("Business Requirements", brd),
        ("Technical Specification", tech_spec),
        ("Existing Test Inventory", test_inventory),
    ):
        # An empty section is named rather than omitted: silence here reads as
        # "nothing to report" when it usually means a section failed to parse.
        parts.append(f"# {heading}\n\n{body.strip() or '_Not produced for this run._'}")
    document = "\n\n---\n\n".join(parts)

    return Response(
        content=document,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="reverse-engineering-{session_id[:8]}.md"'},
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
    _reject_if_discovery(state, "confirm a plan")
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
    _reject_if_discovery(state, "refine a plan")
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
    """Return the migrated repository as a ZIP, preserving folder structure.

    Streams the archive built from the workspace at the end of the run, so the
    download is always the complete result — session state only holds the capped
    browsable preview. Falls back to rebuilding from that preview for a session
    that predates the archive (whose ZIP is then the preview, and says so).
    """
    state = await _get_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found.")

    pattern_slug = state.get("pattern", "migration").replace("/", "-")
    filename = f"{pattern_slug}-migrated.zip"

    archive_path = state.get("result_archive_path", "")
    if archive_path and Path(archive_path).is_file():
        return StreamingResponse(
            open(archive_path, "rb"),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    files = json.loads(state.get("generated_files_json", "[]"))
    if not files:
        raise HTTPException(status_code=404, detail="No generated files found.")

    total = int(state.get("result_total_files") or len(files))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            # Use the path as-is so folder structure is preserved inside the ZIP
            zf.writestr(f["path"], f["content"])
        if total > len(files):
            zf.writestr(
                "INCOMPLETE-DOWNLOAD.txt",
                f"This archive holds {len(files)} of {total} files. The complete result archive "
                "for this session is no longer on disk, so it was rebuilt from the browsable "
                "preview, which is capped. Re-run to get a complete archive.\n",
            )
    buf.seek(0)

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
    # `llm` never carries a key or credential contents — see AuthConfig.public.
    return {"status": "ok", "framework": "google-adk", "llm": LLM_AUTH.public()}
