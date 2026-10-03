"""
Stack discovery -> multi-stack reverse engineering.

The one pattern here that is not a migration. The user uploads a repository
without saying what it is; the pipeline works out which technology stacks are in
it and reverse-engineers each one, then stops. No plan, no code generation, no
build loop — the reverse-engineering document is the deliverable.

    dependency_mapper_agent  (tool-driven: list_files/read_file) -> stack_inventory
        ^ seeded with stack_detector's deterministic pre-scan findings
    [HITL] the reviewer confirms/unchecks the detected stacks
    then, once per confirmed stack, an EVIDENCE specialist — discovery_agent
    with the stack's checklist, wildfly-re for WildFly, or unit runs for a large
    stack — returns a cited Evidence Pack (agents/shared/evidence_pack.py)
    -> po_writer_agent writes the BRD and ea_writer_agent the Technical
       Specification + Test Inventory, in parallel, from the same evidence
       (main.py's _run_discovery_documents)

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
    description="Gathers the cited evidence about one technology stack of an existing repository, via list_files/read_file.",
    instruction=(
        "Load and execute the `stack-discovery-re` skill for the stack named in the request, and load "
        "the reference checklist the request names with load_skill_resource. Use the list_files and "
        "read_file tools to explore the workspace, starting from the evidence paths in the request. "
        "Return the skill's Evidence Pack — evidence only, no documents. Describe only what the repository "
        "contains — no migration, upgrade or other change suggestions of any kind."
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
    description="Merges pieces of evidence that do not fit one writer request, keeping every evidence id.",
    instruction=(
        "Merge the evidence below into ONE evidence document with the same `##` and `###` headings. Keep "
        "every item's `[EV-…]` id at the start of its bullet and its citation. Where items say the same "
        "thing, merge them into one bullet that keeps ALL their ids. Shorten wording, never drop an id or "
        "a limitation. Add nothing the evidence does not say, and no recommendations.\n\n"
        "## Evidence to merge\n{findings_batch}"
    ),
    output_key="merged_findings",
    include_contents="none",
)

# ── The two document writers ──────────────────────────────────────────────────
# Reading and writing are separate: the evidence specialists above read the code;
# these two write only from their evidence packs (main._run_discovery_documents
# builds each writer's view). Same evidence, two audiences, one set of ids.
# No tools — every statement must come from the evidence — and the skill text is
# the instruction itself (a callable also keeps the code in the evidence out of
# {...} templating).
def _skill_text(name: str) -> str:
    return (_SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[-1]


def _writer_instruction(skill: str):
    text = _skill_text(skill)

    def instruction(ctx) -> str:
        return (f"You are running the `{skill}` skill; its instructions follow.\n{text}\n\n"
                + str(ctx.state.get("writer_request", "")))
    return instruction


po_writer_agent = LlmAgent(
    name="po_brd",
    model=_MODEL,
    description="Product Owner: writes the as-is BRD across all stacks from the evidence packs and the rules catalog.",
    instruction=_writer_instruction("as-is-brd"),
    output_key="po_brd",
    include_contents="none",
)

ea_writer_agent = LlmAgent(
    name="ea_spec",
    model=_MODEL,
    description="Enterprise Architect: writes the current-state Technical Specification and Test Inventory from the evidence packs.",
    instruction=_writer_instruction("current-state-architecture"),
    output_key="ea_spec",
    include_contents="none",
)


# One batch of business-rule candidates -> classified, with every rule extracted.
# The skill's text is the instruction itself (no SkillToolset): a load_skill call
# would add a model round trip to each of thousands of batches. A callable
# instruction also bypasses {...} templating, which the skill's JSON example and
# the code in each batch would otherwise trip.
_RULES_SKILL = _skill_text("business-rules-extract")


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
