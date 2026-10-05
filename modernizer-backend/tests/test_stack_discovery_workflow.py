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
import io
import sys
import json
import re
import zipfile

import pytest
from pathlib import Path

from fastapi.testclient import TestClient

import main
from agents import APP_NAME, USER_ID, session_service
from models.schemas import SelectCompanionsRequest

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
            if step == "ea_diagrams":
                return ('```json\n{"diagrams": [{"level": "high", "kind": "context", "title": "System context", '
                        '"nodes": [{"id": "a", "label": "Main", "type": "system", "sources": ["' + first_ev + '"]}, '
                        '{"id": "b", "label": "Java application", "type": "container", "sources": ["stack:java"]}], '
                        '"edges": [{"from": "a", "to": "b", "label": "component", "sources": ["' + first_ev + '"]}]}]}'
                        '\n```')
            if step == "po_brd":
                return (f"## Executive Summary\nThe system serves orders ({first_ev}{cite}).\n"
                        "## Business Journeys\n" + "".join(f"- journey through {label} ({first_ev})\n" for label in labels))
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


def _run(sid: str, selected: list[str] | None, screenshots: bool | None = None,
         documents: list[str] | None = None) -> None:
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
                    if documents is not None:
                        await main.select_companions(sid, SelectCompanionsRequest(
                            selected=selected, documents=documents))
                        continue
                    if screenshots is not None:
                        # Through the endpoint itself, which decides whether the choice counts.
                        await main.select_companions(sid, SelectCompanionsRequest(
                            selected=selected, screenshots=screenshots))
                        continue
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

        assert [w for w, _ in harness.writers] == ["po_brd", "ea_spec", "ea_diagrams"]
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
        # The computed list of every test file leads; the Architect's description follows.
        assert state["test_inventory"].startswith("## Test Files (computed)")
        assert state["test_inventory"].endswith("No tests found.")
        assert "java-8-to-25" not in state["brd"]

    def test_inventory_leads_and_the_evidence_check_closes_the_brd(self, monkeypatch):
        _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java"])

        state = _state(sid)
        brd, evidence = state["brd"], Path(state["evidence_path"]).read_text()
        # The BRD is the business document; the inventory and the check are in the evidence file.
        assert brd.lstrip().startswith("## Executive Summary")
        assert "Detected Technology Stacks" not in brd and "Evidence Check" not in brd and "EV-" not in brd
        assert Path(state["evidence_path"]).parent == Path(state["evidence_dir"])
        assert evidence.index("## BRD Traceability") < evidence.index("## Detected Technology Stacks") \
            < evidence.index("## Evidence Check")
        assert "Every evidence and rule id cited by either document exists." in evidence

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
        assert "`/rest/v1/jobs/{id}`" in request and "do not re-list them" in request
        assert "## Configuration Matrix (computed)" in request
        spec = state["technical_spec"]
        assert "## Interface & Job Inventory (computed)" in spec and "## Configuration Matrix (computed)" in spec
        # Every endpoint has its contract in the specification, whatever the Architect wrote.
        assert "## Endpoint Contracts (computed)" in spec
        assert "### `GET /rest/v1/jobs/{id}` — `JobRestController.get`" in spec
        evidence = Path(state["evidence_path"]).read_text()
        assert "does not mention" not in evidence                 # the catalog is complete by construction

    def test_a_citation_that_matches_no_evidence_is_reported(self, monkeypatch):
        _Harness(monkeypatch, cite=", EV-java-0999, BR-0007")
        sid = _session(PRESCAN)

        _run(sid, ["java"])

        evidence = Path(_state(sid)["evidence_path"]).read_text()
        assert "BRD: `EV-java-0999`" in evidence and "BRD: `BR-0007`" in evidence
        assert "`EV-java-0999` — **no such evidence item** (unverified)" in evidence

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


