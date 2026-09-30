"""
Every migration pattern's workflow end to end, with the agent calls stubbed out.

Guards the shared orchestration against a change made for one pattern leaking
into the others: each pattern must still reach the code step it always did
(incremental Java its staged step, every other migration the single-pass
`_run_workspace_code_step` with its own runner key), the java-8-to-11 fence
must stay a no-op for them -- a JSP another pattern rewrites stays rewritten --
and the upload endpoint must still accept each pattern's own options.
"""
import asyncio
import json
import zipfile
import io

import pytest
from fastapi.testclient import TestClient

import main
from agents import APP_NAME, PATTERN_RUNNERS, USER_ID, session_service

RE_OUTPUT = (
    "<!-- SECTION: ANALYSIS -->\nanalysis\n<!-- SECTION: BRD -->\nbrd\n"
    "<!-- SECTION: TECHNICAL_SPECIFICATION -->\ntech\n<!-- SECTION: TEST_INVENTORY -->\ntests\n"
    "<!-- SECTION: END -->\n"
)

JSP = "src/main/webapp/index.jsp"


class _Harness:
    def __init__(self, monkeypatch):
        self.steps: list[tuple[str, str]] = []
        self.code: list[tuple] = []

        async def fake_run_step(session_id, step_key, pattern, message, sse_event_type):
            self.steps.append((step_key, pattern))
            # java-8-to-11 analyses unit by unit (re_module) and then combines (re_synthesize).
            key, value = {
                "re": ("analysis", RE_OUTPUT),
                "re_synthesize": ("analysis", RE_OUTPUT),
                "re_module": ("module_findings", "## Unit 1: findings"),
            }.get(step_key, ("plan", f"# {pattern} plan"))
            await main._update_state(session_id, {key: value})

        async def fake_workspace_step(session_id, pattern, code_key, push_session_id=None):
            self.code.append(("single-pass", pattern, code_key))
            # A migration that legitimately rewrites a JSP (JSP -> Thymeleaf, say).
            state = await main._get_state(session_id)
            (main.Path(state["workspace_dir"]) / JSP).write_text("<html>migrated</html>")

        async def fake_incremental(session_id, push_session_id=None):
            self.code.append(("incremental", "java-8-to-25", None))

        async def fake_java11(session_id, push_session_id=None):
            self.code.append(("java11", "java-8-to-11", None))

        monkeypatch.setattr(main, "_run_step", fake_run_step)
        monkeypatch.setattr(main, "_run_workspace_code_step", fake_workspace_step)
        monkeypatch.setattr(main, "_run_java8_incremental_code_step", fake_incremental)
        monkeypatch.setattr(main, "_run_java11_code_step", fake_java11)


def _run(tmp_path, pattern: str, strategy: str = "bigbang", graph_json: str = "[]") -> tuple[list[dict], dict]:
    workspace, baseline = tmp_path / "ws", tmp_path / "base"
    for root in (workspace, baseline):
        (root / "src/main/webapp").mkdir(parents=True)
        (root / JSP).write_text("<html></html>")
        (root / "pom.xml").write_text("<project/>")

    state = main._initial_state(pattern, str(workspace), str(baseline), graph_json, strategy, False, False)
    sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
    main._sse_queues[sid] = asyncio.Queue()
    for gates in (main._brd_gates, main._plan_gates, main._companion_gates):
        gates[sid] = asyncio.Event()
        gates[sid].set()  # the reviewer approves immediately

    # Capture the delivered file before _run_workflow deletes the workspace.
    captured: dict = {}
    real_archive = main._archive_workspace

    def archive(workspace_dir):
        captured["jsp"] = (main.Path(workspace_dir) / JSP).read_text()
        return real_archive(workspace_dir)

    main._archive_workspace = archive
    try:
        asyncio.run(main._run_workflow(sid))
    finally:
        main._archive_workspace = real_archive

    events = []
    queue = main._sse_queues[sid]
    while not queue.empty():
        raw = queue.get_nowait()
        if raw:
            events += [json.loads(l[6:]) for l in raw.splitlines() if l.startswith("data: ")]
    return events, captured


