"""
ADK agent registry for the App Modernizer.

PATTERN_RUNNERS maps each migration pattern to its per-step Runners.
All runners share a single session service so ADK session state
(analysis, brd, plan, generated_code_raw, additional_context, …) persists
across the full pipeline for the same session.
"""
import os
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from .java17_to_java25.agents import (
    re_agent as j17_re, brd_agent as j17_brd, plan_agent as j17_plan,
    code_agent as j17_code, test_agent as j17_test,
    validate_agent as j17_validate, fix_agent as j17_fix,
)
from .java_to_go.agents import (
    re_agent as go_re, brd_agent as go_brd, plan_agent as go_plan,
    code_agent as go_code, test_agent as go_test,
    validate_agent as go_validate, fix_agent as go_fix,
)
from .java_to_quarkus.agents import (
    re_agent as qk_re, brd_agent as qk_brd, plan_agent as qk_plan,
    code_agent as qk_code, test_agent as qk_test,
    validate_agent as qk_validate, fix_agent as qk_fix,
)
from .tibco_to_springboot.agents import (
    re_agent as tibco_re, brd_agent as tibco_brd, plan_agent as tibco_plan,
    code_agent as tibco_code, test_agent as tibco_test,
    validate_agent as tibco_validate, fix_agent as tibco_fix,
)

APP_NAME = "modernizer"
USER_ID = "default"  # single-tenant; swap for real user IDs when auth is added

_db_url = os.getenv("DATABASE_URL")
if _db_url:
    # Lazy import: sqlalchemy (pulled in by google-adk[db]) is only required
    # when DATABASE_URL is set. The in-memory path has no extra dependencies.
    from google.adk.sessions import DatabaseSessionService
    session_service = DatabaseSessionService(db_url=_db_url)
else:
    session_service = InMemorySessionService()


def _runner(agent) -> Runner:
    return Runner(app_name=APP_NAME, agent=agent, session_service=session_service)


PATTERN_RUNNERS: dict[str, dict[str, Runner]] = {
    "java17-to-java25": {
        "re":       _runner(j17_re),
        "brd":      _runner(j17_brd),
        "plan":     _runner(j17_plan),
        "code":     _runner(j17_code),
        "test":     _runner(j17_test),
        "validate": _runner(j17_validate),
        "fix":      _runner(j17_fix),
    },
    "java-to-go": {
        "re":       _runner(go_re),
        "brd":      _runner(go_brd),
        "plan":     _runner(go_plan),
        "code":     _runner(go_code),
        "test":     _runner(go_test),
        "validate": _runner(go_validate),
        "fix":      _runner(go_fix),
    },
    "java-to-quarkus": {
        "re":       _runner(qk_re),
        "brd":      _runner(qk_brd),
        "plan":     _runner(qk_plan),
        "code":     _runner(qk_code),
        "test":     _runner(qk_test),
        "validate": _runner(qk_validate),
        "fix":      _runner(qk_fix),
    },
    "tibco-to-springboot": {
        "re":       _runner(tibco_re),
        "brd":      _runner(tibco_brd),
        "plan":     _runner(tibco_plan),
        "code":     _runner(tibco_code),
        "test":     _runner(tibco_test),
        "validate": _runner(tibco_validate),
        "fix":      _runner(tibco_fix),
    },
}

TARGET_LANGS: dict[str, str] = {
    "java17-to-java25":    "java",
    "java-to-go":          "go",
    "java-to-quarkus":     "java",
    "tibco-to-springboot": "java",
}
