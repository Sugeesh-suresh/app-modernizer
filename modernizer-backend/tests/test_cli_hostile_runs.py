"""The Gemini CLI pipeline under hostile conditions: nasty repositories driven through whole runs, a corrupted
run state, symlink loops, very deep trees, concurrent and out-of-order calls. Every failure must be a clear
`ERROR:` / RunError the agent can read — never a traceback, a hang or a half-written state."""
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

import anyio
import pytest

from agents import config
from cli import mcp_server, pipeline
from cli.runstate import Run, RunError

sys.path.insert(0, str(Path(__file__).parent))
from test_stress_inputs import HOSTILE            # noqa: E402  the nasty files of the analyser stress test

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MODERNIZER_WORKSPACE", raising=False)
    monkeypatch.setattr(config, "PREFLIGHT", "off")
    monkeypatch.setattr(config, "MIGRATION_ANALYSIS", "inventory")


def _tool(fn, repo, **kw):
    return anyio.run(lambda: fn(workspace=str(repo), **kw))


def _hostile_repo(tmp_path) -> Path:
    repo = tmp_path / "ünï repo with spaces"
    for rel, data in HOSTILE.items():
        p = repo / rel.removeprefix("repo/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    (repo / "pom.xml").write_text("<project><modelVersion>4.0.0</modelVersion><groupId>g</groupId>"
                                  "<artifactId>a</artifactId><version>1</version></project>")
    (repo / "src/main/java/odd name\twith tab.java").write_text("class X {}")
    os.symlink(repo, repo / "loop")                                  # a symlink to its own root
    os.symlink(repo / "nope", repo / "dangling")
    deep = repo
    for i in range(120):
        deep = deep / f"d{i}"
    deep.mkdir(parents=True)
    (deep / "Deep.java").write_text("import net.sf.ehcache.Cache; class Deep {}")
    (repo / ".modernizer-old").mkdir()
    return repo


def _plan(repo: Path, pattern: str, strategy: str = "bigbang") -> str:
    files = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*.java")
                   if ".modernizer" not in p.parts and not p.is_symlink() and "loop" not in p.relative_to(repo).parts
                   and "\t" not in p.name and "d0" not in p.relative_to(repo).parts)[:6] or ["pom.xml"]
    rows = "\n".join(f"| `{f}` | modify | migrate |" for f in files)
    plan = f"# Plan\n\n## 1. What Changes\n### File Change Manifest\n| File | Change Type | What Changes |\n|---|---|---|\n{rows}\n"
    if pattern == "java-8-to-25":
        from agents.java_8_to_25.stages import INCREMENTAL_STAGES
        stages = [s for s in INCREMENTAL_STAGES if s.idx <= 8] if strategy == "incremental" else None
        if stages:
            for n, s in enumerate(stages, 1):
                plan += f"\n## Stage {n}: {s.title}\n\n### Task {n}.1: do it\n- Files: `{files[0]}`\n- Change: x\n"
        else:
            plan += f"\n### Task 1.1: do it\n- Files: `{files[0]}`\n- Change: x\n"
    return plan


def _drive(repo: Path, pattern: str, **opts) -> list[str]:
    """A whole run with stand-in outputs; returns the step ids handled. Raises on any pipeline error."""
    pipeline.start(repo, pattern, **opts)
    seen = []
    for _ in range(300):
        step, _log = pipeline.next_step(Run.load(repo))
        seen.append(step["id"])
        kind = step["kind"]
        if kind in ("done", "blocked"):
            return seen
        if kind == "ask_user":
            pipeline.confirm(Run.load(repo), "companions", []); continue
        if kind == "review_gate":
            pipeline.confirm(Run.load(repo), "analysis" if "analysis" in step["id"] else "plan"); continue
        sid = step["id"]
        if sid.startswith("plan-"):
            text = _plan(repo, pattern, opts.get("migration_strategy", "bigbang"))
        elif sid.startswith("validate-"):
            _tool(mcp_server.ws_signal_build_success, repo)
            text = '{"passed": true, "errors": [], "summary": "ok"}'
        elif sid.startswith("analysis-"):
            text = ("<!-- SECTION: ANALYSIS -->\nA\n<!-- SECTION: BRD -->\nB\n<!-- SECTION: TECHNICAL_SPECIFICATION -->\n"
                    "T\n<!-- SECTION: TEST_INVENTORY -->\nI\n<!-- SECTION: END -->")
        else:
            text = f"Done {sid}."
        assert _tool(mcp_server.save_output, repo, step_id=sid, content=text).startswith("Saved")
        pipeline.complete_step(Run.load(repo), sid)
    pytest.fail(f"{pattern} did not finish: {seen[-5:]}")


@pytest.mark.parametrize("pattern,opts", [
    ("java-8-to-25", {}),
    ("java-8-to-25", {"migration_strategy": "incremental", "springboot_upgrade": True, "junit_upgrade": True}),
    ("java-8-to-11", {}),
    ("solr-4-to-9", {}),
    ("oracle-19c-to-23ai", {}),
    ("tibco-ems-to-pubsub", {}),
], ids=["j25-bigbang", "j25-incremental", "j11", "solr", "oracle", "tibco"])
def test_every_pipeline_finishes_on_a_hostile_repository(tmp_path, pattern, opts):
    repo = _hostile_repo(tmp_path)
    t = time.monotonic()
    seen = _drive(repo, pattern, **opts)
    assert seen[-1] == "done" and time.monotonic() - t < 60
    assert (repo / ".modernizer/results/changes.md").is_file()


