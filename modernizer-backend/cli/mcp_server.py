"""
MCP server: the Stella Modernizer's deterministic tools and pipeline, for Gemini CLI.

Run by the Gemini CLI extension (gemini-cli/gemini-extension.json, through
gemini-cli/launch.mjs) over stdio. Tools act on the repository Gemini CLI has
open (MODERNIZER_WORKSPACE, set by the extension), or on `workspace` when given.

Three groups of tools:

- **pipeline** — start_run, next_step, save_output, complete_step, confirm,
  refine, run_status, export_docx: the state machine of cli/pipeline.py and
  cli/discovery.py;
- **workspace** (ws_*) — the subagents' write, build and check tools: the same
  functions as the ADK agents' tools (agents/<pattern>/tools.py), so the Java 11
  scope fence, the approved-versions gate, the build classification and the
  change audit behave exactly as in the web pipeline;
- **curator** — the skill curator's skill-file tools, restricted to the
  pattern's own skills.

Usage outside Gemini CLI: `python -m cli.mcp_server` (stdio).
"""
from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

try:   # the same .env the web backend reads (MIGRATION_JAVA_HOME, MAVEN_SETTINGS, limits, ...)
    from dotenv import load_dotenv
    load_dotenv(_BACKEND / ".env")
    # Settings that survive an extension update (an installed copy is replaced on update):
    # MODERNIZER_HOME/.env, default ~/.modernizer/.env. The checkout's .env wins where both set a key.
    load_dotenv(Path(os.getenv("MODERNIZER_HOME") or Path.home() / ".modernizer") / ".env")
except ImportError:
    pass

try:                                                          # mcp 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:                                           # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

import anyio  # noqa: E402 — a dependency of mcp

from agents import config  # noqa: E402
from agents.shared import progress  # noqa: E402
from cli import docs as cli_docs  # noqa: E402
from cli import pipeline, patterns as P  # noqa: E402
from cli.runstate import RUN_DIR, Run, RunError, resolve_workspace  # noqa: E402

INSTRUCTIONS = """\
Stella Modernizer: AI-driven application modernization (Java 8 -> 25 / 11, Solr 4 -> 9, Oracle 19c -> 23ai,
TIBCO EMS -> Pub/Sub, JSP -> React + BFF) and stack discovery, run as a pipeline with two human gates.
Drive it with next_step: it runs every deterministic step itself and returns the next step that needs a
subagent (call that subagent with the returned query, then complete_step) or a person (ask them, then
confirm / refine). Never edit `.modernizer/` files by hand except where a review gate invites it."""

server = _Server("modernizer", instructions=INSTRUCTIONS)


def _safe(fn, *args, **kwargs) -> str:
    """Run a tool body with prints sent to stderr (stdout is the MCP channel) and
    every expected failure returned as an `ERROR:` string the agent can read."""
    with contextlib.redirect_stdout(sys.stderr):
        try:
            return fn(*args, **kwargs)
        except (RunError, KeyError, ValueError) as exc:
            return f"ERROR: {exc.args[0] if exc.args else exc}"


# Gemini CLI runs the tool calls of one turn at the same time — a parallel group's subagents save
# and complete their steps concurrently. Every tool that reads or writes the run state
# (.modernizer/run.json) holds this lock, so no update is lost; builds (ws_run_command,
# ws_validate) do not, since they can run for many minutes and only read the run.
_STATE_LOCK = threading.Lock()


def _locked(fn, *args, **kwargs) -> str:
    with _STATE_LOCK:
        return _safe(fn, *args, **kwargs)


async def _run(fn, *args, locked: bool = True, **kwargs) -> str:
    """Tools can run builds for many minutes: off the event loop, so the server stays responsive."""
    return await anyio.to_thread.run_sync(lambda: (_locked if locked else _safe)(fn, *args, **kwargs))


def _load(workspace: str = "") -> Run:
    return Run.load(workspace or None)


