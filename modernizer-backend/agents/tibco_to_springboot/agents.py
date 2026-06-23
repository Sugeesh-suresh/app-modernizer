import os
from google.adk.agents import LlmAgent
from .prompts import RE_INSTRUCTION, PLAN_INSTRUCTION, CODE_INSTRUCTION

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

re_agent = LlmAgent(
    name="tibco_re",
    model=_MODEL,
    description="Reverse-engineers a TIBCO BusinessWorks project and produces Analysis, BRD, and Technical Specification.",
    instruction=RE_INSTRUCTION,
    output_key="analysis",
    include_contents="none",
)

plan_agent = LlmAgent(
    name="tibco_plan",
    model=_MODEL,
    description="Creates a detailed migration plan from TIBCO BusinessWorks to Java Spring Boot.",
    instruction=PLAN_INSTRUCTION,
    output_key="plan",
    include_contents="none",
)

code_agent = LlmAgent(
    name="tibco_code",
    model=_MODEL,
    description="Generates a complete Spring Boot application migrated from TIBCO BusinessWorks.",
    instruction=CODE_INSTRUCTION,
    output_key="generated_code_raw",
    include_contents="none",
)
