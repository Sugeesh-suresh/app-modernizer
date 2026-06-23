"""
ADK agent registry for the App Modernizer.

Each pattern has 3 runners: re (reverse-engineering + BRD + TechSpec),
plan, and code. The BRD is generated inside the RE step.
"""
import os
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from .java17_to_java25.agents import (
    re_agent as j17_re, plan_agent as j17_plan, code_agent as j17_code,
)
from .java_to_go.agents import (
    re_agent as go_re, plan_agent as go_plan, code_agent as go_code,
)
from .java_to_quarkus.agents import (
    re_agent as qk_re, plan_agent as qk_plan, code_agent as qk_code,
)
from .tibco_to_springboot.agents import (
    re_agent as tibco_re, plan_agent as tibco_plan, code_agent as tibco_code,
)

APP_NAME = "modernizer"
USER_ID = "default"

_db_url = os.getenv("DATABASE_URL")
if _db_url:
    from google.adk.sessions import DatabaseSessionService
    session_service = DatabaseSessionService(db_url=_db_url)
else:
    session_service = InMemorySessionService()


def _runner(agent) -> Runner:
    return Runner(app_name=APP_NAME, agent=agent, session_service=session_service)


PATTERN_RUNNERS: dict[str, dict[str, Runner]] = {
    "java17-to-java25": {
        "re":   _runner(j17_re),
        "plan": _runner(j17_plan),
        "code": _runner(j17_code),
    },
    "java-to-go": {
        "re":   _runner(go_re),
        "plan": _runner(go_plan),
        "code": _runner(go_code),
    },
    "java-to-quarkus": {
        "re":   _runner(qk_re),
        "plan": _runner(qk_plan),
        "code": _runner(qk_code),
    },
    "tibco-to-springboot": {
        "re":   _runner(tibco_re),
        "plan": _runner(tibco_plan),
        "code": _runner(tibco_code),
    },
}

TARGET_LANGS: dict[str, str] = {
    "java17-to-java25":    "java",
    "java-to-go":          "go",
    "java-to-quarkus":     "java",
    "tibco-to-springboot": "java",
}
