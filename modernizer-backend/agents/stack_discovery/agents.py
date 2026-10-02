"""
Stack discovery -> multi-stack reverse engineering.

The one pattern here that is not a migration. The user uploads a repository
without saying what it is; the pipeline works out which technology stacks are in
it and reverse-engineers each one, then stops. No plan, no code generation, no
build loop — the reverse-engineering document is the deliverable.

    dependency_mapper_agent  (tool-driven: list_files/read_file) -> stack_inventory
        ^ seeded with stack_detector's deterministic pre-scan findings
    [HITL] the reviewer confirms/unchecks the detected stacks
    then, once per confirmed stack, a discovery agent (defined below):
        java-8-to-25        -> stack-discovery-re + references/java.md
        jsp-to-react-bff    -> stack-discovery-re + references/jsp.md
        oracle-19c-to-23ai  -> stack-discovery-re + references/oracle.md
        solr-4-to-9         -> stack-discovery-re + references/solr.md
        tibco-ems-to-pubsub -> stack-discovery-re + references/tibco-ems.md
        wildfly             -> wildfly-re
    -> one combined document, one `## <stack>` section each
       (main.py's _run_bundle_re does the fan-out and the combining)

The pattern ids above are only keys for the stacks the detector knows; nothing
here migrates anything. The migrations' own RE skills are deliberately NOT used:
they are written towards a target (the Oracle one assesses 23ai readiness, the
Java one Java 25 blockers), and this document must describe the repository as it
is and nothing else. main.py also scrubs any migration language that slips
through (agents/shared/current_state.py).

`wildfly` is the one stack that exists only here. It has an RE skill and no
target platform, so it is registered with an `re` runner and nothing else — see
stack_detector.EXTRACTION_ONLY_PATTERNS.
"""
import pathlib

from google.adk.agents import LlmAgent
from google.adk.skills import load_skill_from_dir
from google.adk.tools import FunctionTool
from google.adk.tools.skill_toolset import SkillToolset

from ..shared.model_config import make_model
from . import tools as fs_tools

_MODEL = make_model()
_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "skills"


def _skill(name: str) -> SkillToolset:
    return SkillToolset(skills=[load_skill_from_dir(_SKILLS_DIR / name)])


# ── Pass 2 of the dependency mapper ───────────────────────────────────────────
# Pass 1 is agents/shared/stack_detector.py, which runs inline at upload time
# with no model involved. This agent receives those findings in its prompt (see
# main.py's _run_stack_mapping) and is measured against them: it confirms,
# rejects with a reason, or adds — always with a file citation, because main.py
# drops any stack that arrives without one.
dependency_mapper_agent = LlmAgent(
    name="dependency_mapper",
    model=_MODEL,
    description=(
        "Maps every technology stack present in the uploaded repository by reading build files, "
        "dependency declarations, deployment descriptors and configuration, confirming or rejecting "
        "a deterministic pre-scan and adding what it missed."
    ),
    instruction=(
        "Load and execute the `dependency-mapper` skill, using the list_files and read_file tools "
        "to explore the workspace.\n\n"
        "## Pre-scan Findings (deterministic regex scan, already run)\n{stack_prescan}\n\n"
        "## Known Stacks\n"
        "These are the stack identifiers this pipeline can reverse-engineer. Use these exact "
        "`pattern` values in your JSON block wherever one of them fits. A stack you report under "
        "any other identifier is still recorded and shown to the reviewer, but no reverse "
        "engineering will run for it — so do not invent an identifier for something that is "
        "already in this list.\n{stack_known}"
    ),
    tools=[
        _skill("dependency-mapper"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
    ],
    output_key="stack_inventory",
    include_contents="none",
)


# ── WildFly reverse engineering ───────────────────────────────────────────────
# Registered under its own pattern key so _run_bundle_re can invoke it exactly
# like any other stack's `re` runner. Extraction only: there is no wildfly
# planner or code pipeline, and PATTERN_RUNNERS["wildfly"] has no "plan"/"code"
# entry to reach for.
wildfly_re_agent = LlmAgent(
    name="wildfly_re",
    model=_MODEL,
    description=(
        "Extracts a WildFly/JBoss deployment's facts via list_files/read_file: server configuration "
        "and subsystems, datasources and JNDI bindings, module dependencies and class loading, "
        "descriptors, and container-supplied behaviour."
    ),
    instruction=(
        "Load and execute the `wildfly-re` skill, using the list_files and read_file tools to "
        "explore the workspace. Produce the Analysis, BRD, Technical Specification and Existing "
        "Test Inventory sections with the exact SECTION markers the skill specifies."
    ),
    tools=[
        _skill("wildfly-re"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
    ],
    output_key="analysis",
    include_contents="none",
)


# ── Per-stack discovery agents ────────────────────────────────────────────────
# One neutral skill, one reference checklist per stack. Keyed by the detector's
# pattern ids; registered as PATTERN_RUNNERS["stack-discovery"]["discover_<id>"].
DISCOVERY_STACKS: dict[str, tuple[str, str]] = {   # pattern -> (stack name, reference file)
    "java-8-to-25": ("Java application", "java.md"),
    "jsp-to-react-bff": ("JSP / Servlet web tier", "jsp.md"),
    "oracle-19c-to-23ai": ("Oracle Database", "oracle.md"),
    "solr-4-to-9": ("Apache Solr", "solr.md"),
    "tibco-ems-to-pubsub": ("TIBCO EMS messaging", "tibco-ems.md"),
}


def _discovery_agent(pattern: str, stack: str, reference: str) -> LlmAgent:
    return LlmAgent(
        name="discover_" + pattern.replace("-", "_"),
        model=_MODEL,
        description=f"Documents the {stack} part of an existing repository exactly as it is, via list_files/read_file.",
        instruction=(
            f"Load and execute the `stack-discovery-re` skill for the {stack} stack, and load its "
            f"`references/{reference}` resource as your checklist. Use the list_files and read_file "
            "tools to explore the workspace. Produce the Analysis, BRD, Technical Specification and "
            "Existing Test Inventory sections with the exact SECTION markers the skill specifies. "
            "Describe only what the repository contains — no migration, upgrade or other change "
            "suggestions of any kind."
        ),
        tools=[
            _skill("stack-discovery-re"),
            FunctionTool(fs_tools.list_files),
            FunctionTool(fs_tools.read_file),
        ],
        output_key="analysis",
        include_contents="none",
    )


discovery_agents: dict[str, LlmAgent] = {
    pattern: _discovery_agent(pattern, stack, reference)
    for pattern, (stack, reference) in DISCOVERY_STACKS.items()
}
