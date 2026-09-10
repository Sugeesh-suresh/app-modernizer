"""
Integration tests for the confirm-plan endpoint's companion-bundle behaviour.

The reviewer edits the *combined* plan in the UI, but each pattern's modifier
agent only ever reads its own `plan_<pattern>` slice — so confirm-plan has to
split the edits back out. These tests pin that wiring, since a regression here
would silently execute the un-edited plan.
"""
import asyncio

from fastapi.testclient import TestClient

import main
from agents import APP_NAME, USER_ID, session_service

COMBINED = (
    "## Java 8 → Java 25\n\n"
    "Bump the compiler release to 25.\n\n"
    "---\n\n"
    "## Oracle 19c → 23ai\n\n"
    "Replace the ojdbc8 driver.\n"
)


def _make_session(overrides: dict) -> str:
    state = main._initial_state(
        "java-8-to-25", "/tmp/ws", "/tmp/baseline", "[]", "bigbang", False, False,
    )
    state.update(overrides)
    session = asyncio.run(
        session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)
    )
    main._plan_gates[session.id] = asyncio.Event()
    return session.id


def _confirm_plan(session_id: str, body: dict) -> int:
    with TestClient(main.app) as client:
        return client.post(f"/api/sessions/{session_id}/confirm-plan", json=body).status_code


class TestConfirmPlanBundle:
    def test_reviewer_edits_reach_each_patterns_own_slice(self):
        session_id = _make_session({
            "companion_patterns_json": '["oracle-19c-to-23ai"]',
            "plan": COMBINED,
            "plan_java-8-to-25": "Bump the compiler release to 25.",
            "plan_oracle-19c-to-23ai": "Replace the ojdbc8 driver.",
        })
        edited = COMBINED.replace("release to 25", "release to 21 for now")

        assert _confirm_plan(session_id, {"content": edited}) == 200

        state = asyncio.run(main._get_state(session_id))
        assert state["plan_java-8-to-25"] == "Bump the compiler release to 21 for now."
        assert state["plan_oracle-19c-to-23ai"] == "Replace the ojdbc8 driver."
        assert state["plan"] == edited

    def test_feedback_is_attached_to_every_pattern_not_just_the_last(self):
        session_id = _make_session({
            "companion_patterns_json": '["oracle-19c-to-23ai"]',
            "plan": COMBINED,
        })

        assert _confirm_plan(session_id, {"feedback": "Keep the WAR packaging."}) == 200

        state = asyncio.run(main._get_state(session_id))
        assert "Keep the WAR packaging." in state["plan_java-8-to-25"]
        assert "Keep the WAR packaging." in state["plan_oracle-19c-to-23ai"]

    def test_standalone_run_is_untouched_by_the_split(self):
        session_id = _make_session({"plan": "A single-pattern plan.", "plan_java-8-to-25": "A single-pattern plan."})

        assert _confirm_plan(session_id, {"content": "An edited single-pattern plan."}) == 200

        state = asyncio.run(main._get_state(session_id))
        # No companions: the combined plan IS the plan, and the per-pattern slice
        # is left exactly as generated (code generation falls back to state["plan"]).
        assert state["plan"] == "An edited single-pattern plan."
        assert state["plan_java-8-to-25"] == "A single-pattern plan."

    def test_gate_is_released_so_the_workflow_advances(self):
        session_id = _make_session({"plan": COMBINED})

        assert _confirm_plan(session_id, {"content": COMBINED}) == 200

        assert main._plan_gates[session_id].is_set()

    def test_unknown_session_is_rejected(self):
        with TestClient(main.app) as client:
            res = client.post("/api/sessions/does-not-exist/confirm-plan", json={"content": "x"})

        assert res.status_code == 404
