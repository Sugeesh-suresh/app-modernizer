import os
from google.adk.agents import LlmAgent
from .prompts import RE_INSTRUCTION, PLAN_INSTRUCTION, CODE_INSTRUCTION

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

re_agent = LlmAgent(
    name="java17_re",
    model=_MODEL,
    description="Reverse-engineers a Java 17 codebase and produces Analysis, BRD, and Technical Specification.",
    instruction=RE_INSTRUCTION,
    output_key="analysis",
    include_contents="none",
)

plan_agent = LlmAgent(
    name="java17_plan",
    model=_MODEL,
    description="Creates a detailed migration plan from Java 17 to Java 25.",
    instruction=PLAN_INSTRUCTION,
    output_key="plan",
    include_contents="none",
)

code_agent = LlmAgent(
    name="java17_code",
    model=_MODEL,
    description="Generates migrated Java 25 source files from a Java 17 codebase.",
    instruction=CODE_INSTRUCTION,
    output_key="generated_code_raw",
    include_contents="none",
)
