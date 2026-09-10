"""
ADK agent registry for the App Modernizer.

All 4 patterns share one shape: `re` (reverse-engineering -> Analysis/BRD/
TechSpec/Test Inventory) -> HITL brd-review -> `plan` (from confirmed BRD/
TechSpec) -> HITL plan-review -> code generation on a real per-session
workspace directory (modifier -> LoopAgent(validate, fix) -> reporter).

java-8-to-25 is the one exception on the code-generation side: the user
chooses a "bigbang" or "incremental" strategy before upload, so its code
phase is registered as several runners instead of one -- `code_bigbang`
for a single-pass migration straight to Java 25, or `code_stage_1`..
`code_stage_8` for the phased staged builds (Readiness -> Java 17 ->
Spring Boot 2.7 -> 3.x -> Java 25 -> Spring Boot 4.x -> executable JAR;
the Spring Boot stages only run when requested) plus separate incremental reviewer/
reporter/curator runners that work across every stage (see
agents/java_8_to_25/agents.py's INCREMENTAL_STAGES and main.py's
_run_java8_incremental_code_step for the orchestration).
"""
import os
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from .java_8_to_25.agents import (
    re_agent as j8_re,
    planner_agent as j8_plan,
    code_pipeline_bigbang as j8_code_bigbang,
    INCREMENTAL_STAGES as j8_incremental_stages,
    STAGE_PIPELINES as j8_stage_pipelines,
    incremental_code_reviewer_agent as j8_incremental_code_reviewer,
    incremental_reporter_agent as j8_incremental_reporter,
    incremental_skill_curator_agent as j8_incremental_skill_curator,
)
from .solr_4_to_9.agents import (
    re_agent as solr_re, planner_agent as solr_plan, code_pipeline as solr_code,
)
from .oracle_19c_to_23ai.agents import (
    re_agent as oracle_re, planner_agent as oracle_plan, code_pipeline as oracle_code,
)
from .tibco_ems_to_pubsub.agents import (
    re_agent as tibco_ems_re, planner_agent as tibco_ems_plan, code_pipeline as tibco_ems_code,
)
from .jsp_to_react_bff.agents import (
    re_pipeline as jsp_re_pipeline, planner_agent as jsp_plan, code_pipeline as jsp_code,
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
    "java-8-to-25": {
        "re": _runner(j8_re),
        "plan": _runner(j8_plan),
        "code_bigbang": _runner(j8_code_bigbang),
        **{
            f"code_stage_{stage.idx}": _runner(pipeline)
            for stage, pipeline in zip(j8_incremental_stages, j8_stage_pipelines)
        },
        "incremental_code_reviewer": _runner(j8_incremental_code_reviewer),
        "incremental_reporter": _runner(j8_incremental_reporter),
        "incremental_skill_curator": _runner(j8_incremental_skill_curator),
    },
    "solr-4-to-9": {
        "re": _runner(solr_re),
        "plan": _runner(solr_plan),
        "code": _runner(solr_code),
    },
    "oracle-19c-to-23ai": {
        "re": _runner(oracle_re),
        "plan": _runner(oracle_plan),
        "code": _runner(oracle_code),
    },
    "tibco-ems-to-pubsub": {
        "re": _runner(tibco_ems_re),
        "plan": _runner(tibco_ems_plan),
        "code": _runner(tibco_ems_code),
    },
    "jsp-to-react-bff": {
        "re": _runner(jsp_re_pipeline),  # SequentialAgent: jsp_re_agent -> jsp_classifier_agent
        "plan": _runner(jsp_plan),
        "code": _runner(jsp_code),  # SequentialAgent: backend_generator -> frontend_generator -> LoopAgent(validate, fix) -> reporter
    },
}

TARGET_LANGS: dict[str, str] = {
    "java-8-to-25": "java",
    "solr-4-to-9": "xml",
    "oracle-19c-to-23ai": "sql",
    "tibco-ems-to-pubsub": "java",
    "jsp-to-react-bff": "tsx",
}
