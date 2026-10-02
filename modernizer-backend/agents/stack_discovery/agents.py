"""
Stack discovery -> multi-stack reverse engineering.

The one pattern here that is not a migration. The user uploads a repository
without saying what it is; the pipeline works out which technology stacks are in
it and reverse-engineers each one, then stops. No plan, no code generation, no
build loop — the reverse-engineering document is the deliverable.

    dependency_mapper_agent  (tool-driven: list_files/read_file) -> stack_inventory
        ^ seeded with stack_detector's deterministic pre-scan findings
    [HITL] the reviewer confirms/unchecks the detected stacks
    then, once per confirmed stack, discovery_agent (defined below) with the
    stack's checklist — or wildfly-re for WildFly
    -> one combined document, one `## <stack>` section each
       (main.py's _run_bundle_re does the fan-out and the combining)

Stacks are whatever the repository turns out to contain: stack_detector derives
them from repo_fingerprint (manifests, imports, script includes, languages), and
the mapper may add any stack it can cite. The migrations' own RE skills are
deliberately NOT used: they are written towards a target, and this document must
describe the repository as it is. main.py also scrubs any migration language
that slips through (agents/shared/current_state.py).

`wildfly` keeps its own RE skill (wildfly-re) and runner — see
stack_detector.DEDICATED_RUNNERS.
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
        "## Repository Fingerprint (parsed manifests, imports, script includes, languages)\n"
        "{stack_fingerprint?}\n\n"
        "## Pre-scan Findings (stacks derived from the fingerprint, already run)\n{stack_prescan}\n\n"
        "## Stack Identifiers\n"
        "Use one of these exact `pattern` values in your JSON block wherever it fits. Any other "
        "stack you find gets a short kebab-case identifier of your own and is documented the same "
        "way, so report every stack the application is built on — do not squeeze one into an "
        "identifier that does not fit.\n{stack_known}"
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


# ── Discovery agent ───────────────────────────────────────────────────────────
# One agent for every stack, whatever it is. main.py's _run_bundle_re sends it one
# request per confirmed stack naming the stack, the evidence that identified it,
# and the checklist (skills/stack-discovery-re/references/*.md) to document it with
# — a dedicated one where it exists, general.md for anything else.
discovery_agent = LlmAgent(
    name="discover_stack",
    model=_MODEL,
    description="Documents one technology stack of an existing repository exactly as it is, via list_files/read_file.",
    instruction=(
        "Load and execute the `stack-discovery-re` skill for the stack named in the request, and load "
        "the reference checklist the request names with load_skill_resource. Use the list_files and "
        "read_file tools to explore the workspace, starting from the evidence paths in the request. "
        "Produce the Analysis, BRD, Technical Specification and Existing Test Inventory sections with "
        "the exact SECTION markers the skill specifies. Describe only what the repository contains — "
        "no migration, upgrade or other change suggestions of any kind."
    ),
    tools=[
        _skill("stack-discovery-re"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
    ],
    output_key="analysis",
    include_contents="none",
)