UI_PRESCAN = PRESCAN + [{"pattern": "thymeleaf", "label": "Thymeleaf server-rendered UI", "kind": "web-tier",
                         "evidence": ["src/main/resources/templates/home.html: present"]}]
UI_MAPPER_REPLY = (
    "# Technology Stack Inventory\n\n```json\n" + json.dumps({"stacks": [
        {"pattern": s["pattern"], "label": s["label"], "evidence": s["evidence"]} for s in UI_PRESCAN],
        "rejected": []}) + "\n```"
)
OFFER = {"available": True, "default": False, "stacks": ["thymeleaf"], "reason": ""}


def _fake_capture(calls: list, fail: bool = False):
    async def capture(workspace_dir, inventory, out_dir, **kwargs):
        calls.append(out_dir)
        if fail:
            raise RuntimeError(f"browser crashed in {workspace_dir}/x")
        (Path(out_dir) / "SCR-0001.png").write_bytes(b"\x89PNG fake")
        return {"pages": 1, "notes": [], "not_rendered": [], "screens": [{
            "id": "SCR-0001", "image": "SCR-0001.png", "mode": "rendered", "note": "", "state": "default",
            "description": "signed in as sample.user", "template": "src/main/resources/templates/home.html",
            "files": ["src/main/resources/templates/home.html"], "endpoint": None, "model": {"title": "x"}}]}
    return capture


