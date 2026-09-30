"""
The truncation warning has to reach the document a human approves.

Counting what was left behind is only half the fix. The other half is that the
count arrives where the decision is made: the BRD and Technical Specification are
what somebody reads and signs off before a plan is built from them, and if those
read as a complete account of the repository while being derived from a partial
one, the accurate count in the upload response has changed nothing.

This spans the upload handler, _initial_state and _run_bundle_re, so it is pinned
end to end rather than per function.
"""
import asyncio
import json

import pytest

import main
from agents import APP_NAME, USER_ID, config, session_service

_RE_OUTPUT = (
    "<!-- SECTION: ANALYSIS -->\nanalysis body\n"
    "<!-- SECTION: BRD -->\nthe brd body\n"
    "<!-- SECTION: TECHNICAL_SPECIFICATION -->\nthe spec body\n"
    "<!-- SECTION: TEST_INVENTORY -->\nthe test body\n"
    "<!-- SECTION: END -->\n"
)


@pytest.fixture
def stub_re(monkeypatch):
    # These pin the agent path; the inventory path has its own test below.
    monkeypatch.setattr(config, "MIGRATION_ANALYSIS", "agent")
    async def fake_run_step(session_id, step_key, pattern, message, sse_event_type):
        await main._update_state(session_id, {"analysis": _RE_OUTPUT})

    monkeypatch.setattr(main, "_run_step", fake_run_step)
    monkeypatch.setattr(
        main.dependency_graph, "build_dependency_graph",
        lambda *a, **k: {"nodes": [], "edges": [], "groups": []},
    )


def _session(ingestion_warning: str) -> str:
    state = main._initial_state(
        "java-8-to-25", "/tmp/ws-warn", "/tmp/base-warn",
        json.dumps({"nodes": [], "edges": [], "groups": []}),
        "bigbang", False, False, ingestion_warning=ingestion_warning,
    )
    sid = asyncio.run(
        session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)
    ).id
    main._sse_queues[sid] = asyncio.Queue()
    return sid


def _events(sid: str) -> list[dict]:
    out, q = [], main._sse_queues[sid]
    while not q.empty():
        raw = q.get_nowait()
        if not raw:
            continue
        for line in raw.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


class TestWarningReachesTheDocument:
    def test_banner_leads_the_brd_and_the_technical_spec(self, stub_re):
        sid = _session("**3 of 10 files were not unpacked** because the limit was reached.")

        asyncio.run(main._run_bundle_re(sid, ["java-8-to-25"]))

        state = asyncio.run(main._get_state(sid))
        for key in ("brd", "technical_spec"):
            assert state[key].lstrip().startswith("> ⚠️ **Incomplete repository.**"), key
            assert "3 of 10 files were not unpacked" in state[key], key

    def test_the_agent_output_is_kept_not_replaced(self, stub_re):
        sid = _session("**3 of 10 files were not unpacked**.")

        asyncio.run(main._run_bundle_re(sid, ["java-8-to-25"]))

        state = asyncio.run(main._get_state(sid))
        assert "the brd body" in state["brd"]
        assert "the spec body" in state["technical_spec"]

    def test_the_brd_ready_event_carries_it_too(self, stub_re):
        """The UI renders from the SSE payload, not from a later state read."""
        sid = _session("**3 of 10 files were not unpacked**.")

        asyncio.run(main._run_bundle_re(sid, ["java-8-to-25"]))

        ready = next(e for e in _events(sid) if e["type"] == "brd-ready")
        assert "Incomplete repository" in ready["brd"]
        assert "Incomplete repository" in ready["technical_spec"]

    def test_a_complete_upload_adds_no_banner(self, stub_re):
        """A warning on every run would train reviewers to ignore it."""
        sid = _session("")

        asyncio.run(main._run_bundle_re(sid, ["java-8-to-25"]))

        state = asyncio.run(main._get_state(sid))
        assert "Incomplete repository" not in state["brd"]
        assert state["brd"].strip() == "the brd body"

    def test_banner_leads_the_inventory_document_too(self, monkeypatch, tmp_path):
        """java-8-to-25 analyses with the deterministic inventory by default; an
        inventory of a partial upload is just as partial."""
        monkeypatch.setattr(config, "MIGRATION_ANALYSIS", "inventory")
        state = main._initial_state("java-8-to-25", str(tmp_path), str(tmp_path), "[]", "bigbang", False, False,
                                    ingestion_warning="**3 of 10 files were not unpacked**.")
        sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
        main._sse_queues[sid] = asyncio.Queue()

        asyncio.run(main._run_bundle_re(sid, ["java-8-to-25"]))

        state = asyncio.run(main._get_state(sid))
        for key in ("brd", "technical_spec"):
            assert state[key].lstrip().startswith("> ⚠️ **Incomplete repository.**"), key
        assert "no language model read this repository" in state["brd"]

    def test_a_truncated_upload_populates_the_state_key(self, tmp_path, monkeypatch):
        """Closes the loop from the extraction itself, not a hand-written string."""
        monkeypatch.setattr(config, "WORKSPACE_MAX_FILES", 4)
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i in range(12):
                zf.writestr(f"src/F{i}.java", "class X {}")

        extraction = main._extract_zip_to_dir(buf.getvalue(), tmp_path)
        state = main._initial_state(
            "java-8-to-25", str(tmp_path), "/tmp/b", "[]", "bigbang", False, False,
            ingestion_warning=extraction.warning(),
        )

        assert extraction.truncated == 8
        assert "8 of 12 files were not unpacked" in state["ingestion_warning"]


class TestDependencyGraphInjectionIsShapeSafe:
    """`"[]"` is a real value for dependency_graph_json — _create_pattern_session
    seeds it for a bundled code-generation session. Valid JSON of the wrong shape
    used to raise AttributeError rather than being ignored."""

    @pytest.mark.parametrize("graph_json", ["[]", '"text"', "null", "42", "", "{not json"])
    def test_non_dict_graph_is_ignored_rather_than_fatal(self, graph_json):
        assert main._inject_dependency_graph("SPEC", graph_json, "java-8-to-25") == "SPEC"

    def test_a_real_graph_is_still_prepended(self):
        graph_json = json.dumps({"nodes": ["A.java"], "edges": [], "groups": [["A.java"]]})

        out = main._inject_dependency_graph("SPEC", graph_json, "java-8-to-25")

        assert out.endswith("SPEC")
        assert "A.java" in out
