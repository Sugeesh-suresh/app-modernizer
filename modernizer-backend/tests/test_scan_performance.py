"""Structural guards for the scan optimizations (no stopwatch assertions that flake on a slow runner): the
scanners never walk build output / dependency folders, and the fix step of an incremental run reads only its
stage's part of the plan."""
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from agents import config
from agents.shared import change_audit, companion_detector, fswalk, migration_inventory
from cli import pipeline
from cli.runstate import Run

sys.path.insert(0, str(Path(__file__).parent))
from test_cli_hostile_runs import _plan, _tool, home  # noqa: E402,F401  (the autouse home fixture)

FIXTURES = Path(__file__).parent / "fixtures"


def _junk_heavy(tmp_path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "orders-jsp-oracle-monorepo", repo)
    for folder, name, n in (("order-web/node_modules/pkg/lib", "f{}.js", 1500), ("order-services/target/classes/p", "C{}.class", 1500),
                            (".git/objects/ab", "o{}", 800), ("order-web/build/out", "b{}.txt", 500)):
        d = repo / folder
        d.mkdir(parents=True)
        for i in range(n):
            (d / name.format(i)).write_text("x")
    return repo


def test_the_walker_never_enters_an_excluded_folder(tmp_path, monkeypatch):
    repo = _junk_heavy(tmp_path)
    visited = []
    real = os.walk

    def spy(top, *a, **k):
        for dirpath, dirnames, filenames in real(top, *a, **k):
            visited.append(dirpath)
            yield dirpath, dirnames, filenames
    monkeypatch.setattr(fswalk.os, "walk", spy)
    found = list(fswalk.files(repo))
    assert not [d for d in visited if any(part in ("node_modules", "target", ".git", "build") for part in Path(d).parts)]
    assert not [p for p in found if "node_modules" in p.parts or "target" in p.parts]
    assert any(p.name == "pom.xml" for p in found) and any(p.suffix == ".jsp" for p in found)
    assert [p.name for p in fswalk.files(repo, "pom.xml")].count("pom.xml") == 3


def test_a_run_never_globs_the_whole_tree_of_a_repository_full_of_build_output(tmp_path, monkeypatch):
    repo = _junk_heavy(tmp_path)
    whole_tree = []
    real_rglob = Path.rglob

    def spy(self, pattern, *a, **k):
        if pattern == "*" and str(self).startswith(str(repo)) and ".modernizer" not in str(self):
            whole_tree.append(str(self))
        return real_rglob(self, pattern, *a, **k)
    monkeypatch.setattr(Path, "rglob", spy)
    t = time.monotonic()
    pipeline.start(repo, "java-8-to-25", migration_strategy="incremental")
    step, _ = pipeline.next_step(Run.load(repo))
    assert step["kind"] in ("ask_user", "subagent")
    change_audit.relevant_files(repo)
    companion_detector.detect_companions(str(repo), "java-8-to-25")
    migration_inventory.to_document("java-8-to-25", str(repo))
    assert whole_tree == [], f"rglob('*') over {whole_tree[:3]}"
    assert time.monotonic() - t < 30


def test_an_incremental_fix_reads_its_stage_not_the_whole_plan(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "orders-jsp-oracle-monorepo", repo)
    pipeline.start(repo, "java-8-to-25", migration_strategy="incremental")
    step = pipeline.next_step(Run.load(repo))[0]
    if step["kind"] == "ask_user":
        pipeline.confirm(Run.load(repo), "companions", [])
    plan_text = None
    for _ in range(80):
        step, _log = pipeline.next_step(Run.load(repo))
        sid, kind = step["id"], step["kind"]
        if kind == "review_gate":
            pipeline.confirm(Run.load(repo), "plan"); continue
        if sid.startswith("plan-"):
            plan_text = _plan(repo, "java-8-to-25", "incremental") + "\n\n" + "\n".join(
                f"Padding line {i} about unrelated stages." for i in range(400))
            text = plan_text
        elif sid.startswith("validate-"):
            text = '{"passed": false, "errors": ["order-services/pom.xml: cannot resolve"], "summary": "x"}'
        elif sid.startswith("fix-"):
            q = step["query"]
            assert "this stage's section" in q and "plan_stage1.md" in q, q[-900:]
            extract = repo / ".modernizer/results/java-8-to-25/plan_stage1.md"
            full = repo / ".modernizer/docs/java-8-to-25/plan.md"
            assert extract.is_file() and len(extract.read_text()) < len(full.read_text()) / 3
            body = extract.read_text().split("\n---\n")[0]
            assert "### Task 1.1" in body and "### Task 2.1" not in body and "Modernize Build Systems" in body
            assert "The full plan is" in extract.read_text()
            return
        else:
            text = f"Done {sid}."
        _tool(__import__("cli.mcp_server", fromlist=["x"]).save_output, repo, step_id=sid, content=text)
        pipeline.complete_step(Run.load(repo), sid)
    pytest.fail("never reached a fix step")
