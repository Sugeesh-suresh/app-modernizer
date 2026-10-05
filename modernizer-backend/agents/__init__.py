"""
ADK agent registry for the Stella Modernizer.

The 5 migration patterns share one shape: `re` (reverse-engineering ->
Analysis/BRD/TechSpec/Test Inventory) -> HITL brd-review -> `plan` (from
confirmed BRD/TechSpec) -> HITL plan-review -> code generation on a real
per-session workspace directory (modifier -> LoopAgent(validate, fix) ->
reporter).

`stack-discovery` is the exception to that shape and is not a migration: it
maps whichever technology stacks are actually in the uploaded repo, fans out to
each one's `re` runner, and stops at the combined document. It therefore has a
`mapper` runner and no `plan`/`code` at all. `wildfly` exists only as one leg of
that fan-out -- an RE skill with no target platform (see
agents/stack_discovery/agents.py).

java-8-to-11 upgrades the JDK only, inside a scope fence that freezes the JSP
tier and the WildFly deployment (agents/shared/scope_fence.py). Its modifier is
registered on its own (`code_modify`, run once per plan task) and the rest of
its code pipeline as `code_finish` (see agents/java_8_to_11/agents.py and
main.py's _run_java11_code_step).

java-8-to-25 is the other exception on the code-generation side: the user
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
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from .shared.unknown_tool_guard import UnknownToolGuard
from .java_8_to_25.agents import (
    re_agent as j8_re,
    planner_agent as j8_plan,
    code_pipeline_bigbang as j8_code_bigbang,
    INCREMENTAL_STAGES as j8_incremental_stages,
    STAGE_BUILD_LOOPS as j8_stage_build_loops,
    STAGE_MODIFIERS as j8_stage_modifiers,
    STAGE_PIPELINES as j8_stage_pipelines,
    incremental_code_reviewer_agent as j8_incremental_code_reviewer,
    incremental_reporter_agent as j8_incremental_reporter,
    incremental_skill_curator_agent as j8_incremental_skill_curator,
)
from .java_8_to_11.agents import (
    re_agent as j11_re,
    planner_agent as j11_plan,
    modifier_agent as j11_modify,
    code_finish_pipeline as j11_code_finish,
    module_re_agent as j11_re_module,
    findings_merge_agent as j11_re_merge,
    re_synthesis_agent as j11_re_synthesize,
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
from .stack_discovery.agents import (
    dependency_mapper_agent as stack_mapper, wildfly_re_agent as wildfly_re,
    discovery_agent as stack_discovery_agent,
    discover_unit_agent, discover_merge_agent, po_writer_agent, ea_writer_agent, ea_ui_writer_agent,
    rule_extractor_agent,
)

APP_NAME = "modernizer"
USER_ID = "default"

_db_url = os.getenv("DATABASE_URL")
if _db_url:
    from google.adk.sessions import DatabaseSessionService
    session_service = DatabaseSessionService(db_url=_db_url)
else:
    session_service = InMemorySessionService()


# One guard for every runner: a model calling a tool this app never declared
# (e.g. `google:python_interpreter`) gets an error it can recover from instead
# of ending the run -- see agents/shared/unknown_tool_guard.py.
UNKNOWN_TOOL_GUARD = UnknownToolGuard()
from .shared.llm_traffic import LLM_TRAFFIC  # noqa: E402


def _runner(agent) -> Runner:
    _ROOT_AGENTS.append(agent)
    return Runner(
        app=App(name=APP_NAME, root_agent=agent, plugins=[UNKNOWN_TOOL_GUARD, LLM_TRAFFIC]),
        session_service=session_service,
    )


_ROOT_AGENTS: list = []


PATTERN_RUNNERS: dict[str, dict[str, Runner]] = {
    "java-8-to-25": {
        "re": _runner(j8_re),
        "plan": _runner(j8_plan),
        "code_bigbang": _runner(j8_code_bigbang),
        # Per stage: the whole pipeline, plus its halves — main.py runs the modifier once per
        # plan task and the build loop once per stage (see _run_java8_incremental_code_step).
        **{
            key: _runner(agent)
            for stage, pipeline, modifier, build_loop in zip(
                j8_incremental_stages, j8_stage_pipelines, j8_stage_modifiers, j8_stage_build_loops,
            )
            for key, agent in (
                (f"code_stage_{stage.idx}", pipeline),
                (f"code_stage_{stage.idx}_modify", modifier),
                (f"code_stage_{stage.idx}_build", build_loop),
            )
        },
        "incremental_code_reviewer": _runner(j8_incremental_code_reviewer),
        "incremental_reporter": _runner(j8_incremental_reporter),
        "incremental_skill_curator": _runner(j8_incremental_skill_curator),
    },
    # A JDK-only upgrade of a JSP + WildFly monolith. main.py runs `code_modify`
    # once per plan task, then `code_finish` (build loop -> review -> report ->
    # curator) once -- see _run_java11_code_step.
    "java-8-to-11": {
        "re": _runner(j11_re),                  # single pass (RE_UNIT_MAX_FILES=0)
        # Chunked reverse engineering — main.py's _run_java11_re.
        "re_module": _runner(j11_re_module),
        "re_merge": _runner(j11_re_merge),
        "re_synthesize": _runner(j11_re_synthesize),
        "plan": _runner(j11_plan),
        "code_modify": _runner(j11_modify),
        "code_finish": _runner(j11_code_finish),
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
    # Reverse-engineering only -- no plan, no code. `mapper` is pass 2 of the
    # dependency mapper (pass 1 is agents/shared/stack_detector.py, no model);
    # then `discover` gathers evidence once per confirmed stack (not the
    # migrations' own `re` runners above) and two writers turn it into documents.
    "stack-discovery": {
        "mapper": _runner(stack_mapper),
        "discover": _runner(stack_discovery_agent),
        # Evidence for a large stack, unit by unit; merging evidence that does not
        # fit one writer request; the two writers; the business-rules ledger —
        # see main._run_discovery_documents / _run_rules_extraction.
        "discover_unit": _runner(discover_unit_agent),
        "discover_merge": _runner(discover_merge_agent),
        "po_brd": _runner(po_writer_agent),
        "ea_spec": _runner(ea_writer_agent),
        "ea_ui": _runner(ea_ui_writer_agent),
        "rules": _runner(rule_extractor_agent),
    },
    # A stack, not a migration: reachable only as one leg of a stack-discovery
    # fan-out (stack_detector.DEDICATED_RUNNERS), so it has an `re` runner only.
    "wildfly": {
        "re": _runner(wildfly_re),
    },
}

TARGET_LANGS: dict[str, str] = {
    "java-8-to-25": "java",
    "java-8-to-11": "java",
    "solr-4-to-9": "xml",
    "oracle-19c-to-23ai": "sql",
    "tibco-ems-to-pubsub": "java",
    "jsp-to-react-bff": "tsx",
    # stack-discovery generates no code, so it needs no target language. Absent
    # rather than set to a placeholder: a language here would imply an output
    # tree that never gets built.
}


# Every agent gets its role's model (MODEL_PLAN, MODEL_CODE, …, else GEMINI_MODEL),
# with the 429 fallback when MODEL_FALLBACK is set — see shared/model_config.py.
from .shared.model_config import assign_role_models  # noqa: E402

MODEL_ASSIGNMENT = assign_role_models(_ROOT_AGENTS)
