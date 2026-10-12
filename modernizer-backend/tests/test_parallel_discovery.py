"""Parallel discovery batches (Gemini CLI path): independent batches are handed out as one `parallel`
step (DISCOVERY_CONCURRENCY at a time) and completed in any order — with exactly the results a
one-at-a-time run gives for the same answers."""
import json
import re
import shutil
from pathlib import Path

import anyio
import pytest

from agents import config
from cli import discovery, mcp_server, pipeline
from cli.runstate import Run, RunError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MODERNIZER_WORKSPACE", raising=False)
    monkeypatch.setattr(config, "RULES_EXTRACTION", "on")
    monkeypatch.setattr(config, "RULES_BATCH_MAX_CANDIDATES", 2)    # many rule batches from a small repository
    monkeypatch.setattr(config, "DISCOVERY_CHUNK_MIN_FILES", 1)     # the stack's evidence in units…
    monkeypatch.setattr(config, "DISCOVERY_UNIT_MAX_FILES", 3)      # …of three files


def _members(step: dict) -> list[dict]:
    return step["members"] if step["kind"] == "parallel" else [step]


def _answer(repo: Path, sid: str, query: str) -> str:
    """A deterministic stand-in answer per step — the same whatever order the steps run in."""
    if sid.startswith("evidence-java-unit-"):
        files = re.findall(r"^- `([^`]+)`$", query, re.M)
        return "### Components\n" + "".join(f"- `{f}` is part of the shop ({f}:1)\n" for f in files) + \
            "\n### Limitations\nNone found.\n"
    if sid.startswith("rules-"):
        request = repo / re.search(r"`(\.modernizer/discovery/rules/batch-[^`]+\.md)`", query).group(1)
        text = request.read_text()
        results = [{"candidate": cid, "rules": [{"statement": f"An order rule applies in {cid}.", "type": "validation",
                                                 "lines": start, "basis": "explicit"}]}
                   for cid, start in re.findall(r"### (C\d{5}) .*?\nFile: `[^`]+` lines (\d+)-", text)]
        if sid.endswith("-classify-0") and len(results) > 1:
            results = results[1:]                       # a partial first answer: the follow-up asks again
        return "```json\n" + json.dumps({"results": results}) + "\n```"
    if sid.startswith("ea-ui"):
        return "No controls."
    return {"po_brd": "# BRD\n\n## Executive Summary\nThe shop takes orders.\n",
            "ea_spec": "# Technical Specification\n\n## Architecture Overview\nOne Spring MVC application.\n",
            "ea_diagrams": '{"diagrams": []}',
            "setup": "## Prerequisites\nA JDK (pom.xml).\n"}.get(sid.split("-retry")[0], "None found.")


def _discover(tmp_path: Path, name: str, concurrency: int, monkeypatch) -> tuple[Path, list[int]]:
    """Reverse-engineer the thymeleaf-rules fixture with the stand-in answers; returns the repository
    and the size of every step handed out (1 = alone, n = a parallel group of n)."""
    monkeypatch.setattr(config, "DISCOVERY_CONCURRENCY", concurrency)
    repo = tmp_path / name
    shutil.copytree(FIXTURES / "thymeleaf-rules", repo)
    pipeline.start(repo, "stack-discovery")
    sizes = []
    for _ in range(500):
        step, _log = pipeline.next_step(Run.load(repo))
        if step["id"] == "select-stacks":
            pipeline.confirm(Run.load(repo), "stacks", ["java"], ["brd", "technical_spec"])
            continue
        if step["id"] == "select-strategy":
            pipeline.confirm(Run.load(repo), "strategy", ["stack-by-stack"])
            continue
        if step["kind"] == "review_gate":
            return repo, sizes
        assert step["kind"] in ("subagent", "parallel"), step
        members = _members(step)
        sizes.append(len(members))
        for m in members:                                  # all saved, then each completed — as Gemini does
            text = "Nothing to add.\n\n```json\n{\"stacks\": [], \"rejected\": []}\n```" if m["id"] == "mapper" \
                else _answer(repo, m["id"], m["query"])
            anyio.run(lambda: mcp_server.save_output(step_id=m["id"], content=text, workspace=str(repo)))
        for m in reversed(members):                        # completion order must not matter
            pipeline.complete_step(Run.load(repo), m["id"])
    pytest.fail("discovery did not reach the review")


def test_parallel_batches_give_exactly_the_one_at_a_time_results(tmp_path, monkeypatch):
    serial, serial_sizes = _discover(tmp_path, "serial", 1, monkeypatch)
    parallel, parallel_sizes = _discover(tmp_path, "parallel", 4, monkeypatch)
    assert set(serial_sizes) == {1}
    assert max(parallel_sizes) == 4 and len(parallel_sizes) < len(serial_sizes)
    assert sum(parallel_sizes) == sum(serial_sizes)        # the same agent runs, fewer rounds
    for rel in (".modernizer/discovery/evidence/java.md", ".modernizer/deliverables/BRD.md",
                ".modernizer/deliverables/EVIDENCE.md", ".modernizer/deliverables/TECHNICAL_SPECIFICATION.md"):
        assert (serial / rel).read_text() == (parallel / rel).read_text(), rel
    rules = (parallel / ".modernizer/deliverables/EVIDENCE.md").read_text()
    assert "An order rule applies in" in rules                # the follow-up batches ran and were merged