def _format_step(step: dict, log: list[str]) -> str:
    lines = []
    if log:
        lines += ["## Done since the last step (no model)", *[f"- {entry}" for entry in log], ""]
    lines.append(f"## Next: {step.get('title', step['id'])}")
    lines.append(f"- step_id: `{step['id']}`")
    lines.append(f"- kind: {step['kind']}")
    if step["kind"] == "subagent":
        lines += [f"- subagent: `{step['subagent']}`", "",
                  f"Call the `{step['subagent']}` subagent with exactly this query, then call `complete_step` "
                  f"with step_id `{step['id']}`:", "", "<query>", step["query"], "</query>"]
    elif step["kind"] == "parallel":
        from cli.discovery import pending_ids
        open_ids = set(pending_ids(step))
        members = [m for m in step["members"] if m["id"] in open_ids]
        lines += ["", f"These {len(members)} batches are independent of each other. Call all {len(members)} "
                  "subagents **in one turn** — one tool call each, in the same response, so Gemini CLI runs them at "
                  "the same time — each with exactly its query. When they have all returned, call `complete_step` "
                  "once for each step_id below (any order), then `next_step`. If one fails, run that one again on "
                  "its own; the others stay done.", ""]
        for n, m in enumerate(members, 1):
            lines += [f"### {n}. step_id `{m['id']}` — subagent `{m['subagent']}` — {m['title']}", "",
                      "<query>", m["query"], "</query>", ""]
    else:
        lines += ["", step.get("text", "")]
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# Pipeline
# ═════════════════════════════════════════════════════════════════════════════

@server.tool()
async def list_patterns() -> str:
    """List the modernization patterns this server can run, with what each changes."""
    rows = [f"- `{p.id}` — {p.label}" for p in P.PATTERNS.values()]
    rows.append(f"- `{P.STACK_DISCOVERY}` — Discover & reverse-engineer my stack (documents only; changes nothing)")
    return "\n".join(rows) + ("\n\njava-8-to-25 also takes migration_strategy=bigbang|incremental, "
                              "springboot_upgrade and junit_upgrade.")


@server.tool()
async def start_run(pattern: str, workspace: str = "", migration_strategy: str = "bigbang",
                    springboot_upgrade: bool = False, junit_upgrade: bool = False,
                    context_files: list[str] | None = None, restart: bool = False,
                    requirements: str = "") -> str:
    """Start a modernization run on the repository: snapshot it as the baseline, build the
    dependency graph, detect companion migrations (or, for stack-discovery, the stacks).

    Args:
        pattern: java-8-to-25, java-8-to-11, solr-4-to-9, oracle-19c-to-23ai, tibco-ems-to-pubsub,
            jsp-to-react-bff or stack-discovery.
        workspace: Repository root; defaults to the Gemini CLI workspace.
        migration_strategy: java-8-to-25 only — "bigbang" (one pass) or "incremental" (staged).
        springboot_upgrade: java-8-to-25 only — also move to Spring Boot 4 / executable JAR.
        junit_upgrade: java-8-to-25 only — also upgrade JUnit.
        context_files: Swagger / OpenAPI / design documents (paths) for the planner.
        restart: Discard an existing run in this repository and start over.
        requirements: What the person asked for, in their own words and complete (e.g. "Migrate the backend
            to Java 11, keep the JSP WARs as they are; Spring and Hibernate move to compatible versions").
            The planner, reviewer and reporter get it as binding text. Empty when they asked for nothing
            beyond the pattern.
    """
    def body():
        run = pipeline.start(resolve_workspace(workspace or None), pattern, migration_strategy,
                             springboot_upgrade, junit_upgrade, context_files, restart, requirements)
        return pipeline.summary(run) + "\n\nRun started. Call `next_step` to continue."
    return await _run(body)


