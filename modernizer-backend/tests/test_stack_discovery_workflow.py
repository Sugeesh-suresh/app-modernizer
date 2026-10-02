"""
Integration tests for the stack-discovery workflow end to end, with the agent
calls stubbed out.

Verifies the wiring no unit test can reach: that the mapper's result gates on the
reviewer's confirmation, that each confirmed stack's own RE runner is invoked,
that the sections come back combined under per-stack headings with the inventory
on top, and that the run stops at brd-review instead of falling through to plan
generation.
"""
import asyncio
import json

from fastapi.testclient import TestClient

import main
from agents import APP_NAME, USER_ID, session_service

PRESCAN = [
    {"pattern": "wildfly", "label": "WildFly / JBoss (app server)",
     "evidence": ["standalone.xml: present"], "extraction_only": True},
    {"pattern": "oracle-19c-to-23ai", "label": "Oracle 19c → 23ai",
     "evidence": ["pom.xml: matched `ojdbc8`"], "extraction_only": False},
    {"pattern": "java-8-to-25", "label": "Java 8 → Java 25",
     "evidence": ["src/A.java: present"], "extraction_only": False},
]

MAPPER_REPLY = (
    "# Technology Stack Inventory\n\n## Repository Shape\nOne WAR module.\n\n"
    '```json\n{"stacks": [' +
    ",".join(
        json.dumps({"pattern": s["pattern"], "label": s["label"], "evidence": s["evidence"]})
        for s in PRESCAN
    ) +
    '], "rejected": []}\n```'
)


def _re_output(stack: str) -> str:
    return (
        f"<!-- SECTION: ANALYSIS -->\n{stack} analysis\n"
        f"<!-- SECTION: BRD -->\n{stack} brd\n"
        f"<!-- SECTION: TECHNICAL_SPECIFICATION -->\n{stack} techspec\n"
        f"<!-- SECTION: TEST_INVENTORY -->\n{stack} tests\n"
        f"<!-- SECTION: END -->\n"
    )


EMPTY_MAPPER_REPLY = (
    "# Technology Stack Inventory\n\nNothing recognisable in this repository.\n\n"
    '```json\n{"stacks": [], "rejected": []}\n```'
)


class _Harness:
    """Stubs _run_step so no model is called, and records every invocation."""

    def __init__(self, monkeypatch, mapper_reply: str = MAPPER_REPLY):
        self.calls: list[tuple[str, str]] = []  # (step_key, pattern)

        async def fake_run_step(session_id, step_key, pattern, message, sse_event_type):
            self.calls.append((step_key, pattern))
            stack = step_key.removeprefix("discover_") if step_key.startswith("discover_") else pattern
            key = "stack_inventory" if step_key == "mapper" else "analysis"
            value = mapper_reply if step_key == "mapper" else _re_output(stack)
            await main._update_state(session_id, {key: value})

        monkeypatch.setattr(main, "_run_step", fake_run_step)
        # The real one shells out to build a per-stack graph over a workspace
        # that does not exist here.
        monkeypatch.setattr(
            main.dependency_graph, "build_dependency_graph",
            lambda *a, **k: {"nodes": [], "edges": [], "groups": []},
        )

    @property
    def re_patterns(self) -> list[str]:
        """The stacks documented, in order: wildfly by its own `re` runner, every
        other stack by its migration-neutral `discover_<stack>` agent."""
        return [step.removeprefix("discover_") if step.startswith("discover_") else p
                for step, p in self.calls if step == "re" or step.startswith("discover_")]


def _session(prescan: list[dict]) -> str:
    state = main._initial_state(
        "stack-discovery", "/tmp/ws-discovery", "/tmp/baseline-discovery", "[]",
        "bigbang", False, False, json.dumps(prescan),
    )
    session = asyncio.run(
        session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)
    )
    sid = session.id
    main._sse_queues[sid] = asyncio.Queue()
    main._brd_gates[sid] = asyncio.Event()
    main._plan_gates[sid] = asyncio.Event()
    main._companion_gates[sid] = asyncio.Event()
    return sid


#: Events drained during the last _run, keyed by session — see _run's reader.
_RECORDED: dict[str, list[dict]] = {}


