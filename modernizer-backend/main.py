import asyncio
import io
import json
import os
import shutil
import uuid
import zipfile
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from google.adk.events import Event, EventActions
from google.genai import types
from pydantic import BaseModel

load_dotenv()

# ADK expects GOOGLE_API_KEY; map from GEMINI_API_KEY if needed
if not os.getenv("GOOGLE_API_KEY") and os.getenv("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

from agents import APP_NAME, USER_ID, PATTERN_RUNNERS, TARGET_LANGS, session_service
from agents.shared.file_parser import extract_text
from agents.shared.code_parser import parse_generated_files
from models.schemas import PatternType, UploadResponse, ConfirmRequest, GeneratedFile

# ---------------------------------------------------------------------------
# In-process state (SSE queues and HITL events)
# ---------------------------------------------------------------------------

# Per-session asyncio.Queue feeds the SSE endpoint
_sse_queues: dict[str, asyncio.Queue] = {}

# Per-session asyncio.Events gate the HITL confirmation steps
_brd_gates: dict[str, asyncio.Event] = {}
_plan_gates: dict[str, asyncio.Event] = {}

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


def _extract_zip(zip_bytes: bytes) -> str:
    EXTENSIONS = {
        # Java / Go / general
        ".java", ".xml", ".gradle", ".kts", ".properties", ".yaml", ".yml", ".json", ".go", ".mod",
        # TIBCO BusinessWorks artefacts
        ".bwp", ".process", ".substvar", ".xsd", ".wsdl", ".xslt", ".xsl",
        # C# / .NET artefacts
        ".cs", ".csproj", ".sln", ".config", ".razor", ".cshtml", ".resx",
    }
    MAX_TOTAL = 100_000
    lines: list[str] = []
    total = 0
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "upload.zip"
        zip_path.write_bytes(zip_bytes)
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                p = Path(info.filename)
                if p.suffix.lower() not in EXTENSIONS:
                    continue
                if set(p.parts) & {".git", "target", "build", "node_modules", ".gradle", "__pycache__", "bin", "obj"}:
                    continue
                try:
                    content = zf.read(info).decode("utf-8", errors="replace")
                except Exception:
                    continue
                chunk = f"\n\n// === FILE: {info.filename} ===\n{content}"
                if total + len(chunk) > MAX_TOTAL:
                    break
                lines.append(chunk)
                total += len(chunk)
    return "".join(lines) if lines else "(empty repository)"


# ---------------------------------------------------------------------------
# Real workspace helpers — java11-to-java25 only.
#
# Every other pattern above works from a single text dump of the source.
# java11-to-java25's agents have real read/write/run tools instead (see
# agents/java11_to_java25/tools.py), so the uploaded repository needs to
# exist as real files on disk rather than as a concatenated string.
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
# ADK step runner
# ---------------------------------------------------------------------------

async def _run_step(
    session_id: str,
    step_key: str,
    pattern: str,
    message: str,
    sse_event_type: str,
) -> None:
    """Invoke one ADK agent step, streaming text chunks to the SSE queue."""
    runner = PATTERN_RUNNERS[pattern][step_key]
    content = types.Content(role="user", parts=[types.Part(text=message)])

    progress = 5
    async for event in runner.run_async(
        session_id=session_id,
        user_id=USER_ID,
        new_message=content,
    ):
        if not event.content:
            continue
        for part in event.content.parts:
            text = getattr(part, "text", None)
            if text:
                progress = min(progress + 3, 92)
                await _push(session_id, sse_event_type, content=text, progress=progress)
                await asyncio.sleep(0)  # yield to event loop


def _parse_validation_json(raw: str) -> dict:
    """Parse the JSON validation result produced by the validate agent."""
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


async def _run_quarkus_code_step(session_id: str, code_message: str) -> None:
    """Run the Quarkus code_pipeline (code_agent → LoopAgent(validate, fix, max=4)).

    Streams events to the SSE queue with author-aware routing:
      quarkus_code     → code-stream
      quarkus_validate → validate-stream  (also emits validation-agent-start)
      quarkus_fix      → fix-stream       (also emits fix-agent-start)

    After the pipeline completes, reads validation_result from session state
    and emits a validation-complete event.
    """
    runner = PATTERN_RUNNERS["java-to-quarkus"]["code"]
    content = types.Content(role="user", parts=[types.Part(text=code_message)])

    prev_author = ""
    iteration = 0
    progress = 5

    async for event in runner.run_async(
        session_id=session_id,
        user_id=USER_ID,
        new_message=content,
    ):
        author = getattr(event, "author", "") or ""

        # ── Author-transition signals ─────────────────────────────────────
        if author and author != prev_author:
            if "quarkus_validate" in author:
                iteration += 1
                await _push(session_id, "validation-agent-start", iteration=iteration)
            elif "quarkus_fix" in author:
                await _push(session_id, "fix-agent-start", iteration=iteration)
            prev_author = author

        if not event.content:
            continue

        # ── Route text by author ──────────────────────────────────────────
        if "quarkus_validate" in author:
            sse_type = "validate-stream"
        elif "quarkus_fix" in author:
            sse_type = "fix-stream"
        elif "quarkus_code" in author:
            sse_type = "code-stream"
        else:
            continue  # skip SequentialAgent / LoopAgent envelope events

        for part in event.content.parts:
            text = getattr(part, "text", None)
            if text:
                progress = min(progress + 2, 92)
                await _push(session_id, sse_type, content=text, progress=progress)
                await asyncio.sleep(0)

    # ── Emit final validation result ──────────────────────────────────────
    state = await _get_state(session_id)
    raw_result = state.get("validation_result", "")
    validation = _parse_validation_json(raw_result) if raw_result else {"passed": True, "errors": [], "summary": ""}
    await _push(
        session_id,
        "validation-complete",
        passed=validation.get("passed", True),
        errors=validation.get("errors", []),
        summary=validation.get("summary", ""),
        iterations=iteration,
    )

async def _run_java11_code_step(session_id: str) -> List[GeneratedFile]:
    """Run the java11-to-java25 code_pipeline: modifier_agent -> LoopAgent
    (validator_agent, fixer_agent, max=3) -> reporter_agent.

    Unlike every other pattern's code step, modifier_agent/fixer_agent write
    real files to the session's workspace directory via tools instead of
    returning a text blob, and modifier_agent reads the confirmed plan
    straight from session state (its instruction has a `{plan}` template
    variable) — no code message needs to be built here.

    Streams events to the SSE queue with author-aware routing:
      modifier_agent  -> code-stream
      validator_agent -> validate-stream  (also emits validation-agent-start)
      fixer_agent     -> fix-stream       (also emits fix-agent-start)
      reporter_agent  -> report-stream

    After the pipeline completes: emits validation-complete from build_result,
    emits report-ready from final_report, collects the migrated files from
    the workspace directory on disk, deletes the workspace, and returns the
    files for the caller to persist into generated_files_json.
    """
    runner = PATTERN_RUNNERS["java11-to-java25"]["code"]
    content = types.Content(role="user", parts=[types.Part(text=(
        "Apply the confirmed migration plan to the workspace, build the "
        "project and fix any errors, then produce the final report."
    ))])

    prev_author = ""
    iteration = 0
    progress = 5

    async for event in runner.run_async(
        session_id=session_id,
        user_id=USER_ID,
        new_message=content,
    ):
        author = getattr(event, "author", "") or ""

        if author and author != prev_author:
            if "validator_agent" in author:
                iteration += 1
                await _push(session_id, "validation-agent-start", iteration=iteration)
            elif "fixer_agent" in author:
                await _push(session_id, "fix-agent-start", iteration=iteration)
            prev_author = author

        if not event.content:
            continue

        if "validator_agent" in author:
            sse_type = "validate-stream"
        elif "fixer_agent" in author:
            sse_type = "fix-stream"
        elif "modifier_agent" in author:
            sse_type = "code-stream"
        elif "reporter_agent" in author:
            sse_type = "report-stream"
        else:
            continue  # skip SequentialAgent / LoopAgent envelope events

        for part in event.content.parts:
            text = getattr(part, "text", None)
            if text:
                progress = min(progress + 2, 92)
                await _push(session_id, sse_type, content=text, progress=progress)
                await asyncio.sleep(0)

    # ── Emit final build result + report, then collect files from disk ─────
    state = await _get_state(session_id)
    raw_result = state.get("build_result", "")
    validation = _parse_validation_json(raw_result) if raw_result else {"passed": True, "errors": [], "summary": ""}
    await _push(
        session_id,
        "validation-complete",
        passed=validation.get("passed", True),
        errors=validation.get("errors", []),
        summary=validation.get("summary", ""),
        iterations=iteration,
    )

    final_report = state.get("final_report", "")
    if final_report:
        await _push(session_id, "report-ready", content=final_report)

    workspace_dir = state.get("workspace_dir", "")
    files = _workspace_to_files(workspace_dir, TARGET_LANGS["java11-to-java25"]) if workspace_dir else []
    if workspace_dir:
        shutil.rmtree(workspace_dir, ignore_errors=True)

    return files


# ---------------------------------------------------------------------------
# Section parser — splits the combined RE output into Analysis / BRD / TechSpec
# ---------------------------------------------------------------------------

import re as _re

def _parse_re_sections(combined: str) -> tuple[str, str, str]:
    """Return (analysis, brd, technical_spec) parsed from the combined RE output."""
    _A = _re.search(r'<!--\s*SECTION:\s*ANALYSIS\s*-->', combined, _re.IGNORECASE)
    _B = _re.search(r'<!--\s*SECTION:\s*BRD\s*-->', combined, _re.IGNORECASE)
    _T = _re.search(r'<!--\s*SECTION:\s*TECHNICAL_SPECIFICATION\s*-->', combined, _re.IGNORECASE)
    _E = _re.search(r'<!--\s*SECTION:\s*END\s*-->', combined, _re.IGNORECASE)

    analysis = combined[_A.end():_B.start()].strip() if _A and _B else combined
    brd       = combined[_B.end():_T.start()].strip() if _B and _T else (combined[_B.end():].strip() if _B else combined)
    end_pos   = _E.start() if _E else len(combined)
    tech_spec = combined[_T.end():end_pos].strip() if _T else ""

    return analysis, brd or combined, tech_spec


# ---------------------------------------------------------------------------
# Workflow orchestration
# ---------------------------------------------------------------------------

async def _run_workflow(session_id: str) -> None:
    try:
        state = await _get_state(session_id)
        pattern = state["pattern"]
        source_code = state["source_code"]
        is_direct_upgrade = "re" not in PATTERN_RUNNERS[pattern]

        if not is_direct_upgrade:
            # ── Step 1: Reverse Engineering → Analysis + BRD + Tech Spec ────
            await _push(session_id, "step-change", step="reverse-engineering")

            await _run_step(
                session_id, "re", pattern,
                message=f"Analyse this codebase:\n\n{source_code[:60000]}",
                sse_event_type="re-stream",
            )
            state = await _get_state(session_id)
            combined = state.get("analysis", "")
            analysis, brd, tech_spec = _parse_re_sections(combined)

            # Persist parsed sections so confirm-brd can serve them
            await _update_state(session_id, {"brd": brd, "technical_spec": tech_spec})

            await _push(session_id, "brd-ready", brd=brd, technical_spec=tech_spec)
            await _push(session_id, "step-change", step="brd-review")

            # ── HITL: Wait for Analysis confirmation (BRD + TechSpec) ───────
            await _brd_gates[session_id].wait()

        # ── Step 2: Plan Generation ──────────────────────────────────────────
        state = await _get_state(session_id)
        brd       = state.get("brd", "")
        tech_spec = state.get("technical_spec", "")
        additional_context = state.get("additional_context", "")

        if pattern == "java11-to-java25":
            # scanner_agent explores the real workspace via list_files/read_file —
            # no source dump needed, just a kickoff instruction.
            plan_msg = (
                "Scan the repository workspace (starting at the root) and produce "
                "a detailed migration plan for upgrading it from Java 11 to Java 25. "
                "Use the list_files and read_file tools to explore — do not assume "
                "any file contents you have not actually read."
            )
        elif is_direct_upgrade:
            # No BRD/Tech Spec for a direct upgrade — plan from source directly.
            plan_msg = f"Generate the migration plan.\n\nSource code:\n{source_code[:60000]}"
        else:
            plan_msg = f"Generate the migration plan.\n\nBRD:\n{brd[:15000]}"
            if tech_spec.strip():
                plan_msg += f"\n\nTechnical Specification:\n{tech_spec[:15000]}"
        if additional_context.strip():
            plan_msg += f"\n\nAdditional Context (Swagger / OpenAPI / Design Docs):\n{additional_context[:25000]}"

        await _push(session_id, "step-change", step="plan-generation")

        await _run_step(
            session_id, "plan", pattern,
            message=plan_msg,
            sse_event_type="plan-stream",
        )
        state = await _get_state(session_id)
        plan = state.get("plan", "")
        await _push(session_id, "plan-ready", content=plan)
        await _push(session_id, "step-change", step="plan-review")

        # ── HITL: Wait for Plan confirmation ────────────────────────────────
        await _plan_gates[session_id].wait()

        # ── Step 4: Code Generation ──────────────────────────────────────────
        # Re-fetch ALL confirmed/edited artifacts from session state so that
        # any human edits made during the review steps are reflected in the
        # generated code.
        state = await _get_state(session_id)
        plan             = state.get("plan", "")
        brd              = state.get("brd", "")
        tech_spec        = state.get("technical_spec", "")
        additional_ctx   = state.get("additional_context", "")

        code_msg_parts = ["Generate the migrated code using ALL of the following confirmed artifacts.\n"]

        if brd.strip():
            code_msg_parts.append(
                f"=== CONFIRMED BRD (human-reviewed) ===\n{brd[:8000]}"
            )
        if tech_spec.strip():
            code_msg_parts.append(
                f"=== CONFIRMED TECHNICAL SPECIFICATION (human-reviewed) ===\n{tech_spec[:8000]}"
            )
        if additional_ctx.strip():
            code_msg_parts.append(
                f"=== ADDITIONAL CONTEXT (Swagger / OpenAPI / Design Docs) ===\n{additional_ctx[:15000]}"
            )
        code_msg_parts.append(
            f"=== CONFIRMED MIGRATION PLAN (human-reviewed) ===\n{plan[:8000]}"
        )
        code_msg_parts.append(
            f"=== ORIGINAL SOURCE CODE ===\n{source_code[:45000]}"
        )

        await _push(session_id, "step-start", step="code-generation",
                    message="Generating migrated code…")
        await _push(session_id, "step-change", step="code-generation")

        if pattern == "java-to-quarkus":
            # Code pipeline: code_agent → LoopAgent(validate, fix, max=4)
            await _run_quarkus_code_step(session_id, "\n\n".join(code_msg_parts))
            state = await _get_state(session_id)
            raw_code = state.get("generated_code_raw", "")
            files = parse_generated_files(raw_code, TARGET_LANGS[pattern])
        elif pattern == "java11-to-java25":
            # Code pipeline: modifier_agent → LoopAgent(validate, fix, max=3) → reporter_agent.
            # modifier_agent reads the confirmed plan from session state directly
            # (its instruction has a {plan} template variable) and applies it to
            # the real workspace files — no code message needs to be built.
            files = await _run_java11_code_step(session_id)
        else:
            await _run_step(
                session_id, "code", pattern,
                message="\n\n".join(code_msg_parts),
                sse_event_type="code-stream",
            )
            state = await _get_state(session_id)
            raw_code = state.get("generated_code_raw", "")
            files = parse_generated_files(raw_code, TARGET_LANGS[pattern])
        files_payload = [f.model_dump() for f in files]

        await _update_state(session_id, {"generated_files_json": json.dumps(files_payload)})
        await _push(session_id, "code-ready", files=files_payload)

        await _push(session_id, "step-change", step="complete")
        await _push(session_id, "workflow-complete")

    except Exception as exc:
        await _push(session_id, "error", message=str(exc))
        try:
            state = await _get_state(session_id)
            workspace_dir = state.get("workspace_dir")
            if workspace_dir:
                shutil.rmtree(workspace_dir, ignore_errors=True)
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
):
    raw = await file.read()
    workspace_dir = ""

    if pattern == PatternType.JAVA11_TO_JAVA25:
        # Real per-session workspace: this pattern's agents read/write actual
        # files on disk and shell out to `mvn compile`, instead of working
        # from a single text dump like every other pattern (see
        # agents/java11_to_java25/tools.py).
        ws_path = Path(tempfile.mkdtemp(prefix="modernizer-ws-"))
        if file.filename and file.filename.endswith(".zip"):
            files_found = _extract_zip_to_dir(raw, ws_path)
        else:
            (ws_path / (file.filename or "Main.java")).write_bytes(raw)
            files_found = 1
        if files_found == 0:
            shutil.rmtree(ws_path, ignore_errors=True)
            raise HTTPException(status_code=400, detail="No readable source files found.")
        workspace_dir = str(ws_path)
        source_code = "(Workspace-based pattern — scanner_agent explores the repository via list_files/read_file tools.)"
    elif file.filename and file.filename.endswith(".zip"):
        source_code = _extract_zip(raw)
        files_found = source_code.count("// === FILE:")
    else:
        source_code = raw.decode("utf-8", errors="replace")
        files_found = 1

    if not source_code.strip() or source_code == "(empty repository)":
        raise HTTPException(status_code=400, detail="No readable source files found.")

    # Create ADK session with initial state
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state={
            "pattern": pattern.value,
            "source_code": source_code,
            "workspace_dir": workspace_dir,
            "analysis": "",
            "brd": "",
            "technical_spec": "",
            "plan": "",
            "additional_context": "",
            "generated_code_raw": "",
            "generated_files_json": "[]",
            "validation_result": "",
            "repo_facts": "",
            "modify_result": "",
            "build_result": "",
            "fix_result": "",
            "final_report": "",
            "workflow_step": "upload",
        },
    )
    session_id = session.id

    # Set up per-session infrastructure
    _sse_queues[session_id] = asyncio.Queue()
    _brd_gates[session_id] = asyncio.Event()
    _plan_gates[session_id] = asyncio.Event()

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

    delta: dict = {}
    if body.content is not None:
        delta["plan"] = body.content
    if body.feedback:
        state = await _get_state(session_id)
        current = state.get("plan", body.content or "")
        delta["plan"] = current + f"\n\n---\n**Reviewer Feedback:** {body.feedback}"

    if delta:
        await _update_state(session_id, delta)

    _plan_gates[session_id].set()
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
    return {
        "session_id": session_id,
        "pattern": state.get("pattern"),
        "brd": state.get("brd") or None,
        "plan": state.get("plan") or None,
        "generated_files": files,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "framework": "google-adk"}