@pytest.mark.parametrize("pattern, strategy, expected", [
    ("java-8-to-25", "bigbang", ("single-pass", "java-8-to-25", "code_bigbang")),
    ("java-8-to-25", "incremental", ("incremental", "java-8-to-25", None)),
    ("solr-4-to-9", "bigbang", ("single-pass", "solr-4-to-9", "code")),
    ("oracle-19c-to-23ai", "bigbang", ("single-pass", "oracle-19c-to-23ai", "code")),
    ("tibco-ems-to-pubsub", "bigbang", ("single-pass", "tibco-ems-to-pubsub", "code")),
    ("jsp-to-react-bff", "bigbang", ("single-pass", "jsp-to-react-bff", "code")),
    ("java-8-to-11", "bigbang", ("java11", "java-8-to-11", None)),
])
def test_each_pattern_reaches_its_own_code_step_and_completes(monkeypatch, tmp_path, pattern, strategy, expected):
    harness = _Harness(monkeypatch)
    events, _ = _run(tmp_path, pattern, strategy)

    assert not [e for e in events if e["type"] == "error"], events
    # Every migration except JSP -> React + BFF analyses with a deterministic
    # inventory: no model call before the planner.
    expected_re = [("re", pattern)] if pattern == "jsp-to-react-bff" else []
    assert harness.steps == expected_re + [("plan", pattern)]
    assert harness.code == [expected]
    steps = [e["step"] for e in events if e["type"] == "step-change"]
    assert steps[-1] == "complete"
    assert {"reverse-engineering", "brd-review", "plan-generation", "plan-review", "code-generation"} <= set(steps)
    assert any(e["type"] == "workflow-complete" for e in events)
    # Every code runner key the dispatch uses must exist.
    if expected[2]:
        assert expected[2] in PATTERN_RUNNERS[pattern]


@pytest.mark.parametrize("pattern", ["java-8-to-25", "jsp-to-react-bff", "solr-4-to-9"])
def test_the_java_11_fence_never_undoes_another_patterns_changes(monkeypatch, tmp_path, pattern):
    _Harness(monkeypatch)
    events, captured = _run(tmp_path, pattern)

    assert captured["jsp"] == "<html>migrated</html>"
    diff = next(e for e in events if e["type"] == "diff-ready")
    assert [f["path"] for f in diff["changed_files"]] == [JSP]
    assert not any("Scope Fence Enforcement" in (e.get("content") or "") for e in events)


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pom.xml", "<project/>")
    return buf.getvalue()


@pytest.mark.parametrize("pattern, data", [
    ("java-8-to-25", {"migration_strategy": "incremental", "junit_upgrade": "true", "springboot_upgrade": "true"}),
    ("solr-4-to-9", {}),
    ("oracle-19c-to-23ai", {}),
    ("tibco-ems-to-pubsub", {}),
    ("jsp-to-react-bff", {}),
    ("java-8-to-11", {}),
])
def test_upload_still_accepts_each_patterns_own_options(monkeypatch, pattern, data):
    started: list[str] = []

    async def no_workflow(session_id):
        started.append(session_id)

    monkeypatch.setattr(main, "_run_workflow", no_workflow)
    with TestClient(main.app) as client:
        res = client.post("/api/upload", data={"pattern": pattern, **data},
                          files={"file": ("repo.zip", _zip(), "application/zip")})
    assert res.status_code == 200, res.text
    assert started == [res.json()["session_id"]]


@pytest.mark.parametrize("pattern", ["java-8-to-25", "solr-4-to-9", "oracle-19c-to-23ai", "tibco-ems-to-pubsub"])
def test_migration_analysis_agent_restores_the_reverse_engineering_agent(monkeypatch, tmp_path, pattern):
    monkeypatch.setattr(main.config, "MIGRATION_ANALYSIS", "agent")
    harness = _Harness(monkeypatch)
    events, _ = _run(tmp_path, pattern)
    assert not [e for e in events if e["type"] == "error"], events
    assert harness.steps == [("re", pattern), ("plan", pattern)]