def _run(sid: str, selected: list[str] | None) -> None:
    """Drive the workflow, releasing each gate the way the HTTP endpoints do.

    Gates are released off the step-change events the workflow itself emits
    rather than after a fixed number of event-loop turns: the workflow pushes
    `companion-selection` immediately before waiting on that gate, so reacting to
    the event is race-free however many awaits the stubs introduce.
    """
    recorded: list[dict] = []
    _RECORDED[sid] = recorded

    async def drive():
        task = asyncio.create_task(main._run_stack_discovery_workflow(sid))
        queue = main._sse_queues[sid]

        while not task.done() or not queue.empty():
            try:
                raw = await asyncio.wait_for(queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                break
            if raw is None:
                break
            for line in raw.splitlines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                recorded.append(event)
                if event.get("type") != "step-change":
                    continue
                if event.get("step") == "companion-selection" and selected is not None:
                    await main._update_state(
                        sid, {"companion_patterns_json": json.dumps(selected)}
                    )
                    main._companion_gates[sid].set()
                elif event.get("step") == "brd-review":
                    main._brd_gates[sid].set()

        await asyncio.wait_for(task, timeout=5.0)

    asyncio.run(drive())


def _state(sid: str) -> dict:
    return asyncio.run(main._get_state(sid))


def _events(sid: str) -> list[dict]:
    return _RECORDED.get(sid, [])


class TestStackDiscoveryWorkflow:
    def test_runs_the_mapper_then_a_discovery_agent_per_confirmed_stack(self, monkeypatch):
        harness = _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java-8-to-25", "oracle-19c-to-23ai", "wildfly"])

        assert harness.calls[0] == ("mapper", "stack-discovery")
        # STACK_ORDER: infrastructure first, application language last.
        assert harness.re_patterns == ["wildfly", "oracle-19c-to-23ai", "java-8-to-25"]

    def test_unchecked_stacks_are_not_reverse_engineered(self, monkeypatch):
        harness = _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java-8-to-25"])

        assert harness.re_patterns == ["java-8-to-25"]

    def test_document_combines_each_stack_under_its_own_heading(self, monkeypatch):
        _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java-8-to-25", "wildfly"])

        brd = _state(sid)["brd"]
        assert "## WildFly / JBoss (app server)" in brd
        assert "## Java application" in brd
        # Pattern ids name migrations; the document names stacks.
        assert "wildfly brd" in brd and "java brd" in brd and "java-8-to-25" not in brd

    def test_inventory_leads_the_document(self, monkeypatch):
        _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java-8-to-25"])

        brd = _state(sid)["brd"]
        assert brd.lstrip().startswith("## Detected Technology Stacks")
        assert brd.index("Detected Technology Stacks") < brd.index("java brd")

    def test_single_stack_still_gets_a_heading_so_edits_can_be_split_back(self, monkeypatch):
        """A migration run with one pattern skips the headings, but discovery
        always adds them — the inventory sits above them and _split_combined_sections
        needs a heading per stack to find the reviewer's edits."""
        _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["oracle-19c-to-23ai"])

        assert "## Oracle Database" in _state(sid)["brd"]

    def test_per_stack_slices_are_stored_namespaced(self, monkeypatch):
        _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java-8-to-25", "wildfly"])

        state = _state(sid)
        assert state["brd_wildfly"] == "wildfly brd"
        assert state["technical_spec_java-8-to-25"].endswith("java techspec")

    def test_nothing_confirmed_says_so_instead_of_producing_an_empty_document(self, monkeypatch):
        harness = _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, [])

        assert harness.re_patterns == []
        assert "No stacks were documented" in _state(sid)["brd"]

    def test_no_stacks_detected_skips_the_confirmation_gate(self, monkeypatch):
        """With nothing to choose between, gating would park the run on an empty
        confirmation screen forever. `selected=None` means the driver never
        releases the gate, so this deadlocks if the workflow waits on it."""
        harness = _Harness(monkeypatch, mapper_reply=EMPTY_MAPPER_REPLY)
        sid = _session([])

        _run(sid, None)

        assert harness.re_patterns == []
        assert main._companion_gates[sid].is_set()
        steps = [e.get("step") for e in _events(sid) if e.get("type") == "step-change"]
        assert "companion-selection" not in steps

    def test_run_ends_at_complete_without_a_plan_step(self, monkeypatch):
        _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java-8-to-25"])

        steps = [e.get("step") for e in _events(sid) if e.get("type") == "step-change"]
        assert steps == ["stack-mapping", "companion-selection", "reverse-engineering",
                         "brd-review", "complete"]
        assert "plan-generation" not in steps
        assert _state(sid)["plan"] == ""


class TestPlanEndpointsRejected:
    def test_confirm_plan_is_rejected_for_a_discovery_session(self):
        sid = _session(PRESCAN)

        with TestClient(main.app) as client:
            res = client.post(f"/api/sessions/{sid}/confirm-plan", json={})

        assert res.status_code == 400
        assert "reverse engineering only" in res.json()["detail"]

    def test_refine_plan_is_rejected_for_a_discovery_session(self):
        sid = _session(PRESCAN)

        with TestClient(main.app) as client:
            res = client.post(f"/api/sessions/{sid}/refine-plan", json={"feedback": "x"})

        assert res.status_code == 400

    def test_reverse_engineering_download_returns_the_whole_document(self):
        sid = _session(PRESCAN)
        asyncio.run(main._update_state(sid, {
            "brd": "the brd", "technical_spec": "the spec", "test_inventory": "the tests",
        }))

        with TestClient(main.app) as client:
            res = client.get(f"/api/sessions/{sid}/download/reverse-engineering")

        assert res.status_code == 200
        for expected in ("the brd", "the spec", "the tests"):
            assert expected in res.text

    def test_reverse_engineering_download_404s_before_anything_is_produced(self):
        sid = _session(PRESCAN)

        with TestClient(main.app) as client:
            res = client.get(f"/api/sessions/{sid}/download/reverse-engineering")

        assert res.status_code == 404
