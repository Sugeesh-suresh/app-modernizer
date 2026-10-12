"""
Oracle 19c -> 23ai agent pipeline — tool-driven re/planner/modifier/
build-loop/reporter architecture operating on a real per-session workspace
directory, mirroring agents/java_8_to_25/agents.py's shape but with a
deterministic SQL/PLSQL syntax validator (agents/oracle_19c_to_23ai/tools.py)
standing in for a real database connection, since there is no live Oracle
instance to run against here.

Skills (Pattern 2 -- file-based):
  Each agent loads its instructions and reference material from
  agents/skills/<migration>/ at runtime via SkillToolset: one skill per migration, one step
  file per agent (references/steps/<step>.md) — see agents/shared/skill_steps.py.
"""
import pathlib

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.tools import FunctionTool

from .. import config
from ..shared.model_config import make_model
from ..shared.callbacks import make_skill_update_callback
from ..shared.learned_fixes import (
    jsp_targets, make_lesson_capture_callback, make_lesson_verify_callback, skill_targets,
)
from ..shared import skill_manifest, skill_steps
from ..shared.rosters import PLAN_SKILL_ROSTERS
from ..shared.plan_contract import make_plan_contract_callback
from ..shared.review_and_curate import make_code_reviewer_agent, make_skill_curator_agent
from . import tools as fs_tools

_MODEL = make_model()
_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "skills"


# The plan's Skill Composition section, computed from each SKILL.md's frontmatter rather
# than left to the model: the planner cannot see the roster, the order or the versions,
# so a table it wrote itself would be invented.
_PLAN_SKILL_ROSTER: list[tuple[str, str]] = PLAN_SKILL_ROSTERS["oracle-19c-to-23ai"]

planner_agent = LlmAgent(
    name="oracle_plan",
    model=_MODEL,
    description="Creates a detailed Oracle 19c -> 23ai migration plan from the confirmed BRD and Technical Specification.",
    instruction=(
        skill_steps.instruction("oracle-19c-to-23ai:plan") + " to create the migration plan.\n\n"
        + skill_manifest.planner_block(_PLAN_SKILL_ROSTER)
        + "\n\n"
        "## Approved Versions (your organisation's list — use exactly these for these artifacts)\n{approved_versions_oracle_19c_to_23ai?}\n\n"
        "## Confirmed Business Requirements Document\n{brd}\n\n"
        "## Confirmed Technical Specification\n{technical_spec}\n\n## Existing Test Inventory\n{test_inventory}\n\n"
        "The Test Inventory is what question 4 is answered from — its Coverage Gaps section "
        "is the starting point for the plan's own, never a substitute for it."
    ),
    tools=[skill_steps.toolset("oracle-19c-to-23ai:plan")],
    output_key="plan",
    after_agent_callback=make_plan_contract_callback(pattern="oracle-19c-to-23ai"),
    include_contents="none",
)

modifier_agent = LlmAgent(
    name="modifier_agent",
    model=_MODEL,
    description="Applies the confirmed migration plan to the workspace's SQL/PLSQL files, reading and rewriting files in place.",
    instruction=(
        skill_steps.instruction("oracle-19c-to-23ai:modify") + " to apply the confirmed migration plan "
        "to the files in the workspace, using the list_files, read_file and write_file tools.\n\n"
        "## Approved Versions (your organisation's list — use exactly these for these artifacts)\n{approved_versions_oracle_19c_to_23ai?}\n\n"
        "## Confirmed Migration Plan\n{plan}"
    ),
    tools=[
        skill_steps.toolset("oracle-19c-to-23ai:modify"),
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
    description="Statically validates the migrated SQL/PLSQL and reports pass/fail as JSON.",
    instruction=skill_steps.instruction("oracle-19c-to-23ai:validate") + " to check the workspace and report the result.",
    tools=[
        skill_steps.toolset("oracle-19c-to-23ai:validate"),
        FunctionTool(fs_tools.validate_sql_syntax),
        FunctionTool(fs_tools.signal_build_success),
    ],
    output_key="build_result",
    include_contents="none",
    after_agent_callback=[
        # A verified resolution from the previous fix pass goes to the modifier's skill.
        make_lesson_verify_callback("build_result", "pending_lessons", skill_targets(_SKILLS_DIR, "oracle-19c-to-23ai:modify", "oracle-19c-to-23ai:fix"), "oracle-19c-to-23ai"),
        make_skill_update_callback(
            validation_key="build_result",
            skill_md_path=skill_steps.file("oracle-19c-to-23ai:validate"),
            section_header="Validation Pass",
        ),
    ],
)

fixer_agent = LlmAgent(
    name="fixer_agent",
    model=_MODEL,
    description="Reads the files implicated by validator_agent's report and fixes them in place in the workspace.",
    instruction=(
        skill_steps.instruction("oracle-19c-to-23ai:fix") + ".\n\n"
        "## Approved Versions (your organisation's list — use exactly these for these artifacts)\n{approved_versions_oracle_19c_to_23ai?}\n\n"
        "## Validation Report (issues to fix)\n{build_result}"
    ),
    tools=[
        skill_steps.toolset("oracle-19c-to-23ai:fix"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
        FunctionTool(fs_tools.replace_in_file),
        FunctionTool(fs_tools.write_file),
    ],
    output_key="fix_result",
    include_contents="none",
    # The fixer states each resolution (its `## Lessons` block); it is published only
    # once the next validation shows the error gone (see shared/learned_fixes.py).
    after_agent_callback=make_lesson_capture_callback("fix_result", "build_result", "pending_lessons"),
)

build_loop = LoopAgent(
    name="build_loop",
    description="Iteratively validates and fixes the migrated SQL/PLSQL (configurable max iterations).",
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
        skill_steps.instruction("oracle-19c-to-23ai:report") + " to produce the final migration report. "
        "Fold the Independent Code Review's findings into a dedicated report section rather than "
        "ignoring them.\n\n"
        "## Modify Result\n{modify_result}\n\n"
        "## Final Validation Result\n{build_result}\n\n"
        "## Independent Code Review\n{code_review}"
    ),
    tools=[skill_steps.toolset("oracle-19c-to-23ai:report")],
    output_key="final_report",
    include_contents="none",
)

skill_curator_agent = make_skill_curator_agent(
    _MODEL,
    allowed_skills=[
        "oracle-19c-to-23ai:plan", "oracle-19c-to-23ai:modify",
        "oracle-19c-to-23ai:validate", "oracle-19c-to-23ai:fix", "oracle-19c-to-23ai:report",
    ],
    context_instruction=(
        "## Confirmed Migration Plan\n{plan}\n\n## Modify Result\n{modify_result}\n\n"
        "## Final Validation Result\n{build_result}\n\n## Independent Code Review\n{code_review}"
    ),
)

code_pipeline = SequentialAgent(
    name="oracle_code_pipeline",
    description="Applies the migration plan, validates/fixes the workspace in a loop, reviews and reports the outcome, then curates the skill library.",
    sub_agents=[modifier_agent, build_loop, code_reviewer_agent, reporter_agent, skill_curator_agent],
)
