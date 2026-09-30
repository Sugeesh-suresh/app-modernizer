"""
Stack discovery -> multi-stack reverse engineering.

The one pattern here that is not a migration. The user uploads a repository
without saying what it is; the pipeline works out which technology stacks are in
it and reverse-engineers each one, then stops. No plan, no code generation, no
build loop — the reverse-engineering document is the deliverable.

    dependency_mapper_agent  (tool-driven: list_files/read_file) -> stack_inventory
        ^ seeded with stack_detector's deterministic pre-scan findings
    [HITL] the reviewer confirms/unchecks the detected stacks
    then, once per confirmed stack, that stack's OWN existing `re` runner:
        java-8-to-25        -> java-8-to-25-re
        jsp-to-react-bff    -> jsp-re + jsp-logic-classifier
        oracle-19c-to-23ai  -> oracle-19c-to-23ai-re
        solr-4-to-9         -> solr-4-to-9-re
        tibco-ems-to-pubsub -> tibco-ems-to-pubsub-re
        wildfly             -> wildfly-re          (defined below)
    -> one combined document, one `## <stack>` section each
       (main.py's _run_bundle_re already does the fan-out and the combining)

Reusing each stack's existing RE skill rather than writing a discovery-specific
one is the point: those skills are the maintained extraction logic for their
stack, and a second set written for this pipeline would drift from them. The
consequence is that the sections read with their migration framing intact (the
Oracle section is written towards 23ai), which is honest about where the analysis
comes from.

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
