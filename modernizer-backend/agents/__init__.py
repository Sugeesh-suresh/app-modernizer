"""
ADK agent registry for the App Modernizer.

Each pattern normally has 3 runners: re (reverse-engineering + BRD +
TechSpec), plan, and code. The BRD is generated inside the RE step.

Direct-upgrade patterns (e.g. dotnet4-to-dotnet8) omit the "re" runner
entirely — main.py's workflow detects this and skips the reverse-
engineering / BRD-review phase, going straight from upload to plan
generation using the raw source code.
"""
import os
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from .java11_to_java25.agents import (
    plan_pipeline as j11_plan_pipeline, code_pipeline as j11_code_pipeline,
)
from .java17_to_java25.agents import (
    re_agent as j17_re, plan_agent as j17_plan, code_agent as j17_code,
)
from .java_to_go.agents import (
    re_agent as go_re, plan_agent as go_plan, code_agent as go_code,
)
from .java_to_quarkus.agents import (
    re_agent as qk_re, plan_agent as qk_plan, code_pipeline as qk_code_pipeline,
)
from .tibco_to_springboot.agents import (
    re_agent as tibco_re, plan_agent as tibco_plan, code_agent as tibco_code,
)
from .dotnet4_to_dotnet8.agents import (
    plan_agent as net8_plan, code_agent as net8_code,
)
from .dotnet8_to_dotnet9.agents import (
    plan_agent as net9_plan, code_agent as net9_code,
)
from .dotnet9_to_dotnet10.agents import (
    plan_agent as net10_plan, code_agent as net10_code,
)
from .dotnet10_to_dotnet11.agents import (
    plan_agent as net11_plan, code_agent as net11_code,
)
from .dotnet_to_java.agents import (
    re_agent as netjava_re, plan_agent as netjava_plan, code_agent as netjava_code,
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
    "java11-to-java25": {
        # No "re" runner — direct upgrade pattern, skips reverse-engineering / BRD review.
        "plan": _runner(j11_plan_pipeline),  # SequentialAgent: scanner_agent -> planner_agent
        "code": _runner(j11_code_pipeline),  # SequentialAgent: modifier_agent -> LoopAgent(validate, fix, max=3) -> reporter_agent
    },
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
        "code": _runner(qk_code_pipeline),  # SequentialAgent: code → LoopAgent(validate, fix, max=4)
    },
    "tibco-to-springboot": {
        "re":   _runner(tibco_re),
        "plan": _runner(tibco_plan),
        "code": _runner(tibco_code),
    },
    "dotnet4-to-dotnet8": {
        # No "re" runner — direct upgrade pattern, skips reverse-engineering / BRD review.
        "plan": _runner(net8_plan),
        "code": _runner(net8_code),
    },
    "dotnet8-to-dotnet9": {
        # No "re" runner — direct upgrade pattern, skips reverse-engineering / BRD review.
        "plan": _runner(net9_plan),
        "code": _runner(net9_code),
    },
    "dotnet9-to-dotnet10": {
        # No "re" runner — direct upgrade pattern, skips reverse-engineering / BRD review.
        "plan": _runner(net10_plan),
        "code": _runner(net10_code),
    },
    "dotnet10-to-dotnet11": {
        # No "re" runner — direct upgrade pattern, skips reverse-engineering / BRD review.
        "plan": _runner(net11_plan),
        "code": _runner(net11_code),
    },
    "dotnet-to-java": {
        "re":   _runner(netjava_re),
        "plan": _runner(netjava_plan),
        "code": _runner(netjava_code),
    },
}

TARGET_LANGS: dict[str, str] = {
    "java11-to-java25":    "java",
    "java17-to-java25":    "java",
    "java-to-go":          "go",
    "java-to-quarkus":     "java",
    "tibco-to-springboot": "java",
    "dotnet4-to-dotnet8":  "csharp",
    "dotnet8-to-dotnet9":  "csharp",
    "dotnet9-to-dotnet10": "csharp",
    "dotnet10-to-dotnet11": "csharp",
    "dotnet-to-java":      "java",
}
