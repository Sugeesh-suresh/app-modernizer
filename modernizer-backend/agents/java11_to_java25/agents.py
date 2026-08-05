"""
Java 11 -> Java 25 agent pipeline — tool-driven scanner/planner/modifier/
build-loop/reporter architecture, mirroring
https://github.com/SahitiDamineni/java-migration-agent's
SequentialAgent "java_migration_agent":

    scanner_agent   (list_files, read_file)          -> repo_facts
    planner_agent   (pure reasoning)                  -> plan
    modifier_agent  (read_file, write_file)           -> modify_result
    build_loop = LoopAgent(max_iterations=3)
        validator_agent (run_command, signal_build_success) -> build_result
        fixer_agent     (read_file, write_file)              -> fix_result
    reporter_agent  (pure reasoning)                  -> final_report

Unlike every other pattern in this app, this pipeline does not generate
the whole codebase as one text blob: the uploaded repository is unpacked
to a real per-session workspace directory (see main.py's upload handler,
which sets session state["workspace_dir"]) and these agents read/write
real files there via agents/java11_to_java25/tools.py. validator_agent
actually shells out to `mvn compile` so fixer_agent works from real
compiler errors, not a guess.

Runtime wiring is split into `plan_pipeline` (scanner -> planner) and
`code_pipeline` (modifier -> build_loop -> reporter) at the same
plan-review human-in-the-loop checkpoint every other pattern in this app
uses (see main.py `_run_workflow`): ADK agent instances can only belong
to one SequentialAgent parent, so the two phases are wired as two
SequentialAgents rather than one literal top-level `java_migration_agent`
that would run start-to-finish with no pause for human review.

Skills (Pattern 2 — file-based):
  Each agent loads its instructions and reference material from
  agents/skills/<skill-name>/ at runtime via SkillToolset.
"""
import os
import pathlib
from google.adk.agents import LlmAgent, SequentialAgent, LoopAgent
from google.adk.skills import load_skill_from_dir
from google.adk.tools import FunctionTool
from google.adk.tools.skill_toolset import SkillToolset

from ..shared.callbacks import make_skill_update_callback
from . import tools as fs_tools

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "skills"


def _skill(name: str) -> SkillToolset:
    return SkillToolset(skills=[load_skill_from_dir(_SKILLS_DIR / name)])


# ── scanner_agent: explores the real workspace ──────────────────────────────
scanner_agent = LlmAgent(
    name="scanner_agent",
    model=_MODEL,
    description="Scans the repository workspace via list_files/read_file and records repo facts relevant to a Java 11 -> Java 25 migration.",
    instruction="Load and execute the `java11-to-java25-scan` skill, using the list_files and read_file tools to explore the workspace.",
    tools=[_skill("java11-to-java25-scan"), FunctionTool(fs_tools.list_files), FunctionTool(fs_tools.read_file)],
    output_key="repo_facts",
    include_contents="none",
)

# ── planner_agent: pure reasoning over repo_facts ───────────────────────────
planner_agent = LlmAgent(
    name="planner_agent",
    model=_MODEL,
    description="Creates a detailed Java 11 -> Java 25 migration plan from the scanner's repo facts.",
    instruction=(
        "Load and execute the `java11-to-java25-plan` skill to create the migration plan.\n\n"
        "## Repository Facts (from scanner_agent)\n"
        "{repo_facts}"
    ),
    tools=[_skill("java11-to-java25-plan")],
    output_key="plan",
    include_contents="none",
)

plan_pipeline = SequentialAgent(
    name="java11_plan_pipeline",
    description="Scans the workspace then produces the Java 11 -> Java 25 migration plan.",
    sub_agents=[scanner_agent, planner_agent],
)

# ── modifier_agent: applies the confirmed plan directly to workspace files ──
modifier_agent = LlmAgent(
    name="modifier_agent",
    model=_MODEL,
    description="Applies the confirmed migration plan to the workspace, reading and rewriting files in place via read_file/write_file.",
    instruction=(
        "Load and execute the `java11-to-java25-modify` skill to apply the confirmed migration plan "
        "to the files in the workspace, using the list_files, read_file and write_file tools.\n\n"
        "## Confirmed Migration Plan\n"
        "{plan}"
    ),
    tools=[
        _skill("java11-to-java25-modify"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
        FunctionTool(fs_tools.write_file),
    ],
    output_key="modify_result",
    include_contents="none",
)

# ── validator_agent: actually compiles the workspace ────────────────────────
# Outputs a JSON build report to build_result and calls signal_build_success
# (escalating out of build_loop) as soon as the build is clean.
validator_agent = LlmAgent(
    name="validator_agent",
    model=_MODEL,
    description="Runs the real build (mvn compile) against the modified workspace and reports pass/fail as JSON.",
    instruction="Load and execute the `java11-to-java25-validate` skill to build the workspace and report the result.",
    tools=[
        _skill("java11-to-java25-validate"),
        FunctionTool(fs_tools.run_command),
        FunctionTool(fs_tools.signal_build_success),
    ],
    output_key="build_result",
    include_contents="none",
    after_agent_callback=make_skill_update_callback(
        validation_key="build_result",
        skill_md_path=_SKILLS_DIR / "java11-to-java25-validate" / "SKILL.md",
        section_header="Validation Pass",
    ),
)

# ── fixer_agent: reads the failing files, patches them in place ────────────
fixer_agent = LlmAgent(
    name="fixer_agent",
    model=_MODEL,
    description="Reads the files implicated by validator_agent's build report and fixes them in place in the workspace.",
    instruction=(
        "Load and execute the `java11-to-java25-fix` skill.\n\n"
        "## Build Report (errors to fix)\n"
        "{build_result}"
    ),
    tools=[
        _skill("java11-to-java25-fix"),
        FunctionTool(fs_tools.read_file),
        FunctionTool(fs_tools.write_file),
    ],
    output_key="fix_result",
    include_contents="none",
    after_agent_callback=make_skill_update_callback(
        validation_key="build_result",
        skill_md_path=_SKILLS_DIR / "java11-to-java25-fix" / "SKILL.md",
        section_header="Fix Pass",
    ),
)

# ── build_loop: validate -> fix, up to 3 iterations ─────────────────────────
# validator_agent calls signal_build_success (escalate=True) as soon as the
# build passes, so the loop usually exits well before max_iterations.
build_loop = LoopAgent(
    name="build_loop",
    description="Iteratively builds and fixes the migrated workspace (max 3 iterations).",
    sub_agents=[validator_agent, fixer_agent],
    max_iterations=3,
)

# ── reporter_agent: pure reasoning, summarises the whole run ────────────────
reporter_agent = LlmAgent(
    name="reporter_agent",
    model=_MODEL,
    description="Summarises the migration run — what changed, final build status, and any remaining issues.",
    instruction=(
        "Load and execute the `java11-to-java25-report` skill to produce the final migration report.\n\n"
        "## Modify Result\n{modify_result}\n\n"
        "## Final Build Result\n{build_result}"
    ),
    tools=[_skill("java11-to-java25-report")],
    output_key="final_report",
    include_contents="none",
)

code_pipeline = SequentialAgent(
    name="java11_code_pipeline",
    description="Applies the migration plan, builds/fixes the workspace in a loop, then reports the outcome.",
    sub_agents=[modifier_agent, build_loop, reporter_agent],
)