@pytest.mark.parametrize("pattern", ["java-8-to-25", "solr-4-to-9", "oracle-19c-to-23ai", "tibco-ems-to-pubsub"])
def test_inventory_reaches_the_planner_state_and_the_review_screen(monkeypatch, tmp_path, pattern):
    """What the planner is templated with ({brd}, {technical_spec},
    {test_inventory}) is the inventory, and the brd-review gate still shows it."""
    harness = _Harness(monkeypatch)
    seen = {}

    async def fake_run_step(session_id, step_key, p, message, sse_event_type):
        harness.steps.append((step_key, p))
        seen.update(await main._get_state(session_id))
        await main._update_state(session_id, {"plan": f"# {p} plan"})

    monkeypatch.setattr(main, "_run_step", fake_run_step)
    graph = json.dumps({"nodes": ["pom.xml"], "edges": [], "groups": [["pom.xml"]]})
    events, _ = _run(tmp_path, pattern, graph_json=graph)
    assert harness.steps == [("plan", pattern)]
    assert "no language model read this repository" in seen["brd"]
    assert "## Legacy Stack Blockers" in seen["technical_spec"]
    assert seen["technical_spec"].startswith("## Dependency Graph & Migration Groups")  # still injected
    assert seen["test_inventory"].strip()
    brd_ready = next(e for e in events if e["type"] == "brd-ready")
    assert "## Legacy Stack Blockers" in brd_ready["technical_spec"]


def test_refine_keeps_the_reviewers_feedback_for_the_planner(monkeypatch, tmp_path):
    _Harness(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "schema.sql").write_text("CREATE TABLE t (c LONG);\n")
    state = main._initial_state("oracle-19c-to-23ai", str(workspace), str(workspace), "[]", "bigbang", False, False)
    sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
    main._sse_queues[sid] = asyncio.Queue()
    asyncio.run(main._run_bundle_re(sid, ["oracle-19c-to-23ai"], feedback="Keep LONG in the audit table."))
    brd = asyncio.run(main._get_state(sid))["brd"]
    assert "## Reviewer Notes" in brd and "Keep LONG in the audit table." in brd


def test_companion_bundle_uses_an_inventory_for_each_migration(monkeypatch, tmp_path):
    """java-8-to-25 with Oracle selected as a companion: both analysed without a
    model, each under its own heading, then each planned."""
    harness = _Harness(monkeypatch)
    workspace = tmp_path / "ws"
    (workspace / "db").mkdir(parents=True)
    (workspace / "db/schema.sql").write_text("CREATE TABLE t (c LONG);\n")
    (workspace / "A.java").write_text("import net.sf.ehcache.CacheManager;\n")
    state = main._initial_state("java-8-to-25", str(workspace), str(workspace), "[]", "bigbang", False, False)
    sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
    main._sse_queues[sid] = asyncio.Queue()
    asyncio.run(main._run_bundle_re(sid, ["oracle-19c-to-23ai", "java-8-to-25"]))
    assert harness.steps == []
    state = asyncio.run(main._get_state(sid))
    assert "LONG / LONG RAW column" in state["technical_spec_oracle-19c-to-23ai"]
    assert "Ehcache 2" in state["technical_spec_java-8-to-25"]
    assert "Ehcache 2" not in state["technical_spec_oracle-19c-to-23ai"]
    combined = state["technical_spec"]
    assert combined.index("## " + main._label("java-8-to-25")) < combined.index("## " + main._label("oracle-19c-to-23ai"))
    # The combined document still splits back per pattern for the reviewer's edits.
    assert set(main._split_combined_sections(combined, ["java-8-to-25", "oracle-19c-to-23ai"])) >= {
        "java-8-to-25", "oracle-19c-to-23ai"}


def test_stack_discovery_still_runs_the_reverse_engineering_agents(monkeypatch, tmp_path):
    harness = _Harness(monkeypatch)
    state = main._initial_state("stack-discovery", str(tmp_path), str(tmp_path), "[]", "bigbang", False, False)
    sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
    main._sse_queues[sid] = asyncio.Queue()
    stacks = ["java-8-to-25", "oracle-19c-to-23ai", "solr-4-to-9", "tibco-ems-to-pubsub", "wildfly"]
    asyncio.run(main._run_bundle_re(sid, stacks))
    assert harness.steps == [("re", p) for p in stacks]
    for p in stacks:
        assert "re" in PATTERN_RUNNERS[p]
