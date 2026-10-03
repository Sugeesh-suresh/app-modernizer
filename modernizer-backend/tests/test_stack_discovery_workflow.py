"""
Integration tests for the stack-discovery workflow end to end, with the agent
calls stubbed out.

Verifies the wiring no unit test can reach: that the mapper's result gates on the
reviewer's confirmation, that each confirmed stack's evidence specialist runs once,
that the Product Owner and Enterprise Architect writers both work from that
evidence, that the inventory leads the BRD, that a refine re-runs only the writer
of the refined document, and that the run stops at brd-review instead of falling
through to plan generation.
"""
import asyncio
import json
import re

from fastapi.testclient import TestClient

import main
from agents import APP_NAME, USER_ID, session_service

PRESCAN = [
    {"pattern": "wildfly", "label": "WildFly / JBoss (app server)", "kind": "server",
     "evidence": ["standalone.xml: present"]},
    {"pattern": "oracle", "label": "Oracle Database", "kind": "database",
     "evidence": ["pom.xml: matched `ojdbc8`"]},
    {"pattern": "java", "label": "Java application", "kind": "application",
     "evidence": ["src/A.java: present"]},
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


def _evidence(stack: str) -> str:
    return (f"### Components\n- `{stack}/Main` — the {stack} component\n"
            f"### Business Behaviour\n- {stack} behaviour: orders are checked\n"
            "### Tests\nNone found.\n")


EMPTY_MAPPER_REPLY = (
    "# Technology Stack Inventory\n\nNothing recognisable in this repository.\n\n"
    '```json\n{"stacks": [], "rejected": []}\n```'
)


class _Harness:
    """Stubs the agents so no model is called, and records every invocation:
    evidence specialists through _run_step, writers through _run_isolated."""

    def __init__(self, monkeypatch, mapper_reply: str = MAPPER_REPLY, cite: str = ""):
        self.calls: list[tuple[str, str]] = []   # (step_key, pattern)
        self.stacks: list[tuple[str, str]] = []  # (step_key, stack whose evidence was gathered)
        self.writers: list[tuple[str, str]] = []  # (writer, request)

        async def fake_run_step(session_id, step_key, pattern, message, sse_event_type):
            self.calls.append((step_key, pattern))
            named = re.search(r"\(id `([^`]+)`", message)
            stack = named.group(1) if named else pattern
            if step_key == "mapper":
                await main._update_state(session_id, {"stack_inventory": mapper_reply})
            else:
                self.stacks.append((step_key, stack))
                await main._update_state(session_id, {"analysis": _evidence(stack)})

        async def fake_isolated(step, pattern, state, message, output_key):
            request = state.get("writer_request", "")
            self.writers.append((step, request))
            labels = re.findall(r"^- (.+?) \(id `", request, re.M)
            first_ev = (re.findall(r"\[(EV-[^\]]+)\]", request) or [""])[0]
            if step == "po_brd":
                return (f"## Executive Summary\nThe system serves orders ({first_ev}{cite}).\n"
                        "## Business Journeys\n" + "".join(f"- journey through {label}\n" for label in labels))
            return ("<!-- SECTION: TECHNICAL_SPECIFICATION -->\n## Architecture Overview\noverview "
                    f"({first_ev})\n## Per-Stack Detail\n" + "".join(f"### {label}\ncomponents\n" for label in labels)
                    + "<!-- SECTION: TEST_INVENTORY -->\nNo tests found.\n<!-- SECTION: END -->")

        monkeypatch.setattr(main, "_run_step", fake_run_step)
        monkeypatch.setattr(main, "_run_isolated", fake_isolated)
        # The real one shells out to build a per-stack graph over a workspace
        # that does not exist here.
        monkeypatch.setattr(
            main.dependency_graph, "build_dependency_graph",
            lambda *a, **k: {"nodes": [], "edges": [], "groups": []},
        )

    @property
    def re_patterns(self) -> list[str]:
        """The stacks whose evidence was gathered, in order: wildfly by its own
        `re` runner, every other stack by the one discovery agent."""
        return [s for step, s in self.stacks if step in ("re", "discover")]

    def request(self, writer: str) -> str:
        return next(r for w, r in self.writers if w == writer)


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

        _run(sid, ["java", "oracle", "wildfly"])

        assert harness.calls[0] == ("mapper", "stack-discovery")
        # STACK_ORDER: infrastructure first, application language last.
        assert harness.re_patterns == ["wildfly", "oracle", "java"]

    def test_unchecked_stacks_are_not_reverse_engineered(self, monkeypatch):
        harness = _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java"])

        assert harness.re_patterns == ["java"]

    def test_both_writers_work_from_every_confirmed_stacks_evidence(self, monkeypatch):
        harness = _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java", "wildfly"])

        assert [w for w, _ in harness.writers] == ["po_brd", "ea_spec"]
        for writer in ("po_brd", "ea_spec"):
            request = harness.request(writer)
            assert "WildFly / JBoss (app server) (id `wildfly`" in request and "Java application (id `java`" in request
        po, ea = harness.request("po_brd"), harness.request("ea_spec")
        assert "[EV-java-0002] java behaviour" in po and "[EV-java-0001]" not in po     # PO view: behaviour, not components
        assert "[EV-java-0001] `java/Main`" in ea and "java behaviour" not in ea           # EA view: components
        assert "## Business-Rules Catalog (brief)" in po and "## Repository Facts" in ea

    def test_the_brd_is_the_product_owners_and_the_specification_the_architects(self, monkeypatch):
        _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java", "wildfly"])

        state = _state(sid)
        assert "## Executive Summary" in state["brd"] and "journey through Java application" in state["brd"]
        assert "## Architecture Overview" in state["technical_spec"] and "Executive Summary" not in state["technical_spec"]
        assert "### WildFly / JBoss (app server)" in state["technical_spec"]
        assert state["test_inventory"] == "No tests found."
        assert "java-8-to-25" not in state["brd"]

    def test_inventory_leads_and_the_evidence_check_closes_the_brd(self, monkeypatch):
        _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java"])

        brd = _state(sid)["brd"]
        assert brd.lstrip().startswith("## Detected Technology Stacks")
        assert brd.index("Detected Technology Stacks") < brd.index("## Executive Summary") < brd.index("## Evidence Check")
        assert "Every evidence and rule id cited by either document exists." in brd

    def test_computed_interfaces_and_configuration_reach_the_architect_and_the_check(self, monkeypatch):
        h = _Harness(monkeypatch)
        sid = _session(PRESCAN)
        inventory = {"endpoints": [{"verb": "GET", "path": "/rest/v1/jobs/{id}", "handler": "JobRestController.get",
                                    "kind": "REST", "view": "", "source": "src/JobRestController.java:12"}],
                     "jobs": [{"handler": "JobController.nightly", "schedule": "cron = 0 0 2 * * *", "zone": "",
                               "source": "src/JobController.java:20"}],
                     "listeners": []}
        asyncio.run(main._update_state(sid, {
            "interfaces_json": json.dumps(inventory),
            "config_matrix_markdown": "## Configuration Matrix (computed)\n\n| Key | default |"}))

        _run(sid, ["java"])

        state = _state(sid)
        request = h.request("ea_spec")
        assert "`/rest/v1/jobs/{id}`" in request and "must appear in your Interface Catalog" in request
        assert "## Configuration Matrix (computed)" in request
        assert "## Interface & Job Inventory (computed)" in state["technical_spec"]
        assert "## Configuration Matrix (computed)" in state["technical_spec"]
        # The stub architect mentions neither, so the evidence check names both.
        assert "GET /rest/v1/jobs/{id} (JobRestController.get)" in state["brd"]
        assert "scheduled job JobController.nightly" in state["brd"]

    def test_a_citation_that_matches_no_evidence_is_reported(self, monkeypatch):
        _Harness(monkeypatch, cite=", EV-java-0999, BR-0007")
        sid = _session(PRESCAN)

        _run(sid, ["java"])

        brd = _state(sid)["brd"]
        assert "BRD: `EV-java-0999`" in brd and "BRD: `BR-0007`" in brd

    def test_evidence_packs_are_numbered_and_kept_on_disk(self, monkeypatch):
        _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java", "wildfly"])

        state = _state(sid)
        pack = (main.Path(state["evidence_dir"]) / "java.md").read_text()
        assert "- [EV-java-0001] `java/Main`" in pack and "- [EV-java-0002] java behaviour" in pack
        assert state["evidence_count"] == "4"
        assert not any(k.startswith("brd_") for k in state if k.endswith(("java", "wildfly")) and state[k])

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

        _run(sid, ["java"])

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


class TestRefineTargetsOneWriter:
    def _reviewed(self, monkeypatch):
        harness = _Harness(monkeypatch)
        sid = _session(PRESCAN)
        main._brd_gates[sid] = asyncio.Event()             # stays open: the review is in progress
        asyncio.run(main._update_state(sid, {"companion_patterns_json": json.dumps(["java"])}))
        asyncio.run(main._run_discovery_documents(sid, ["java"]))
        harness.calls.clear(), harness.writers.clear(), harness.stacks.clear()
        return harness, sid

    def test_refining_the_brd_reruns_only_the_product_owner_from_stored_evidence(self, monkeypatch):
        harness, sid = self._reviewed(monkeypatch)
        before = _state(sid)["technical_spec"]

        with TestClient(main.app) as client:
            res = client.post(f"/api/sessions/{sid}/refine-brd", json={"feedback": "more on refunds", "target": "brd"})

        assert res.status_code == 200, res.text
        assert harness.stacks == [] and [w for w, _ in harness.writers] == ["po_brd"]
        assert "## Reviewer Feedback\nmore on refunds" in harness.request("po_brd")
        assert "## Your Previous Document (revise it)" in harness.request("po_brd")
        assert _state(sid)["technical_spec"] == before

    def test_refining_the_technical_documents_reruns_only_the_architect(self, monkeypatch):
        harness, sid = self._reviewed(monkeypatch)

        with TestClient(main.app) as client:
            client.post(f"/api/sessions/{sid}/refine-brd", json={"feedback": "x", "target": "technical_spec"})

        assert [w for w, _ in harness.writers] == ["ea_spec"]

    def test_a_refine_without_a_target_reruns_both_writers(self, monkeypatch):
        harness, sid = self._reviewed(monkeypatch)

        with TestClient(main.app) as client:
            client.post(f"/api/sessions/{sid}/refine-brd", json={"feedback": "x"})

        assert sorted(w for w, _ in harness.writers) == ["ea_spec", "po_brd"] and harness.stacks == []
