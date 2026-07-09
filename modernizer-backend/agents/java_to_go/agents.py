"""
Java → Go agent pipeline.

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
    name="java_go_re",
    model=_MODEL,
    description="Reverse-engineers a Java codebase and produces Analysis, BRD, and Technical Specification for a Java-to-Go migration.",
    instruction="Load and execute the `java-to-go-re` skill to analyse the provided codebase.",
    tools=[_skill("java-to-go-re")],
    output_key="analysis",
    include_contents="none",
)

plan_agent = LlmAgent(
    name="java_go_plan",
    model=_MODEL,
    description="Creates a detailed Java-to-Go migration plan.",
    instruction="Load and execute the `java-to-go-plan` skill to create the migration plan.",
    tools=[_skill("java-to-go-plan")],
    output_key="plan",
    include_contents="none",
)

code_agent = LlmAgent(
    name="java_go_code",
    model=_MODEL,
    description="Generates idiomatic Go source files from a Java codebase.",
    instruction="Load and execute the `java-to-go-code` skill to generate the migrated Go codebase.",
    tools=[_skill("java-to-go-code")],
    output_key="generated_code_raw",
    include_contents="none",
)
