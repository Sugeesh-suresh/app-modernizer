"""
TIBCO EMS -> Google Cloud Pub/Sub agent pipeline — tool-driven re/planner/
modifier/build-loop/reporter architecture operating on a real per-session
workspace directory, mirroring agents/java_8_to_25/agents.py's shape.

validator_agent has both a real `run_command` (mvn/gradle, for when the
migrated output is a Java/Spring Pub/Sub client application) and a
deterministic `validate_pubsub_mapping` config check (for when the output
is topic/subscription mapping config only) -- it inspects the workspace
first to decide which applies.

Skills (Pattern 2 -- file-based):
  Each agent loads its instructions and reference material from
  agents/skills/<skill-name>/ at runtime via SkillToolset.
"""
import os
import pathlib

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.skills import load_skill_from_dir
from google.adk.tools import FunctionTool
from google.adk.tools.skill_toolset import SkillToolset

from .. import config
from ..shared.callbacks import make_skill_update_callback
from ..shared.review_and_curate import make_code_reviewer_agent, make_skill_curator_agent
from . import tools as fs_tools

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "skills"


def _skill(name: str) -> SkillToolset:
    return SkillToolset(skills=[load_skill_from_dir(_SKILLS_DIR / name)])


re_agent = LlmAgent(
    name="tibco_ems_re",
    model=_MODEL,
    description="Reverse-engineers a TIBCO EMS integration (destinations, producers/consumers) and produces Analysis, BRD, Technical Specification, and an Existing Test Inventory.",
    instruction="Load and execute the `tibco-ems-to-pubsub-re` skill, using the list_files and read_file tools to explore the workspace.",
    tools=[_skill("tibco-ems-to-pubsub-re"), FunctionTool(fs_tools.list_files), FunctionTool(fs_tools.read_file)],
    output_key="analysis",
    include_contents="none",
)

planner_agent = LlmAgent(
    name="tibco_ems_plan",
    model=_MODEL,
    description="Creates a detailed TIBCO EMS -> Google Cloud Pub/Sub migration plan from the confirmed BRD and Technical Specification.",
    instruction=(
        "Load and execute the `tibco-ems-to-pubsub-plan` skill to create the migration plan.\n\n"
        "## Confirmed Business Requirements Document\n{brd}\n\n"
        "## Confirmed Technical Specification\n{technical_spec}"
    ),
    tools=[_skill("tibco-ems-to-pubsub-plan")],
    output_key="plan",
    include_contents="none",
)

modifier_agent = LlmAgent(
    name="modifier_agent",
    model=_MODEL,
    description="Applies the confirmed migration plan to the workspace, translating EMS destinations/producers/consumers to Pub/Sub topics/subscriptions.",
    instruction=(
        "Load and execute the `tibco-ems-to-pubsub-modify` skill to apply the confirmed migration plan "
        "to the files in the workspace, using the list_files, read_file and write_file tools.\n\n"
        "## Confirmed Migration Plan\n{plan}"
    ),
    tools=[
        _skill("tibco-ems-to-pubsub-modify"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
        FunctionTool(fs_tools.replace_in_file),
        FunctionTool(fs_tools.write_file),
    ],
    output_key="modify_result",
    include_contents="none",
)

validator_agent = LlmAgent(
    name="validator_agent",
    model=_MODEL,
    description="Validates the migrated output -- a real mvn/gradle build if it's a Java/Spring Pub/Sub client, otherwise a deterministic topic-mapping config check -- and reports pass/fail as JSON.",
    instruction="Load and execute the `tibco-ems-to-pubsub-validate` skill to check the workspace and report the result.",
    tools=[
        _skill("tibco-ems-to-pubsub-validate"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.run_command),
        FunctionTool(fs_tools.validate_pubsub_mapping),
        FunctionTool(fs_tools.signal_build_success),
    ],
    output_key="build_result",
    include_contents="none",
    after_agent_callback=make_skill_update_callback(
        validation_key="build_result",
        skill_md_path=_SKILLS_DIR / "tibco-ems-to-pubsub-validate" / "SKILL.md",
        section_header="Validation Pass",
    ),
)

fixer_agent = LlmAgent(
    name="fixer_agent",
    model=_MODEL,
    description="Reads the files implicated by validator_agent's report and fixes them in place in the workspace.",
    instruction=(
        "Load and execute the `tibco-ems-to-pubsub-fix` skill.\n\n"
        "## Validation Report (errors/issues to fix)\n{build_result}"
    ),
    tools=[
        _skill("tibco-ems-to-pubsub-fix"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
        FunctionTool(fs_tools.replace_in_file),
        FunctionTool(fs_tools.write_file),
    ],
    output_key="fix_result",
    include_contents="none",
    after_agent_callback=make_skill_update_callback(
        validation_key="build_result",
        skill_md_path=_SKILLS_DIR / "tibco-ems-to-pubsub-fix" / "SKILL.md",
        section_header="Fix Pass",
    ),
)

build_loop = LoopAgent(
    name="build_loop",
    description="Iteratively validates and fixes the migrated workspace (configurable max iterations).",
    sub_agents=[validator_agent, fixer_agent],
    max_iterations=config.BUILD_LOOP_MAX_ITERATIONS,
)

code_reviewer_agent = make_code_reviewer_agent(
    _MODEL,
    FunctionTool(fs_tools.list_files),
    FunctionTool(fs_tools.read_file),
    context_instruction="## Confirmed Migration Plan\n{plan}\n\n## Final Validation Result\n{build_result}",
)

reporter_agent = LlmAgent(
    name="reporter_agent",
    model=_MODEL,
    description="Summarises the migration run -- what changed, final validation status, and any remaining issues.",
    instruction=(
        "Load and execute the `tibco-ems-to-pubsub-report` skill to produce the final migration report. "
        "Fold the Independent Code Review's findings into a dedicated report section rather than "
        "ignoring them.\n\n"
        "## Modify Result\n{modify_result}\n\n"
        "## Final Validation Result\n{build_result}\n\n"
        "## Independent Code Review\n{code_review}"
    ),
    tools=[_skill("tibco-ems-to-pubsub-report")],
    output_key="final_report",
    include_contents="none",
)

skill_curator_agent = make_skill_curator_agent(
    _MODEL,
    allowed_skills=[
        "tibco-ems-to-pubsub-re", "tibco-ems-to-pubsub-plan", "tibco-ems-to-pubsub-modify",
        "tibco-ems-to-pubsub-validate", "tibco-ems-to-pubsub-fix", "tibco-ems-to-pubsub-report",
    ],
    context_instruction=(
        "## Confirmed Migration Plan\n{plan}\n\n## Modify Result\n{modify_result}\n\n"
        "## Final Validation Result\n{build_result}\n\n## Independent Code Review\n{code_review}"
    ),
)

code_pipeline = SequentialAgent(
    name="tibco_ems_code_pipeline",
    description="Applies the migration plan, validates/fixes the workspace in a loop, reviews and reports the outcome, then curates the skill library.",
    sub_agents=[modifier_agent, build_loop, code_reviewer_agent, reporter_agent, skill_curator_agent],
)
