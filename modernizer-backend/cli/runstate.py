"""
A Gemini CLI run's state, kept on disk in the repository's `.modernizer/` folder.

The ADK pipeline keeps a session's state in memory (or a database) and the
workspace in a temporary copy of the upload. A CLI run works on the repository
the user opened, in place, so everything it needs to resume lives next to it:

    .modernizer/
      run.json                      the state machine (pattern, step, gates, progress)
      docs/<pattern>/analysis.md    the four-section analysis, then its parts:
      docs/<pattern>/brd.md           BRD, Technical Specification, Test Inventory
      docs/<pattern>/technical_spec.md
      docs/<pattern>/test_inventory.md
      docs/<pattern>/plan.md        the plan the human approves
      out/<step>.md                 what each subagent saved (save_output)
      results/                      build results, review, report, changes

The baseline — the repository exactly as it was when the run started — is a
copy outside the repository (MODERNIZER_HOME, default ~/.modernizer), because
the scope fence, the change audit, plan conformance and the final diff all
compare against it, and a copy inside the repository would be scanned as part
of it. `.modernizer` itself is excluded from every scan (dependency_graph.EXCLUDED_DIRS).
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from agents.shared.dependency_graph import EXCLUDED_DIRS

RUN_DIR = ".modernizer"
STATE_FILE = "run.json"
DOC_NAMES = ("analysis", "brd", "technical_spec", "test_inventory", "plan")


class RunError(RuntimeError):
    """A request the run's current state cannot satisfy; the message says what to do instead."""


def modernizer_home() -> Path:
    return Path(os.getenv("MODERNIZER_HOME") or Path.home() / ".modernizer")


def resolve_workspace(workspace: str | None = None) -> Path:
    """The repository a tool call acts on: the argument, else MODERNIZER_WORKSPACE
    (set by the Gemini CLI extension to the CLI's workspace), else the cwd."""
    raw = workspace or os.getenv("MODERNIZER_WORKSPACE") or os.getcwd()
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise RunError(f"Workspace '{raw}' is not a directory.")
    return root


def snapshot(workspace: Path, run_id: str) -> Path:
    """Copy the repository to the baseline folder, leaving out what every scan
    leaves out (build output, dependencies, VCS metadata, this run's folder)."""
    target = modernizer_home() / "baselines" / run_id
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(workspace, target, symlinks=True,
                    ignore=lambda _d, names: [n for n in names if n in EXCLUDED_DIRS])
    return target


def _damaged(path: Path, why: str) -> str:
    return (f"The run state `{path}` is damaged: {why}. Nothing was changed by this call. If you edited it by hand, "
            "undo that; otherwise start over with /modernize:start (restart=true) — the repository itself is "
            "untouched until a plan is approved, and the baseline copy of the original is in the run's folder.")


class Run:
    """One run's state: `run.json` plus the documents and outputs beside it."""

    def __init__(self, workspace: Path, state: dict):
        self.workspace = workspace
        self.state = state

    # ── lifecycle ─────────────────────────────────────────────────────────────
    @property
    def dir(self) -> Path:
        return self.workspace / RUN_DIR

    @classmethod
    def exists(cls, workspace: Path) -> bool:
        return (workspace / RUN_DIR / STATE_FILE).is_file()

    @classmethod
    def load(cls, workspace: str | Path | None = None) -> "Run":
        root = resolve_workspace(str(workspace) if workspace else None)
        path = root / RUN_DIR / STATE_FILE
        if not path.is_file():
            raise RunError(
                f"No modernizer run in {root}. Start one with /modernize:start <pattern> "
                "(or the start_run tool).")
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise RunError(_damaged(path, f"it cannot be read as JSON ({type(exc).__name__}: {exc})")) from None
        if not isinstance(state, dict) or not all(isinstance(state.get(k), str) and state[k]
                                                   for k in ("run_id", "pattern")):
            raise RunError(_damaged(path, "it is not a run state (no run_id / pattern)"))
        if Path(state.get("workspace_dir", "")).resolve() != root:
            # The repository was moved or cloned: the run follows it.
            state["workspace_dir"] = str(root)
        return cls(root, state)

    @classmethod
    def create(cls, workspace: Path, pattern: str, **options) -> "Run":
        run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        # Not git-ignored on purpose: Gemini CLI's read_file refuses ignored files,
        # and the subagents read the confirmed documents and the plan from here.
        (workspace / RUN_DIR).mkdir(exist_ok=True)
        baseline = snapshot(workspace, run_id)
        state = {
            "run_id": run_id,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pattern": pattern,
            "workspace_dir": str(workspace),
            "baseline_dir": str(baseline),
            **options,
        }
        run = cls(workspace, state)
        run.save()
        return run

    def save(self) -> None:
        self.dir.mkdir(exist_ok=True)
        tmp = self.dir / (STATE_FILE + ".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / STATE_FILE)

    # ── documents and outputs ────────────────────────────────────────────────
    def doc_path(self, name: str, pattern: str | None = None) -> Path:
        return self.dir / "docs" / (pattern or self.state["pattern"]) / f"{name}.md"

    def read_doc(self, name: str, pattern: str | None = None) -> str:
        path = self.doc_path(name, pattern)
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def write_doc(self, name: str, text: str, pattern: str | None = None) -> Path:
        path = self.doc_path(name, pattern)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def out_path(self, step_id: str) -> Path:
        return self.dir / "out" / f"{step_id}.md"

    def read_out(self, step_id: str) -> str:
        path = self.out_path(step_id)
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def result_path(self, name: str) -> Path:
        path = self.dir / "results" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def rel(self, path: Path) -> str:
        """A path as the agents should name it: relative to the repository."""
        try:
            return path.relative_to(self.workspace).as_posix()
        except ValueError:
            return str(path)

    # ── the ADK tool functions' view of this run ─────────────────────────────
    def tool_context(self, pattern: str | None = None, **extra) -> SimpleNamespace:
        """An object shaped like ADK's ToolContext (`.state`, `.actions`), so the
        tool functions in agents/*/tools.py run unchanged. `state` carries what
        they read: the workspace, the baseline, the pattern, the approved plan,
        the preflight result, the incremental stage."""
        pattern = pattern or self.state.get("current_pattern") or self.state["pattern"]
        state = {
            "workspace_dir": str(self.workspace),
            "baseline_dir": self.state.get("baseline_dir", ""),
            "pattern": pattern,
            "plan": self.read_doc("plan", pattern),
            "preflight_json": self.state.get("preflight_json", ""),
            "approved_stage": self.state.get("approved_stage", ""),
            "java11_build_passed": self.state.get("java11_build_passed"),
            "pass_changes": self.state.get("pass_changes", {}),
            "pass_start_file": str(self.result_path(f"{pattern}/pass_start.json")),
            **extra,
        }
        return SimpleNamespace(state=state, actions=SimpleNamespace(escalate=False, skip_summarization=False))

    def absorb(self, ctx: SimpleNamespace, *keys: str) -> None:
        """Copy back what a tool function wrote to its state."""
        for key in keys:
            if key in ctx.state:
                self.state[key] = ctx.state[key]
        self.save()
