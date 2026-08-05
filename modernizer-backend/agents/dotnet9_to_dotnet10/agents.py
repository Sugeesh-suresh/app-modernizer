"""
.NET 9 → .NET 10 agent pipeline.

This is a DIRECT UPGRADE pattern: there is no reverse-engineering / BRD
phase. The plan agent works straight from the original source code, and
the code agent works from the confirmed plan + original source only.

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


plan_agent = LlmAgent(
    name="dotnet10_plan",
    model=_MODEL,
    description="Analyses a .NET 9 codebase directly and creates a detailed .NET 10 upgrade plan (no reverse-engineering phase).",
    instruction="Load and execute the `dotnet9-to-dotnet10-plan` skill to analyse the provided codebase and create the migration plan.",
    tools=[_skill("dotnet9-to-dotnet10-plan")],
    output_key="plan",
    include_contents="none",
)

code_agent = LlmAgent(
    name="dotnet10_code",
    model=_MODEL,
    description="Generates the fully migrated .NET 10 codebase from a .NET 9 application.",
    instruction="Load and execute the `dotnet9-to-dotnet10-code` skill to generate the migrated .NET 10 codebase.",
    tools=[_skill("dotnet9-to-dotnet10-code")],
    output_key="generated_code_raw",
    include_contents="none",
)
