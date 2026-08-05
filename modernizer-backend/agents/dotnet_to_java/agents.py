"""
C# .NET → Java agent pipeline.

Full pipeline: reverse-engineering + BRD/Tech Spec → plan → code.

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
    name="dotnet_java_re",
    model=_MODEL,
    description="Reverse-engineers a C# .NET codebase and produces Analysis, BRD, and Technical Specification for a .NET-to-Java migration.",
    instruction="Load and execute the `dotnet-to-java-re` skill to analyse the provided codebase.",
    tools=[_skill("dotnet-to-java-re")],
    output_key="analysis",
    include_contents="none",
)

plan_agent = LlmAgent(
    name="dotnet_java_plan",
    model=_MODEL,
    description="Creates a detailed C# .NET-to-Java migration plan.",
    instruction="Load and execute the `dotnet-to-java-plan` skill to create the migration plan.",
    tools=[_skill("dotnet-to-java-plan")],
    output_key="plan",
    include_contents="none",
)

code_agent = LlmAgent(
    name="dotnet_java_code",
    model=_MODEL,
    description="Generates idiomatic Java/Spring Boot source files from a C# .NET codebase.",
    instruction="Load and execute the `dotnet-to-java-code` skill to generate the migrated Java codebase.",
    tools=[_skill("dotnet-to-java-code")],
    output_key="generated_code_raw",
    include_contents="none",
)
