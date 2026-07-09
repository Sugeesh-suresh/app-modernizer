"""
Java 17 → Java 25 agent pipeline.

Skills (Pattern 2 — file-based):
  Each agent loads its instructions and reference material from
  agents/skills/<skill-name>/ at runtime via SkillToolset.
"""
import os
import pathlib
from google.adk.agents import LlmAgent
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "skills"


def _skill(name: str) -> SkillToolset:
    return SkillToolset(skills=[load_skill_from_dir(_SKILLS_DIR / name)])


re_agent = LlmAgent(
    name="java17_re",
    model=_MODEL,
    description="Reverse-engineers a Java 17 codebase and produces Analysis, BRD, and Technical Specification.",
    instruction="Load and execute the `java17-to-java25-re` skill to analyse the provided codebase.",
    tools=[_skill("java17-to-java25-re")],
    output_key="analysis",
    include_contents="none",
)

plan_agent = LlmAgent(
    name="java17_plan",
    model=_MODEL,
    description="Creates a detailed migration plan from Java 17 to Java 25.",
    instruction="Load and execute the `java17-to-java25-plan` skill to create the migration plan.",
    tools=[_skill("java17-to-java25-plan")],
    output_key="plan",
    include_contents="none",
)

code_agent = LlmAgent(
    name="java17_code",
    model=_MODEL,
    description="Generates migrated Java 25 source files from a Java 17 codebase.",
    instruction="Load and execute the `java17-to-java25-code` skill to generate the migrated Java 25 codebase.",
    tools=[_skill("java17-to-java25-code")],
    output_key="generated_code_raw",
    include_contents="none",
)