@server.tool()
async def run_status(workspace: str = "") -> str:
    """Show the current run: pattern, phase, the step it waits on, and its documents — and, while
    `next_step` is working in the background, what it is doing."""
    def body():
        run = _load(workspace)
        docs = sorted(p for p in (run.dir / "docs").rglob("*.md")) if (run.dir / "docs").is_dir() else []
        results = sorted(p for p in (run.dir / "results").rglob("*") if p.is_file()) \
            if (run.dir / "results").is_dir() else []
        lines = [pipeline.summary(run)]
        if docs:
            lines += ["", "## Documents", *[f"- `{run.rel(p)}`" for p in docs]]
        if results:
            lines += ["", "## Results", *[f"- `{run.rel(p)}`" for p in results]]
        return "\n".join(lines)
    try:
        worker = _WORKERS.get(str(resolve_workspace(workspace or None)))
    except RunError:
        worker = None
    if worker is not None and not worker.done.is_set():
        # The run is busy (and holds the state lock): read its saved state as it is, and say what is running.
        return await _run(lambda: "## In progress\n\n" + worker.tracker.report() + "\n\n" + body(), locked=False)
    return await _run(body)


@dataclass
class _Worker:
    """One `next_step` running in the background, with what it is doing (agents/shared/progress.py)."""
    tracker: progress.Tracker
    done: threading.Event = field(default_factory=threading.Event)
    result: str = ""
    finished_state_mtime: float = 0.0


_WORKERS: dict[str, _Worker] = {}          # workspace -> its running (or finished, not yet collected) next_step
_WORKERS_LOCK = threading.Lock()


def _state_mtime(key: str) -> float:
    try:
        return (Path(key) / RUN_DIR / "run.json").stat().st_mtime
    except OSError:
        return 0.0


def _start_worker(key: str, workspace: str) -> _Worker:
    worker = _Worker(progress.Tracker(title="The run is working through its deterministic steps"))

    def body():
        step, log = pipeline.next_step(_load(workspace))
        return _format_step(step, log)

    def work():
        previous = progress.activate(worker.tracker)
        try:
            worker.result = _locked(body)
        except Exception as exc:                                  # noqa: BLE001 — returned, not lost in a thread
            worker.result = f"ERROR: next_step failed: {type(exc).__name__}: {exc}"
        finally:
            progress.activate(previous)
            worker.finished_state_mtime = _state_mtime(key)
            worker.done.set()

    threading.Thread(target=work, name=f"next_step {key}", daemon=True).start()
    return worker


def _still_working(worker: _Worker, poll: int = 0) -> str:
    # Each wait call carries a new `poll` number: Gemini CLI halts a request that repeats an identical tool
    # call many times ("potential loop"), and a build can outlast many waits.
    again = f"`next_step` again with `poll={poll + 1}`"
    return "\n".join([
        "## Still working — no step for you yet", "",
        worker.tracker.report(), "",
        "The run is doing this itself: nothing is needed from you or the user. Tell the user in one line what it "
        "is doing now (the **Now:** line), then call " + again + " straight away (same workspace; only `poll` changes) — it waits up to "
        f"{config.PROGRESS_REPORT_SECONDS}s and returns the next step or a newer progress report. Calling it again "
        "never restarts the work. Do not call other modernizer tools meanwhile.",
    ])


@server.tool()
async def next_step(workspace: str = "", poll: int = 0) -> str:
    """Advance the run: performs every deterministic step it reaches (inventories, preflight, plan
    checks, mechanical rewrites, computed sections, the final diff) and returns the next step that
    needs a subagent (with the exact query to give it) or a person (what to ask). Long work runs in the
    background: until it finishes, this answers every PROGRESS_REPORT_SECONDS with what it is doing.

    Args:
        poll: Leave 0, except when the previous answer said "Still working": pass the `poll` number it names
            (it counts up), so repeated waits are not mistaken for a loop. Calling again never restarts the work."""
    try:
        key = str(resolve_workspace(workspace or None))
    except RunError as exc:
        return f"ERROR: {exc.args[0] if exc.args else exc}"
    with _WORKERS_LOCK:
        worker = _WORKERS.get(key)
        if worker is not None and worker.done.is_set() and _state_mtime(key) != worker.finished_state_mtime:
            worker = None                       # the run moved on since that answer was computed: it is stale
        fresh = worker is None
        if fresh:
            worker = _WORKERS[key] = _start_worker(key, workspace)
    wait = config.PROGRESS_FIRST_REPORT_SECONDS if fresh else config.PROGRESS_REPORT_SECONDS
    if await anyio.to_thread.run_sync(worker.done.wait, wait):
        with _WORKERS_LOCK:
            if _WORKERS.get(key) is worker:
                del _WORKERS[key]
        return worker.result
    return _still_working(worker, max(0, int(poll or 0)))