def test_a_group_member_is_saved_and_completed_on_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DISCOVERY_CONCURRENCY", 3)
    repo = tmp_path / "shop"
    shutil.copytree(FIXTURES / "thymeleaf-rules", repo)
    pipeline.start(repo, "stack-discovery")
    step, _ = pipeline.next_step(Run.load(repo))
    anyio.run(lambda: mcp_server.save_output(step_id="mapper", content="```json\n{\"stacks\": []}\n```",
                                             workspace=str(repo)))
    pipeline.complete_step(Run.load(repo), "mapper")
    pipeline.next_step(Run.load(repo))
    pipeline.confirm(Run.load(repo), "stacks", ["java"], ["technical_spec"])
    pipeline.next_step(Run.load(repo))
    pipeline.confirm(Run.load(repo), "strategy", ["stack-by-stack"])
    group, _ = pipeline.next_step(Run.load(repo))
    assert group["kind"] == "parallel" and [m["id"] for m in group["members"]] == [
        "evidence-java-unit-1", "evidence-java-unit-2", "evidence-java-unit-3"]
    text = mcp_server._format_step(group, [])
    assert "**in one turn**" in text and text.count("<query>") == 3
    assert pipeline.next_step(Run.load(repo))[0]["id"] == group["id"]          # asked again: the same group

    first, second = group["members"][0]["id"], group["members"][1]["id"]
    with pytest.raises(RunError):                                               # nothing saved yet
        pipeline.complete_step(Run.load(repo), second)
    assert anyio.run(lambda: mcp_server.save_output(step_id="evidence-java-unit-9", content="x",
                                                    workspace=str(repo))).startswith("ERROR")
    for sid in (first, second):
        anyio.run(lambda: mcp_server.save_output(step_id=sid, content=_answer(repo, sid, next(
            m["query"] for m in group["members"] if m["id"] == sid)), workspace=str(repo)))
    assert "2 more in this group" in pipeline.complete_step(Run.load(repo), second)
    with pytest.raises(RunError):
        pipeline.complete_step(Run.load(repo), second)                          # already done
    pipeline.complete_step(Run.load(repo), first)
    status = pipeline.summary(Run.load(repo))
    assert "1 of 3 parallel batches" in status and "evidence-java-unit-3" in status
    assert pipeline.next_step(Run.load(repo))[0]["id"] == group["id"]          # still waiting on one


def test_concurrent_saves_and_completions_lose_no_update(tmp_path, monkeypatch):
    """Gemini CLI runs a group's tool calls at the same time: the MCP server serialises them."""
    monkeypatch.setattr(config, "DISCOVERY_CONCURRENCY", 4)
    repo = tmp_path / "shop"
    shutil.copytree(FIXTURES / "thymeleaf-rules", repo)
    pipeline.start(repo, "stack-discovery")
    pipeline.next_step(Run.load(repo))
    anyio.run(lambda: mcp_server.save_output(step_id="mapper", content="```json\n{\"stacks\": []}\n```",
                                             workspace=str(repo)))
    pipeline.complete_step(Run.load(repo), "mapper")
    pipeline.next_step(Run.load(repo))
    pipeline.confirm(Run.load(repo), "stacks", ["java"], ["technical_spec"])
    pipeline.next_step(Run.load(repo))
    pipeline.confirm(Run.load(repo), "strategy", ["stack-by-stack"])
    group, _ = pipeline.next_step(Run.load(repo))
    members = group["members"]
    assert len(members) == 3                                                   # the fixture's three units

    async def all_at_once():
        async with anyio.create_task_group() as tg:
            for m in members:
                tg.start_soon(lambda m=m: mcp_server.save_output(step_id=m["id"], content=_answer(
                    repo, m["id"], m["query"]), workspace=str(repo)))
        results = []
        async with anyio.create_task_group() as tg:
            for m in members:
                async def finish(m=m):
                    results.append(await mcp_server.complete_step(step_id=m["id"], workspace=str(repo)))
                tg.start_soon(finish)
        return results
    results = anyio.run(all_at_once)
    assert not [r for r in results if r.startswith("ERROR")], results
    state = Run.load(repo).state
    assert state["current_step"] is None                                       # every member recorded
    units = sorted(p.name for p in (repo / ".modernizer/discovery/evidence/units").iterdir())
    assert units == [f"java-{n:04d}.md" for n in range(1, 4)]
