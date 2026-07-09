"""
Java/Spring → Quarkus agent pipeline.

Agents:
  re_agent    — reverse-engineering + BRD + TechSpec (run separately)
  plan_agent  — migration plan (run separately)
  code_pipeline — SequentialAgent:
      code_agent       — generates full Quarkus codebase
      validation_loop  — LoopAgent(validate_agent, fix_agent, max_iterations=4)
          validate_agent — checks for compilation/build errors; exits loop early on pass
          fix_agent      — fixes errors and re-outputs the complete codebase

validate_agent and fix_agent read generated_code_raw and validation_result
from session state via template variables so they don't need the full
conversation history.

Skills (Pattern 2 — file-based):
  Each agent loads its instructions and reference material from
  agents/skills/<skill-name>/ at runtime via SkillToolset.
"""
import os
import pathlib
from google.adk.agents import LlmAgent, SequentialAgent, LoopAgent
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset
from ..shared.callbacks import make_validation_exit_callback, make_skill_update_callback

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "skills"


def _skill(name: str) -> SkillToolset:
    return SkillToolset(skills=[load_skill_from_dir(_SKILLS_DIR / name)])


# ── Step 1: Reverse Engineering ────────────────────────────────────────────
re_agent = LlmAgent(
    name="quarkus_re",
    model=_MODEL,
    description="Reverse-engineers a Java/Spring codebase and produces Analysis, BRD, and Technical Specification for a Quarkus migration.",
    instruction="Load and execute the `java-to-quarkus-re` skill to analyse the provided codebase.",
    tools=[_skill("java-to-quarkus-re")],
    output_key="analysis",
    include_contents="none",
)

# ── Step 2: Plan ───────────────────────────────────────────────────────────
plan_agent = LlmAgent(
    name="quarkus_plan",
    model=_MODEL,
    description="Creates a detailed Java/Spring-to-Quarkus migration plan.",
    instruction="Load and execute the `java-to-quarkus-plan` skill to create the migration plan.",
    tools=[_skill("java-to-quarkus-plan")],
    output_key="plan",
    include_contents="none",
)

# ── Step 3a: Code Generation ───────────────────────────────────────────────
code_agent = LlmAgent(
    name="quarkus_code",
    model=_MODEL,
    description="Generates Quarkus source files from a Java/Spring codebase.",
    instruction="Load and execute the `java-to-quarkus-code` skill to generate the migrated Quarkus codebase.",
    tools=[_skill("java-to-quarkus-code")],
    output_key="generated_code_raw",
    include_contents="none",
)

# ── Step 3b: Validate ──────────────────────────────────────────────────────
# generated_code_raw is injected from session state via the template variable below.
# After each pass:
#   1. New error patterns are appended to the validate SKILL.md (skill factory).
#   2. If validation passed, the loop is escalated (early exit).
validate_agent = LlmAgent(
    name="quarkus_validate",
    model=_MODEL,
    description="Reviews generated Quarkus code for compilation/build errors; outputs JSON.",
    instruction=(
        "Load and execute the `java-to-quarkus-validate` skill.\n\n"
        "## Generated Code to Review\n"
        "{generated_code_raw}"
    ),
    tools=[_skill("java-to-quarkus-validate")],
    output_key="validation_result",
    include_contents="none",
    after_agent_callback=[
        make_skill_update_callback(
            validation_key="validation_result",
            skill_md_path=_SKILLS_DIR / "java-to-quarkus-validate" / "SKILL.md",
            section_header="Validation Pass",
        ),
        make_validation_exit_callback("validation_result"),
    ],
)

# ── Step 3c: Fix ───────────────────────────────────────────────────────────
# Reads generated_code_raw and validation_result from session state.
# Overwrites generated_code_raw with the corrected full codebase.
# After each fix pass, the errors that were addressed are appended to the
# fix SKILL.md so future iterations have richer fix context (skill factory).
fix_agent = LlmAgent(
    name="quarkus_fix",
    model=_MODEL,
    description="Fixes compilation/build errors; outputs the complete corrected Quarkus codebase.",
    instruction=(
        "Load and execute the `java-to-quarkus-fix` skill.\n\n"
        "## Generated Code (current state — may already have previous fixes applied)\n"
        "{generated_code_raw}\n\n"
        "## Validation Report (errors to fix)\n"
        "{validation_result}"
    ),
    tools=[_skill("java-to-quarkus-fix")],
    output_key="generated_code_raw",
    include_contents="none",
    after_agent_callback=make_skill_update_callback(
        validation_key="validation_result",
        skill_md_path=_SKILLS_DIR / "java-to-quarkus-fix" / "SKILL.md",
        section_header="Fix Pass",
    ),
)

# ── Validation loop: validate → fix, up to 4 iterations ───────────────────
validation_loop = LoopAgent(
    name="quarkus_validation_loop",
    description="Iteratively validates and fixes generated Quarkus code (max 4 iterations).",
    sub_agents=[validate_agent, fix_agent],
    max_iterations=4,
)

# ── Code pipeline: generate then validate/fix ──────────────────────────────
code_pipeline = SequentialAgent(
    name="quarkus_code_pipeline",
    description="Generates Quarkus code then auto-validates and fixes compilation errors.",
    sub_agents=[code_agent, validation_loop],
)
