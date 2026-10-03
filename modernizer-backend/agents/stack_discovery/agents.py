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


# ── Large repositories ────────────────────────────────────────────────────────
# Each of these runs in its own short-lived session (main._run_isolated), so many
# can run at once without sharing state; their inputs arrive as session state.

# One unit (a bounded list of files) of one stack -> Unit Findings.
discover_unit_agent = LlmAgent(
    name="discover_unit",
    model=_MODEL,
    description="Reads every file of one unit of one stack and writes cited Unit Findings.",
    instruction=(
        "Load and execute the `stack-discovery-unit` skill for the unit below, using read_file, "
        "search_files and list_files.\n\n{unit_scope}"
    ),
    tools=[
        _skill("stack-discovery-unit"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.search_files),
        FunctionTool(fs_tools.read_file),
    ],
    output_key="unit_findings",
    include_contents="none",
)

# Several units' findings -> one, when all of them do not fit one request.
discover_merge_agent = LlmAgent(
    name="discover_merge",
    model=_MODEL,
    description="Merges several units' findings into one findings document without losing facts.",
    instruction=(
        "Merge the Unit Findings below into ONE findings document with the same sections, headed "
        "`## Units <first id>-<last id>`. Keep every component, entry point, data item, integration and "
        "test with its citation; merge only exact duplicates. Keep every limitation. Add nothing the "
        "findings do not say, and no recommendations.\n\n## Findings to merge\n{findings_batch}"
    ),
    output_key="merged_findings",
    include_contents="none",
)

# Every unit's findings -> the stack's four-section document.
discover_synthesis_agent = LlmAgent(
    name="discover_synthesize",
    model=_MODEL,
    description="Writes one stack's Analysis/BRD/Technical Specification/Test Inventory from its units' findings.",
    instruction=(
        "Load the `stack-discovery-re` skill and write its four-section document for the stack below, "
        "following its Required output exactly (the five SECTION markers, in order) and its rules: describe "
        "only what exists, no migration or change suggestions. The skill's discovery procedure has already "
        "been carried out unit by unit by separate runs: the Unit Findings below are your only evidence. You "
        "have no workspace tools — never claim to have read a file the findings do not cite. Where a unit "
        "failed or was cut, say so under Discovery Limitations. The Business Rules section summarises "
        "the rules by capability; the complete rule-by-rule catalog is appended to the document "
        "separately.\n\n{synthesis_request}"
    ),
    tools=[_skill("stack-discovery-re")],
    output_key="analysis",
    include_contents="none",
)

# One batch of business-rule candidates -> classified, with every rule extracted.
# The skill's text is the instruction itself (no SkillToolset): a load_skill call
# would add a model round trip to each of thousands of batches. A callable
# instruction also bypasses {...} templating, which the skill's JSON example and
# the code in each batch would otherwise trip.
_RULES_SKILL = (_SKILLS_DIR / "business-rules-extract" / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[-1]


def _rule_instruction(ctx) -> str:
    return ("You are running the `business-rules-extract` skill; its instructions follow.\n"
            + _RULES_SKILL + "\n\n## Candidates\n" + str(ctx.state.get("rule_batch", "")))


rule_extractor_agent = LlmAgent(
    name="rule_extractor",
    model=_MODEL,
    description="Classifies each parsed code candidate and extracts every business rule it implements, cited to lines.",
    instruction=_rule_instruction,
    output_key="rule_batch_result",
    include_contents="none",
)
