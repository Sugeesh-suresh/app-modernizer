import os
from google.adk.agents import LlmAgent
from .prompts import (
    RE_INSTRUCTION, BRD_INSTRUCTION, PLAN_INSTRUCTION, CODE_INSTRUCTION,
    TEST_INSTRUCTION, VALIDATE_INSTRUCTION, FIX_INSTRUCTION,
)

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

re_agent = LlmAgent(
    name="tibco_re",
    model=_MODEL,
    description="Reverse-engineers a TIBCO BusinessWorks project into a structured analysis report.",
    instruction=RE_INSTRUCTION,
    output_key="analysis",
    include_contents="none",
)

brd_agent = LlmAgent(
    name="tibco_brd",
    model=_MODEL,
    description="Generates a Business Requirements Document for a TIBCO BW → Spring Boot migration.",
    instruction=BRD_INSTRUCTION,
    output_key="brd",
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

test_agent = LlmAgent(
    name="tibco_test",
    model=_MODEL,
    description="Generates JUnit 5 unit tests targeting >80% coverage for migrated Spring Boot code.",
    instruction=TEST_INSTRUCTION,
    output_key="generated_tests_raw",
    include_contents="none",
)

validate_agent = LlmAgent(
    name="tibco_validate",
    model=_MODEL,
    description="Validates that Spring Boot source code and JUnit 5 tests are mutually consistent.",
    instruction=VALIDATE_INSTRUCTION,
    output_key="validation_result",
    include_contents="none",
)

fix_agent = LlmAgent(
    name="tibco_fix",
    model=_MODEL,
    description="Fixes Spring Boot source or test files to resolve validation failures.",
    instruction=FIX_INSTRUCTION,
    output_key="generated_fix_raw",
    include_contents="none",
)
