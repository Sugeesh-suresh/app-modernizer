"""
Solr 4.x -> Solr 9.x agent pipeline — tool-driven re/planner/modifier/
build-loop/reporter architecture operating on a real per-session workspace
directory, mirroring agents/java_8_to_25/agents.py's shape but with a
deterministic config validator (agents/solr_4_to_9/tools.py) standing in
for a real compiler, since there is no Solr server to build/deploy against
here.

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
    name="solr_re",
    model=_MODEL,
    description="Reverse-engineers a Solr 4.x deployment (config + any SolrJ client code) and produces Analysis, BRD, Technical Specification, and an Existing Test Inventory.",
    instruction="Load and execute the `solr-4-to-9-re` skill, using the list_files and read_file tools to explore the workspace.",
    tools=[_skill("solr-4-to-9-re"), FunctionTool(fs_tools.list_files), FunctionTool(fs_tools.read_file)],
    output_key="analysis",
    include_contents="none",
)

planner_agent = LlmAgent(
    name="solr_plan",
    model=_MODEL,
    description="Creates a detailed Solr 4.x -> 9.x migration plan from the confirmed BRD and Technical Specification.",
    instruction=(
        "Load and execute the `solr-4-to-9-plan` skill to create the migration plan.\n\n"
        "## Confirmed Business Requirements Document\n{brd}\n\n"
        "## Confirmed Technical Specification\n{technical_spec}"
    ),
    tools=[_skill("solr-4-to-9-plan")],
    output_key="plan",
    include_contents="none",
)

modifier_agent = LlmAgent(
    name="modifier_agent",
    model=_MODEL,
    description="Applies the confirmed migration plan to the workspace's Solr config (and SolrJ client code, if any), reading and rewriting files in place.",
    instruction=(
        "Load and execute the `solr-4-to-9-modify` skill to apply the confirmed migration plan "
        "to the files in the workspace, using the list_files, read_file and write_file tools.\n\n"
        "## Confirmed Migration Plan\n{plan}"
    ),
    tools=[
        _skill("solr-4-to-9-modify"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
        FunctionTool(fs_tools.write_file),
    ],
    output_key="modify_result",
    include_contents="none",
)

validator_agent = LlmAgent(
    name="validator_agent",
    model=_MODEL,
    description="Statically validates the migrated Solr config and reports pass/fail as JSON.",
    instruction="Load and execute the `solr-4-to-9-validate` skill to check the workspace and report the result.",
    tools=[
        _skill("solr-4-to-9-validate"),
        FunctionTool(fs_tools.validate_solr_config),
        FunctionTool(fs_tools.signal_build_success),
    ],
    output_key="build_result",
    include_contents="none",
    after_agent_callback=make_skill_update_callback(
        validation_key="build_result",
        skill_md_path=_SKILLS_DIR / "solr-4-to-9-validate" / "SKILL.md",
        section_header="Validation Pass",
    ),
)

fixer_agent = LlmAgent(
    name="fixer_agent",
    model=_MODEL,
    description="Reads the files implicated by validator_agent's report and fixes them in place in the workspace.",
    instruction=(
        "Load and execute the `solr-4-to-9-fix` skill.\n\n"
        "## Validation Report (issues to fix)\n{build_result}"
    ),
    tools=[
        _skill("solr-4-to-9-fix"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
        FunctionTool(fs_tools.write_file),
    ],
    output_key="fix_result",
    include_contents="none",
    after_agent_callback=make_skill_update_callback(
        validation_key="build_result",
        skill_md_path=_SKILLS_DIR / "solr-4-to-9-fix" / "SKILL.md",
        section_header="Fix Pass",
    ),
)

build_loop = LoopAgent(
    name="build_loop",
    description="Iteratively validates and fixes the migrated Solr config (configurable max iterations).",
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
        "Load and execute the `solr-4-to-9-report` skill to produce the final migration report. Fold "
        "the Independent Code Review's findings into a dedicated report section rather than ignoring "
        "them.\n\n"
        "## Modify Result\n{modify_result}\n\n"
        "## Final Validation Result\n{build_result}\n\n"
        "## Independent Code Review\n{code_review}"
    ),
    tools=[_skill("solr-4-to-9-report")],
    output_key="final_report",
    include_contents="none",
)

skill_curator_agent = make_skill_curator_agent(
    _MODEL,
    allowed_skills=[
        "solr-4-to-9-re", "solr-4-to-9-plan", "solr-4-to-9-modify",
        "solr-4-to-9-validate", "solr-4-to-9-fix", "solr-4-to-9-report",
    ],
    context_instruction=(
        "## Confirmed Migration Plan\n{plan}\n\n## Modify Result\n{modify_result}\n\n"
        "## Final Validation Result\n{build_result}\n\n## Independent Code Review\n{code_review}"
    ),
)

code_pipeline = SequentialAgent(
    name="solr_code_pipeline",
    description="Applies the migration plan, validates/fixes the workspace in a loop, reviews and reports the outcome, then curates the skill library.",
    sub_agents=[modifier_agent, build_loop, code_reviewer_agent, reporter_agent, skill_curator_agent],
)