class TestGrounding:
    def test_evidence_that_cannot_be_traced_never_reaches_the_writers(self, monkeypatch, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src/OrderService.java").write_text("class OrderService {\n  boolean ok(int n) { return n < 50; }\n}\n")
        monkeypatch.setattr(sys.modules[__name__], "_evidence", lambda stack: (
            "### Data\n- `src/OrderService.java:2` — `return n < 50;`: orders under 50 items are accepted\n"
            "- `src/RefundService.java:9` — refunds are paid within 5 days\n"
            "### Business Behaviour\n- Loyalty points expire after a year\n### Tests\nNone found.\n"))
        h = _Harness(monkeypatch)
        sid = _session(PRESCAN)
        asyncio.run(main._update_state(sid, {"workspace_dir": str(tmp_path)}))

        _run(sid, ["java"])

        for writer in ("po_brd", "ea_spec"):
            request = h.request(writer)
            assert "orders under 50 items" in request
            assert "RefundService" not in request and "Loyalty" not in request
        evidence = Path(_state(sid)["evidence_path"]).read_text()
        assert "## Grounding Checks" in evidence and "**Evidence items withheld from the writers:** 2" in evidence
        assert "RefundService.java" in evidence and "cites no file of the repository" in evidence


class TestUiScreens:
    def test_without_a_ui_nothing_changes(self, monkeypatch):
        calls = []
        monkeypatch.setattr(main.ui_screens, "capture", _fake_capture(calls))
        _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java"], screenshots=True)

        recs = next(e for e in _events(sid) if e.get("type") == "companion-recommendations")
        ready = next(e for e in _events(sid) if e.get("type") == "brd-ready")
        assert "screenshots" not in recs and "ui_screens" not in ready
        assert calls == [] and _state(sid)["ui_screens"] == "" and _state(sid)["ui_screenshots"] == ""

    def test_offered_but_not_chosen_produces_no_screens(self, monkeypatch):
        calls = []
        monkeypatch.setattr(main.ui_screens, "offer", lambda stacks: OFFER)
        monkeypatch.setattr(main.ui_screens, "capture", _fake_capture(calls))
        _Harness(monkeypatch, mapper_reply=UI_MAPPER_REPLY)
        sid = _session(UI_PRESCAN)

        _run(sid, ["java", "thymeleaf"], screenshots=False)

        recs = next(e for e in _events(sid) if e.get("type") == "companion-recommendations")
        assert recs["screenshots"] == OFFER
        assert calls == [] and "ui_screens" not in next(e for e in _events(sid) if e.get("type") == "brd-ready")

    def test_chosen_screens_become_their_own_document(self, monkeypatch):
        calls = []
        monkeypatch.setattr(main.ui_screens, "offer", lambda stacks: OFFER)
        monkeypatch.setattr(main.ui_screens, "capture", _fake_capture(calls))
        _Harness(monkeypatch, mapper_reply=UI_MAPPER_REPLY)
        sid = _session(UI_PRESCAN)

        _run(sid, ["java", "thymeleaf"], screenshots=True)

        state = _state(sid)
        ready = next(e for e in _events(sid) if e.get("type") == "brd-ready")
        assert len(calls) == 1 and state["ui_screenshots"] == "true"
        assert ready["ui_screens"] == state["ui_screens"]
        assert state["ui_screens"].startswith("## UI Screens") and "(screens/SCR-0001.png)" in state["ui_screens"]
        # The other documents are untouched by it.
        assert "UI Screens" not in state["brd"] + state["technical_spec"]
        assert (Path(state["ui_screens_dir"]) / "SCR-0001.png").is_file()

    def test_unchecking_the_ui_stack_turns_screenshots_off(self, monkeypatch):
        calls = []
        monkeypatch.setattr(main.ui_screens, "offer", lambda stacks: OFFER)
        monkeypatch.setattr(main.ui_screens, "capture", _fake_capture(calls))
        _Harness(monkeypatch, mapper_reply=UI_MAPPER_REPLY)
        sid = _session(UI_PRESCAN)

        _run(sid, ["java"], screenshots=True)

        assert calls == [] and _state(sid)["ui_screenshots"] == ""

    def test_an_unavailable_offer_cannot_be_chosen(self, monkeypatch):
        calls = []
        monkeypatch.setattr(main.ui_screens, "offer", lambda stacks: {**OFFER, "available": False,
                                                                      "reason": "no browser"})
        monkeypatch.setattr(main.ui_screens, "capture", _fake_capture(calls))
        _Harness(monkeypatch, mapper_reply=UI_MAPPER_REPLY)
        sid = _session(UI_PRESCAN)

        _run(sid, ["java", "thymeleaf"], screenshots=True)

        assert calls == [] and _state(sid)["ui_screens"] == ""

    def test_a_capture_failure_is_reported_and_the_documents_still_arrive(self, monkeypatch):
        calls = []
        monkeypatch.setattr(main.ui_screens, "offer", lambda stacks: OFFER)
        monkeypatch.setattr(main.ui_screens, "capture", _fake_capture(calls, fail=True))
        _Harness(monkeypatch, mapper_reply=UI_MAPPER_REPLY)
        sid = _session(UI_PRESCAN)

        _run(sid, ["java", "thymeleaf"], screenshots=True)

        state = _state(sid)
        assert "## Executive Summary" in state["brd"] and state["technical_spec"]
        assert "Screenshots could not be produced: RuntimeError: browser crashed in x" in state["ui_screens"]
        assert "/tmp/ws-discovery" not in state["ui_screens"]

    def test_a_refine_keeps_the_same_screens_document(self, monkeypatch):
        calls = []
        monkeypatch.setattr(main.ui_screens, "offer", lambda stacks: OFFER)
        monkeypatch.setattr(main.ui_screens, "capture", _fake_capture(calls))
        _Harness(monkeypatch, mapper_reply=UI_MAPPER_REPLY)
        sid = _session(UI_PRESCAN)
        _run(sid, ["java", "thymeleaf"], screenshots=True)
        before = _state(sid)["ui_screens"]

        asyncio.run(main._run_discovery_documents(sid, ["java", "thymeleaf"], feedback="shorter", target="brd"))

        assert _state(sid)["ui_screens"] == before and len(calls) == 1

    def test_screen_images_and_zip_are_served_only_for_listed_screens(self, tmp_path):
        sid = _session(PRESCAN)
        (tmp_path / "SCR-0001.png").write_bytes(b"\x89PNG one")
        (tmp_path / "SCR-0002.png").write_bytes(b"\x89PNG not listed")
        asyncio.run(main._update_state(sid, {
            "ui_screens_dir": str(tmp_path), "ui_screens": "## UI Screens\n\n![SCR-0001](screens/SCR-0001.png)\n",
            "ui_screens_json": json.dumps({"screens": [{"id": "SCR-0001", "image": "SCR-0001.png"}]})}))

        with TestClient(main.app) as client:
            ok = client.get(f"/api/sessions/{sid}/screens/SCR-0001.png")
            unlisted = client.get(f"/api/sessions/{sid}/screens/SCR-0002.png")
            traversal = client.get(f"/api/sessions/{sid}/screens/..%2F..%2Fetc%2Fpasswd")
            archive = client.get(f"/api/sessions/{sid}/download/ui-screens")

        assert ok.status_code == 200 and ok.content == b"\x89PNG one" and ok.headers["content-type"] == "image/png"
        assert unlisted.status_code == 404 and traversal.status_code == 404
        names = zipfile.ZipFile(io.BytesIO(archive.content)).namelist()
        assert archive.status_code == 200 and names == ["ui-screens.md", "screens/SCR-0001.png"]

    def test_no_zip_without_screens(self):
        sid = _session(PRESCAN)
        with TestClient(main.app) as client:
            assert client.get(f"/api/sessions/{sid}/download/ui-screens").status_code == 404


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

        assert [w for w, _ in harness.writers] == ["ea_spec", "ea_diagrams"]

    def test_a_refine_without_a_target_reruns_both_writers(self, monkeypatch):
        harness, sid = self._reviewed(monkeypatch)

        with TestClient(main.app) as client:
            client.post(f"/api/sessions/{sid}/refine-brd", json={"feedback": "x"})

        assert sorted(w for w, _ in harness.writers) == ["ea_diagrams", "ea_spec", "po_brd"] and harness.stacks == []


class TestUiInteractionContracts:
    """The UI Interaction Contracts are written a batch of screens at a time; a control
    the agent leaves out is asked for again, then filled from the computed contracts —
    every control is in the specification, in order, and nothing is abbreviated."""

    def _ui_result(self, tmp_path):
        from agents.shared import interfaces, ui_contracts
        from test_ui_contracts import FILES
        for rel, text in FILES.items():
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        inventory = interfaces.scan(str(tmp_path))
        return inventory, ui_contracts.scan(str(tmp_path), inventory)

    def test_batches_retry_and_fill(self, monkeypatch, tmp_path):
        h = _Harness(monkeypatch)
        inner = main._run_isolated
        ui_calls: list[list[str]] = []

        async def isolated(step, pattern, state, message, output_key):
            if step != "ea_ui":
                return await inner(step, pattern, state, message, output_key)
            request = state["writer_request"]
            ids = re.search(r"controls: ([^\n]+)\.", request).group(1).split(", ")
            ui_calls.append(ids)
            out = []
            for i in ids:
                if i == "UI-004" or (i == "UI-002" and len(ids) > 1):
                    continue           # UI-004 never described; UI-002 only when asked again on its own
                out.append(f"- **{i}** — described by the architect, see the computed row [...3 more fields]")
            return "### Screen\n" + "\n".join(out)

        monkeypatch.setattr(main, "_run_isolated", isolated)
        monkeypatch.setattr(main.config, "UI_CONTRACTS_BATCH_ELEMENTS", 5)
        inventory, result = self._ui_result(tmp_path)
        sid = _session(PRESCAN)
        asyncio.run(main._update_state(sid, {"interfaces_json": json.dumps(inventory),
                                             "ui_contracts_json": json.dumps(result)}))

        _run(sid, ["java"])

        ids = [e["id"] for s in result["screens"] for e in s["elements"]]
        assert len(ids) == 12
        first = [c for c in ui_calls if len(c) > 1]
        assert sum(len(c) for c in first) == 12 and all(len(c) <= 5 for c in first)   # every control, in batches
        assert ["UI-002"] in ui_calls                                                     # asked again
        spec = _state(sid)["technical_spec"]
        section = spec[spec.index("## UI Interaction Contracts"):]
        positions = [section.index(f"**{i}**") for i in ids]
        assert positions == sorted(positions)                                             # in the screens' order
        assert "**UI-004** — " in section and "the writer did not describe this control" in section
        assert section.count("described by the architect") == 11
        assert "[...3 more fields]" not in spec and "every control is listed in the computed" in spec
        evidence = Path(_state(sid)["evidence_path"]).read_text()
        assert "did not describe (1)" in evidence and "UI-004" in evidence
        assert "### Abbreviated lists replaced in the technical documents" in evidence
        assert "## Endpoint Contracts (computed)" in spec and "### Web pages and templates (3)" in spec
        assert "Interface Overview" in h.request("ea_spec") or "do not re-list them" in h.request("ea_spec")


class TestArchitectureDiagrams:
    """The architect declares the diagrams; the pipeline checks, draws, places and serves them."""

    def test_declared_diagrams_are_drawn_placed_and_served(self, monkeypatch):
        pytest.importorskip("PIL")
        _Harness(monkeypatch)
        sid = _session(PRESCAN)

        _run(sid, ["java"])

        state = _state(sid)
        spec = state["technical_spec"]
        assert "## Architecture Diagrams" in spec and "### High-level design" in spec
        assert "![HLD-1 — System context](diagrams/HLD-1.png)" in spec
        assert spec.index("## Architecture Overview") < spec.index("## Architecture Diagrams")
        assert json.loads(state["diagram_files_json"]) == ["HLD-1.png"]
        with TestClient(main.app) as client:
            image = client.get(f"/api/sessions/{sid}/diagrams/HLD-1.png")
            assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
            assert client.get(f"/api/sessions/{sid}/diagrams/..%2Fsecret.png").status_code == 404
            assert client.get(f"/api/sessions/{sid}/diagrams/LLD-9.png").status_code == 404
            docx = client.get(f"/api/sessions/{sid}/download/technical-spec?format=docx")
            with zipfile.ZipFile(io.BytesIO(docx.content)) as archive:
                assert any(n.startswith("word/media/") for n in archive.namelist())
            bundle = client.get(f"/api/sessions/{sid}/download/technical-spec?format=zip")
            with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
                assert sorted(archive.namelist()) == ["diagrams/HLD-1.png", "technical-spec.md"]


class TestChosenDocuments:
    """Only the documents the reviewer chose are generated — and only the work they need runs."""

    def _setup(self, monkeypatch, offer: bool = False):
        h = _Harness(monkeypatch)
        rules: list[str] = []

        async def fake_rules(session_id):
            rules.append(session_id)
        monkeypatch.setattr(main, "_run_rules_extraction", fake_rules)

        async def fake_screens(session_id):
            await main._update_state(session_id, {"ui_screens_json": json.dumps(
                {"screens": [], "not_rendered": [], "pages": 0, "notes": ["rendered by the stub"]})})
        monkeypatch.setattr(main, "_run_ui_screens", fake_screens)
        sid = _session(PRESCAN)
        if offer:
            asyncio.run(main._update_state(sid, {"ui_screens_offer_json": json.dumps(
                {"available": True, "default": False, "stacks": ["java"], "reason": ""})}))
        return h, rules, sid

    def test_brd_only(self, monkeypatch):
        h, rules, sid = self._setup(monkeypatch)
        _run(sid, ["java"], documents=["brd"])
        state = _state(sid)
        assert [w for w, _ in h.writers] == ["po_brd"] and rules == [sid]
        assert "## Executive Summary" in state["brd"]
        assert state["technical_spec"] == "" and state["test_inventory"] == "" and state["ui_screens"] == ""
        assert json.loads(state["documents_json"]) == ["brd"]

    def test_technical_specification_only(self, monkeypatch):
        h, rules, sid = self._setup(monkeypatch)
        _run(sid, ["java"], documents=["technical_spec"])
        state = _state(sid)
        assert [w for w, _ in h.writers] == ["ea_spec", "ea_diagrams"] and rules == []    # no business rules
        assert "Only the Existing Test Inventory" not in h.request("ea_spec")
        assert state["brd"] == "" and state["test_inventory"] == ""
        assert "## Architecture Overview" in state["technical_spec"]

    def test_test_cases_only(self, monkeypatch):
        h, rules, sid = self._setup(monkeypatch)
        _run(sid, ["java"], documents=["test_inventory"])
        state = _state(sid)
        assert [w for w, _ in h.writers] == ["ea_spec"] and rules == []                   # no diagrams, no UI
        assert "## Only the Existing Test Inventory is wanted" in h.request("ea_spec")
        assert state["brd"] == "" and state["technical_spec"] == ""
        assert state["test_inventory"].startswith("## Test Files (computed)")

    def test_ui_screens_only_runs_no_agent(self, monkeypatch):
        h, rules, sid = self._setup(monkeypatch, offer=True)
        _run(sid, ["java"], documents=["ui_screens"])
        state = _state(sid)
        assert h.writers == [] and h.re_patterns == [] and rules == []                     # no model at all
        assert state["brd"] == "" and state["technical_spec"] == "" and state["test_inventory"] == ""
        assert "rendered by the stub" in state["ui_screens"]
        ready = [e for e in _RECORDED[sid] if e.get("type") == "brd-ready"][-1]
        assert ready["ui_screens"] and not ready["brd"]

    def test_two_documents(self, monkeypatch):
        h, rules, sid = self._setup(monkeypatch, offer=True)
        _run(sid, ["java"], documents=["brd", "ui_screens"])
        state = _state(sid)
        assert [w for w, _ in h.writers] == ["po_brd"] and state["brd"] and state["ui_screens"]
        assert state["technical_spec"] == "" and state["test_inventory"] == ""

    def test_a_choice_is_required_and_ui_screens_needs_the_offer(self, monkeypatch):
        _, _, sid = self._setup(monkeypatch)
        asyncio.run(main._update_state(sid, {"companion_recommendations_json": json.dumps(
            [{"pattern": "java", "label": "Java", "evidence": []}])}))
        for documents in ([], ["ui_screens"]):
            with pytest.raises(main.HTTPException) as err:
                asyncio.run(main.select_companions(sid, SelectCompanionsRequest(selected=["java"], documents=documents)))
            assert err.value.status_code == 400
        assert not main._companion_gates[sid].is_set()

    def test_without_a_choice_the_earlier_documents_are_produced(self, monkeypatch):
        h, rules, sid = self._setup(monkeypatch)
        _run(sid, ["java"], screenshots=False)
        state = _state(sid)
        assert json.loads(state["documents_json"]) == ["brd", "technical_spec", "test_inventory"]
        assert state["brd"] and state["technical_spec"] and state["test_inventory"]

    def test_refine_and_download_respect_the_choice(self, monkeypatch):
        _, _, sid = self._setup(monkeypatch)
        _run(sid, ["java"], documents=["technical_spec"])
        main._brd_gates[sid] = asyncio.Event()
        with TestClient(main.app) as client:
            refused = client.post(f"/api/sessions/{sid}/refine-brd", json={"feedback": "x", "target": "brd"})
            assert refused.status_code == 400
            combined = client.get(f"/api/sessions/{sid}/download/reverse-engineering?format=md").text
            assert "# Technical Specification" in combined and "# Business Requirements" not in combined
