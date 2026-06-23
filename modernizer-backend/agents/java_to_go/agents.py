import os
from google.adk.agents import LlmAgent
from .prompts import RE_INSTRUCTION, PLAN_INSTRUCTION, CODE_INSTRUCTION

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

re_agent = LlmAgent(
    name="java_go_re",
    model=_MODEL,
    description="Reverse-engineers a Java codebase and produces Analysis, BRD, and Technical Specification for a Java-to-Go migration.",
    instruction=RE_INSTRUCTION,
    output_key="analysis",
    include_contents="none",
)

plan_agent = LlmAgent(
    name="java_go_plan",
    model=_MODEL,
    description="Creates a detailed Java-to-Go migration plan.",
    instruction=PLAN_INSTRUCTION,
    output_key="plan",
    include_contents="none",
)

code_agent = LlmAgent(
    name="java_go_code",
    model=_MODEL,
    description="Generates idiomatic Go source files from a Java codebase.",
    instruction=CODE_INSTRUCTION,
    output_key="generated_code_raw",
    include_contents="none",
)
