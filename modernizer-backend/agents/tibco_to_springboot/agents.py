"""
TIBCO BusinessWorks → Spring Boot agent pipeline.

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
    name="tibco_re",
    model=_MODEL,
    description="Reverse-engineers a TIBCO BusinessWorks project and produces Analysis, BRD, and Technical Specification.",
    instruction="Load and execute the `tibco-to-springboot-re` skill to analyse the provided TIBCO project.",
    tools=[_skill("tibco-to-springboot-re")],
    output_key="analysis",
    include_contents="none",
)

plan_agent = LlmAgent(
    name="tibco_plan",
    model=_MODEL,
    description="Creates a detailed migration plan from TIBCO BusinessWorks to Java Spring Boot.",
    instruction="Load and execute the `tibco-to-springboot-plan` skill to create the migration plan.",
    tools=[_skill("tibco-to-springboot-plan")],
    output_key="plan",
    include_contents="none",
)

code_agent = LlmAgent(
    name="tibco_code",
    model=_MODEL,
    description="Generates a complete Spring Boot application migrated from TIBCO BusinessWorks.",
    instruction="Load and execute the `tibco-to-springboot-code` skill to generate the migrated Spring Boot application.",
    tools=[_skill("tibco-to-springboot-code")],
    output_key="generated_code_raw",
    include_contents="none",
)