def test_a_corrupted_run_state_is_a_clear_error_not_a_traceback(tmp_path):
    repo = tmp_path / "r"
    shutil.copytree(FIXTURES / "orders-jsp-hibernate-monorepo", repo)
    pipeline.start(repo, "java-8-to-11")
    state = repo / ".modernizer/run.json"
    for broken in ('{"run_id": "x", "pattern": "java-8-', "", "[]", "null", '{"pattern": "java-8-to-11"}'):
        state.write_text(broken)
        out = _tool(mcp_server.next_step, repo)
        assert out.startswith("ERROR:") and "Traceback" not in out, (broken, out[:200])
        out = _tool(mcp_server.run_status, repo)
        assert out.startswith("ERROR:"), (broken, out[:200])
    out = _tool(mcp_server.start_run, repo, pattern="java-8-to-11")
    assert out.startswith("ERROR:") and "restart=true" in out         # not silently overwritten
    assert not _tool(mcp_server.start_run, repo, pattern="java-8-to-11", restart=True).startswith("ERROR")


def test_calls_out_of_order_are_refused_clearly(tmp_path):
    repo = tmp_path / "r"
    shutil.copytree(FIXTURES / "banking-soap-oracle", repo)
    pipeline.start(repo, "oracle-19c-to-23ai")
    step = pipeline.next_step(Run.load(repo))[0]
    assert _tool(mcp_server.save_output, repo, step_id="plan-nope", content="x").startswith("ERROR")
    assert _tool(mcp_server.complete_step, repo, step_id=step["id"]).startswith("ERROR")        # nothing saved yet
    assert _tool(mcp_server.confirm, repo, gate="plan").startswith("ERROR")                     # not at that gate
    assert _tool(mcp_server.confirm, repo, gate="nonsense").startswith("ERROR")
    assert _tool(mcp_server.ws_write_file, repo, path="a.txt", content="x").startswith("ERROR")  # plan not approved
    assert _tool(mcp_server.ws_signal_build_success, repo).startswith("ERROR")
    assert _tool(mcp_server.save_output, repo, step_id=step["id"], content="# Plan\n").startswith("Saved")
    assert not _tool(mcp_server.complete_step, repo, step_id=step["id"]).startswith("ERROR")
    assert _tool(mcp_server.complete_step, repo, step_id=step["id"]).startswith("ERROR")        # twice


def test_paths_cannot_escape_the_repository_or_touch_the_run_state(tmp_path):
    repo = tmp_path / "r"
    shutil.copytree(FIXTURES / "banking-soap-oracle", repo)
    outside = tmp_path / "outside.txt"
    run = pipeline.start(repo, "oracle-19c-to-23ai")
    step = pipeline.next_step(Run.load(repo))[0]
    _tool(mcp_server.save_output, repo, step_id=step["id"], content=_plan(repo, "oracle-19c-to-23ai"))
    pipeline.complete_step(Run.load(repo), step["id"])
    pipeline.next_step(Run.load(repo))
    pipeline.confirm(Run.load(repo), "plan")
    os.symlink(tmp_path, repo / "escape")
    for bad in ("../outside.txt", "/etc/passwd-x", "escape/outside.txt", ".modernizer/run.json", "a/../../outside.txt",
                "..\\outside.txt", "C:\\Windows\\x.txt"):
        out = _tool(mcp_server.ws_write_file, repo, path=bad, content="pwned")
        assert out.startswith("ERROR"), (bad, out)
    assert not outside.exists() and not Path("/etc/passwd-x").exists()
    assert json.loads((repo / ".modernizer/run.json").read_text())["run_id"] == run.state["run_id"]


def test_concurrent_next_step_calls_share_one_piece_of_work(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    shutil.copytree(FIXTURES / "banking-soap-oracle", repo)
    pipeline.start(repo, "oracle-19c-to-23ai")
    calls, release = [], threading.Event()
    real = pipeline.next_step

    def slow(run):
        calls.append(1)
        release.wait(20)
        return real(run)

    monkeypatch.setattr(mcp_server.pipeline, "next_step", slow)
    monkeypatch.setattr(config, "PROGRESS_FIRST_REPORT_SECONDS", 1)
    monkeypatch.setattr(config, "PROGRESS_REPORT_SECONDS", 1)
    mcp_server._WORKERS.clear()
    results: list[str] = []

    async def many():
        async with anyio.create_task_group() as tg:
            for _ in range(5):
                async def one():
                    results.append(await mcp_server.next_step(workspace=str(repo)))
                tg.start_soon(one)
            await anyio.sleep(2.5)
            release.set()
    anyio.run(many)
    assert len(calls) == 1, f"the work ran {len(calls)} times"
    assert all(r.startswith("## Still working") for r in results)         # nobody got a second copy of the work
    final = anyio.run(lambda: mcp_server.next_step(workspace=str(repo)))
    assert "## Next:" in final and len(calls) == 1                         # and the one result is collected once
    mcp_server._WORKERS.clear()