@server.tool()
async def save_output(step_id: str, content: str, workspace: str = "") -> str:
    """Save a subagent's complete output for the step it was given. This is the only output the
    pipeline reads — call it once, at the end, with the whole document/result.

    Args:
        step_id: The step_id from the brief (e.g. `plan-solr-4-to-9`).
        content: The complete output: the document, the JSON verdict, the summary.
    """
    def body():
        run = _load(workspace)
        from cli.discovery import pending_ids
        waiting = pending_ids(run.state.get("current_step") or {})
        if step_id not in waiting:
            raise RunError(f"The run is waiting on {', '.join(f'`{w}`' for w in waiting) or 'nothing'}, "
                           f"not `{step_id}`.")
        text = content if isinstance(content, str) else __import__("json").dumps(content, ensure_ascii=False)
        path = run.out_path(step_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return f"Saved {len(text):,} characters for `{step_id}`."
    return await _run(body)


@server.tool()
async def complete_step(step_id: str, workspace: str = "") -> str:
    """Finish a subagent step after the subagent called save_output: the pipeline processes the
    output (splits the analysis, checks the plan, routes a failed build to the fixer, ...).

    Args:
        step_id: The step_id next_step returned.
    """
    return await _run(lambda: pipeline.complete_step(_load(workspace), step_id)
                      + "\n\nCall `next_step` to continue.")


@server.tool()
async def confirm(gate: str, selection: list[str] | None = None, documents: list[str] | None = None,
                  workspace: str = "") -> str:
    """Record a person's decision at a gate. Only call this with the user's explicit answer.

    Args:
        gate: `companions` (which companion migrations to include), `analysis` (the analysis is
            confirmed), `plan` (the plan is approved — code changes start), `stacks` (stack-discovery:
            which stacks to document), `strategy` (stack-discovery: how to reverse engineer — one id
            from the offered options, before any code is read) or `documents` (stack-discovery: the
            deliverables are accepted).
        selection: For `companions` / `stacks`: the chosen ids (empty list = none). For `strategy`:
            [the strategy id] — layered-trace, api-first, data-first or stack-by-stack.
        documents: For `stacks`: brd, technical_spec, test_inventory, setup, openapi, tech_debt, ui_screens.
    """
    return await _run(lambda: pipeline.confirm(_load(workspace), gate, selection, documents)
                      + "\n\nCall `next_step` to continue.")


@server.tool()
async def refine(gate: str, feedback: str, workspace: str = "") -> str:
    """Send a reviewed document back with the user's feedback instead of approving it.

    Args:
        gate: `analysis` or `plan`; for stack-discovery `brd`, `technical_spec`, `test_inventory` or `setup`.
        feedback: What should change, in the user's words.
    """
    return await _run(lambda: pipeline.refine(_load(workspace), gate, feedback))


@server.tool()
async def export_docx(workspace: str = "") -> str:
    """Write Word (.docx) copies of the run's documents (BRD, Technical Specification, Test
    Inventory, plan, reports) to `.modernizer/export/`."""
    return await _run(lambda: cli_docs.export(_load(workspace)))


# ═════════════════════════════════════════════════════════════════════════════
# Workspace tools for the subagents
# ═════════════════════════════════════════════════════════════════════════════

def _pattern_tools(run: Run):
    pattern = run.state.get("current_pattern") or run.state["pattern"]
    if pattern == P.STACK_DISCOVERY:
        raise RunError("Stack discovery is read-only: it has no write or build tools.")
    return pattern, P.get(pattern).tools()


def _guard_path(path: str) -> None:
    parts = Path(path.replace("\\", "/")).parts
    if parts and parts[0] == RUN_DIR:
        raise RunError(f"`{RUN_DIR}/` holds the run's state — save your output with save_output instead.")


def _require_code_phase(run: Run) -> None:
    if not run.state.get("plan_approved"):
        raise RunError("No plan is approved yet — the repository is not changed before the human approves the plan.")


@server.tool()
async def ws_write_file(path: str, content: str, allow_full_overwrite: bool = False, workspace: str = "") -> str:
    """Write a new file, or replace an existing file's entire content, in the repository. For an
    edit to an existing file prefer ws_replace_in_file. Overwriting a file larger than one read
    window is refused unless allow_full_overwrite=True after reading all of it. In a Java 8 -> 11
    run, only `.java` sources and build files may be written (the scope fence).

    Args:
        path: File path relative to the repository root.
        content: The complete new content of the file.
        allow_full_overwrite: Confirm a deliberate full rewrite of a large file you read in full.
    """
    def body():
        run = _load(workspace)
        _require_code_phase(run)
        _guard_path(path)
        _, tools = _pattern_tools(run)
        return tools.write_file(run.tool_context(), path, content, allow_full_overwrite)
    return await _run(body)


@server.tool()
async def ws_delete_file(path: str, workspace: str = "") -> str:
    """Delete one file the migration makes obsolete (a `web.xml` replaced by Java config, a Spring
    XML context, a JSP converted to Thymeleaf). One file per call, never a directory. Only the
    patterns whose skills remove files offer it (Java 8 -> 25).

    Args:
        path: File path relative to the repository root.
    """
    def body():
        run = _load(workspace)
        _require_code_phase(run)
        _guard_path(path)
        _, tools = _pattern_tools(run)
        if not hasattr(tools, "delete_file"):
            return "ERROR: this migration does not delete files — leave the file in place and say why in your output."
        return tools.delete_file(run.tool_context(), path)
    return await _run(body)


@server.tool()
async def ws_replace_in_file(path: str, old_text: str, new_text: str, expected_count: int = 1,
                             workspace: str = "") -> str:
    """Replace an exact snippet in one repository file, leaving everything else untouched — the
    preferred way to edit. In a Java 8 -> 11 run the scope fence refuses frozen files and edits
    that break its invariants.

    Args:
        path: File path relative to the repository root.
        old_text: The exact text to replace, copied verbatim including indentation; unique enough.
        new_text: The replacement ("" deletes old_text).
        expected_count: How many occurrences you expect; refused unless exactly this many.
    """
    def body():
        run = _load(workspace)
        _require_code_phase(run)
        _guard_path(path)
        _, tools = _pattern_tools(run)
        return tools.replace_in_file(run.tool_context(), path, old_text, new_text, expected_count)
    return await _run(body)


@server.tool()
async def ws_run_command(command: str, subdir: str = ".", workspace: str = "") -> str:
    """Run one build command in the repository (or a subdirectory). Only the pattern's toolchain is
    allowed (mvn/gradle/java/javac; npm/npx/node/tsc for JSP -> React). No shell: one command per
    call, no `&&`, `|` or `;`. Java 8 -> 11 builds run on MIGRATION_JAVA_HOME with MAVEN_SETTINGS.

    Args:
        command: The command line, e.g. "mvn -q -DskipTests test-compile".
        subdir: Directory relative to the repository root (e.g. "backend", "frontend").
    """
    def body():
        run = _load(workspace)
        pattern, tools = _pattern_tools(run)
        if not hasattr(tools, "run_command"):
            # A companion (Oracle, Solr) builds with the run's Java build tool: its pass changes dependencies
            # and client code that only a real build verifies.
            borrowed = pipeline.build_pattern(run, pattern)
            if not borrowed:
                return "ERROR: this pattern has no build toolchain — call ws_validate for its static check."
            tools = P.get(borrowed).tools()
        return tools.run_command(run.tool_context(), command, subdir)
    return await _run(body, locked=False)


@server.tool()
async def ws_validate(workspace: str = "") -> str:
    """Run the pattern's deterministic validation and return its report: Java 8 -> 11 builds with
    `mvn clean package` on the migration JDK and classifies every problem (COMPILE / TEST / BUILD /
    DEPENDENCY / ENVIRONMENT); Solr, Oracle and TIBCO run their static config/SQL/mapping checks.
    Read the report and decide pass/fail yourself."""
    def body():
        run = _load(workspace)
        pattern, tools = _pattern_tools(run)
        name = P.get(pattern).validator
        if not name:
            return (f"No static validator for {pattern} — build with ws_run_command and read the output. "
                    + P.get(pattern).validator_note)
        ctx = run.tool_context()
        report = getattr(tools, name)(ctx)
        run.absorb(ctx, "java11_build_passed")
        return report
    return await _run(body, locked=False)


@server.tool()
async def ws_check_invariants(workspace: str = "") -> str:
    """Java 8 -> 11 only: check the workspace against the scope fence, comparing with the baseline
    (frozen files byte-identical, packaging/finalName/WildFly plugins unchanged, Java level exactly
    11, no Spring Boot, no jakarta.* imports). Ends with OVERALL: PASS or OVERALL: FAIL."""
    def body():
        run = _load(workspace)
        pattern, tools = _pattern_tools(run)
        if not hasattr(tools, "check_java11_invariants"):
            return f"No scope fence for {pattern}."
        return tools.check_java11_invariants(run.tool_context())
    return await _run(body)


@server.tool()
async def ws_signal_build_success(workspace: str = "") -> str:
    """Call ONLY after validation succeeded (exit code 0 / no errors, and for Java 11 the invariants
    PASS). Records the pass. Refused — and validation has then FAILED — while a version this
    migration set contradicts the approved-versions list, or a Java 11 fence invariant fails."""
    def body():
        run = _load(workspace)
        current = run.state.get("current_step") or {}
        if current.get("handler") != "validate":
            raise RunError("Only the validator signals build success, during a validation step.")
        _, tools = _pattern_tools(run)
        result = tools.signal_build_success(run.tool_context())
        if not result.startswith("ERROR"):
            run.state["build_signalled"] = True
            run.save()
            return "Build success recorded. Save your JSON result with save_output."
        return result
    return await _run(body)


@server.tool()
async def ws_audit_changes(workspace: str = "") -> str:
    """Audit what this run changed, before reviewing any file: compares the baseline with the
    migrated repository and reports, with the matched line as evidence, changes with no migration
    signal (scope creep), legacy APIs re-introduced (regressions), and untouched files that still
    match a legacy marker (coverage gaps). Call this FIRST."""
    from agents.shared import change_audit

    def body():
        run = _load(workspace)
        return change_audit.audit_migration_changes(run.tool_context())
    return await _run(body)


@server.tool()
async def ws_compare_plan_to_changes(workspace: str = "") -> str:
    """Check what changed against the approved plan's File Change Manifest: promised files left
    untouched, files changed without approval, files the plan said to leave alone that changed, and
    manifest entries matching no file. Call after ws_audit_changes."""
    from agents.shared import plan_coverage

    def body():
        run = _load(workspace)
        return plan_coverage.compare_plan_to_actual_changes(run.tool_context())
    return await _run(body)


# ═════════════════════════════════════════════════════════════════════════════
# Skill curator
# ═════════════════════════════════════════════════════════════════════════════

def _curator_tools(run: Run):
    from agents.shared.skill_curator_tools import make_skill_curator_tools
    allowed = run.state.get("curator_skills")
    if not allowed:
        raise RunError("Skill files are only written during the run's skill-curation step.")
    return make_skill_curator_tools(allowed)


@server.tool()
async def curator_list_skill_files(skill_name: str, workspace: str = "") -> str:
    """List the files of one skill this run's curator may edit (SKILL.md and references/)."""
    return await _run(lambda: _curator_tools(_load(workspace))[0](skill_name))


@server.tool()
async def curator_read_skill_file(skill_name: str, relative_path: str, workspace: str = "") -> str:
    """Read one file of a skill this run's curator may edit, e.g. relative_path="SKILL.md"."""
    return await _run(lambda: _curator_tools(_load(workspace))[1](skill_name, relative_path))


@server.tool()
async def curator_write_skill_file(skill_name: str, relative_path: str, content: str, workspace: str = "") -> str:
    """Write one file of a skill this run's curator may edit. Rejected for any other skill."""
    return await _run(lambda: _curator_tools(_load(workspace))[2](skill_name, relative_path, content))


def main() -> None:
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    server.run()


if __name__ == "__main__":
    main()
