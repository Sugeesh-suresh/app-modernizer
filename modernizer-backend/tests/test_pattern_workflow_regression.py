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


def _run(tmp_path, pattern: str, strategy: str = "bigbang") -> tuple[list[dict], dict]:
    workspace, baseline = tmp_path / "ws", tmp_path / "base"
    for root in (workspace, baseline):
        (root / "src/main/webapp").mkdir(parents=True)
        (root / JSP).write_text("<html></html>")
        (root / "pom.xml").write_text("<project/>")

    state = main._initial_state(pattern, str(workspace), str(baseline), "[]", strategy, False, False)
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
    # The small test repository is one unit, so java-8-to-11 runs one unit analysis, then combines.
    expected_re = [("re_module", pattern), ("re_synthesize", pattern)] if pattern == "java-8-to-11" else [("re", pattern)]
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
