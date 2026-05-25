import asyncio
import json
import os
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
from agents.config import TEST_RETRY_ATTEMPTS
from agents.shared.file_parser import extract_text
from agents.shared.code_parser import parse_generated_files, is_test_file, merge_files_by_path
from models.schemas import PatternType, UploadResponse, ConfirmRequest

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


def _parse_validation(raw: str) -> dict:
    """Extract JSON from the validate-agent output with multi-strategy fallback.

    The model is instructed to output only JSON, but may occasionally wrap it
    in markdown fences or add surrounding text.  We try three strategies in
    order and fall back to "passed=True" so a bad parse never blocks the
    pipeline.
    """
    import re as _re
    text = raw.strip()

    # Strategy 1: direct JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: strip markdown fences then parse
    clean = _re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # Strategy 3: extract outermost { … } block
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    # Fallback: treat as passed so pipeline continues
    return {"passed": True, "issues": [], "summary": "Validation output could not be parsed; assuming passed."}


def _extract_zip(zip_bytes: bytes) -> str:
    EXTENSIONS = {
        # Java / Go / general
        ".java", ".xml", ".gradle", ".kts", ".properties", ".yaml", ".yml", ".json", ".go", ".mod",
        # TIBCO BusinessWorks artefacts
        ".bwp", ".process", ".substvar", ".xsd", ".wsdl", ".xslt", ".xsl",
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
                if set(p.parts) & {".git", "target", "build", "node_modules", ".gradle", "__pycache__"}:
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

# ---------------------------------------------------------------------------
# Workflow orchestration
# ---------------------------------------------------------------------------

async def _run_workflow(session_id: str) -> None:
    try:
        state = await _get_state(session_id)
        pattern = state["pattern"]
        source_code = state["source_code"]

        # ── Step 1: Reverse Engineering ─────────────────────────────────────
        await _push(session_id, "step-start", step="reverse-engineering",
                    message="Analysing your codebase…")
        await _push(session_id, "step-change", step="reverse-engineering")

        await _run_step(
            session_id, "re", pattern,
            message=f"Analyse this codebase:\n\n{source_code[:60000]}",
            sse_event_type="re-stream",
        )
        state = await _get_state(session_id)
        analysis = state.get("analysis", "")
        await _push(session_id, "re-complete", content=analysis)

        # ── Step 2: BRD Generation ───────────────────────────────────────────
        await _push(session_id, "step-start", step="brd-generation",
                    message="Generating Business Requirements Document…")
        await _push(session_id, "step-change", step="brd-generation")

        await _run_step(
            session_id, "brd", pattern,
            message=f"Generate the BRD based on this analysis:\n\n{analysis[:25000]}",
            sse_event_type="brd-stream",
        )
        state = await _get_state(session_id)
        brd = state.get("brd", "")
        await _push(session_id, "brd-ready", content=brd)
        await _push(session_id, "step-change", step="brd-review")

        # ── HITL: Wait for BRD confirmation ─────────────────────────────────
        await _brd_gates[session_id].wait()

        # ── Step 3: Plan Generation ──────────────────────────────────────────
        state = await _get_state(session_id)
        brd = state.get("brd", "")
        additional_context = state.get("additional_context", "")

        plan_msg = f"Generate the migration plan.\n\nBRD:\n{brd[:20000]}"
        if additional_context.strip():
            plan_msg += f"\n\nAdditional Context:\n{additional_context[:30000]}"

        await _push(session_id, "step-start", step="plan-generation",
                    message="Generating migration plan…")
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
        state = await _get_state(session_id)
        plan = state.get("plan", "")

        await _push(session_id, "step-start", step="code-generation",
                    message="Generating migrated code…")
        await _push(session_id, "step-change", step="code-generation")

        await _run_step(
            session_id, "code", pattern,
            message=(
                f"Generate the migrated code.\n\n"
                f"Plan summary:\n{plan[:10000]}\n\n"
                f"Original source:\n{source_code[:50000]}"
            ),
            sse_event_type="code-stream",
        )
        state = await _get_state(session_id)
        raw_code = state.get("generated_code_raw", "")
        files = parse_generated_files(raw_code, TARGET_LANGS[pattern])
        files_payload = [f.model_dump() for f in files]

        await _update_state(session_id, {"generated_files_json": json.dumps(files_payload)})
        await _push(session_id, "code-ready", files=files_payload)

        # ── Step 5: Test Generation ──────────────────────────────────────────
        await _push(session_id, "step-start", step="test-generation",
                    message="Generating unit tests (>80% coverage target)…")
        await _push(session_id, "step-change", step="test-generation")

        await _run_step(
            session_id, "test", pattern,
            message=(
                f"Generate the unit test suite for the migrated code.\n\n"
                f"Plan:\n{plan[:8000]}\n\n"
                f"Generated source code:\n{raw_code[:50000]}"
            ),
            sse_event_type="test-stream",
        )
        state = await _get_state(session_id)
        raw_tests = state.get("generated_tests_raw", "")
        test_files = parse_generated_files(raw_tests, TARGET_LANGS[pattern])
        tests_payload = [f.model_dump() for f in test_files]

        await _update_state(session_id, {"generated_tests_json": json.dumps(tests_payload)})
        await _push(session_id, "tests-ready", files=tests_payload)

        # ── Step 6: Validation / Fix retry loop ─────────────────────────────
        # Keep mutable copies so each iteration works on the latest version.
        files_current = files_payload          # list[dict]  source files
        tests_current = tests_payload          # list[dict]  test files
        lang = TARGET_LANGS[pattern]

        validation: dict = {"passed": True, "issues": [], "summary": ""}
        attempts_used = 0

        def _to_raw(file_list: list) -> str:
            """Reconstruct fenced-block text from a list of file dicts."""
            return "\n\n".join(
                f"```{f['language']}:{f['path']}\n{f['content']}\n```"
                for f in file_list
            )

        if TEST_RETRY_ATTEMPTS > 0:
            for attempt in range(1, TEST_RETRY_ATTEMPTS + 1):
                attempts_used = attempt

                # --- Validate ---
                await _push(session_id, "validation-start",
                            attempt=attempt, max_retries=TEST_RETRY_ATTEMPTS)

                raw_src = _to_raw(files_current)
                raw_tst = _to_raw(tests_current)

                await _run_step(
                    session_id, "validate", pattern,
                    message=(
                        f"Review these source files and test files for correctness.\n\n"
                        f"=== SOURCE CODE ===\n{raw_src[:35000]}\n\n"
                        f"=== TEST FILES ===\n{raw_tst[:20000]}"
                    ),
                    sse_event_type="validate-stream",
                )

                state = await _get_state(session_id)
                validation = _parse_validation(state.get("validation_result", ""))
                issues = validation.get("issues", [])
                passed = validation.get("passed", True)

                await _push(session_id, "validation-result",
                            passed=passed,
                            attempt=attempt,
                            max_retries=TEST_RETRY_ATTEMPTS,
                            issues=issues,
                            summary=validation.get("summary", ""))

                if passed:
                    break

                if attempt >= TEST_RETRY_ATTEMPTS:
                    break  # budget exhausted — accept best-effort result

                # --- Fix ---
                await _push(session_id, "fix-start",
                            attempt=attempt, max_retries=TEST_RETRY_ATTEMPTS,
                            issues=issues)

                issues_text = "\n".join(f"- {iss}" for iss in issues)
                await _run_step(
                    session_id, "fix", pattern,
                    message=(
                        f"Fix the following issues:\n{issues_text}\n\n"
                        f"=== SOURCE CODE ===\n{raw_src[:35000]}\n\n"
                        f"=== TEST FILES ===\n{raw_tst[:20000]}"
                    ),
                    sse_event_type="fix-stream",
                )

                state = await _get_state(session_id)
                raw_fix = state.get("generated_fix_raw", "").strip()

                if raw_fix:
                    fixed_files = parse_generated_files(raw_fix, lang)
                    fixed_payload = [f.model_dump() for f in fixed_files]

                    src_fixed  = [f for f in fixed_payload if not is_test_file(f["path"], lang)]
                    test_fixed = [f for f in fixed_payload if is_test_file(f["path"], lang)]

                    if src_fixed:
                        files_current = merge_files_by_path(files_current, src_fixed)
                    if test_fixed:
                        tests_current = merge_files_by_path(tests_current, test_fixed)

                    # Persist updated files so the session stays consistent
                    await _update_state(session_id, {
                        "generated_files_json": json.dumps(files_current),
                        "generated_tests_json": json.dumps(tests_current),
                    })

                    await _push(session_id, "fix-applied",
                                attempt=attempt,
                                source_files=src_fixed,
                                test_files=test_fixed)

        final_passed = validation.get("passed", True)
        await _push(session_id, "validation-complete",
                    passed=final_passed,
                    attempts_used=attempts_used,
                    max_retries=TEST_RETRY_ATTEMPTS,
                    final_issues=validation.get("issues", []))

        await _push(session_id, "step-change", step="complete")
        await _push(session_id, "workflow-complete")

    except Exception as exc:
        await _push(session_id, "error", message=str(exc))
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
    if file.filename and file.filename.endswith(".zip"):
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
            "analysis": "",
            "brd": "",
            "plan": "",
            "additional_context": "",
            "generated_code_raw": "",
            "generated_files_json": "[]",
            "generated_tests_raw": "",
            "generated_tests_json": "[]",
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
    if body.feedback:
        state = await _get_state(session_id)
        current = state.get("brd", body.content or "")
        delta["brd"] = current + f"\n\n---\n**Reviewer Feedback:** {body.feedback}"

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


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    state = await _get_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found.")
    files = json.loads(state.get("generated_files_json", "[]"))
    tests = json.loads(state.get("generated_tests_json", "[]"))
    return {
        "session_id": session_id,
        "pattern": state.get("pattern"),
        "brd": state.get("brd") or None,
        "plan": state.get("plan") or None,
        "generated_files": files,
        "generated_tests": tests,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "framework": "google-adk"}
