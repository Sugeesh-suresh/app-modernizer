import os
from google.adk.agents import LlmAgent
from .prompts import RE_INSTRUCTION, BRD_INSTRUCTION, PLAN_INSTRUCTION, CODE_INSTRUCTION, TEST_INSTRUCTION, VALIDATE_INSTRUCTION, FIX_INSTRUCTION

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

re_agent = LlmAgent(
    name="java17_re",
    model=_MODEL,
    description="Reverse-engineers a Java 17 codebase into a structured analysis report.",
    instruction=RE_INSTRUCTION,
    output_key="analysis",
    include_contents="none",
)

brd_agent = LlmAgent(
    name="java17_brd",
    model=_MODEL,
    description="Generates a Business Requirements Document for a Java 17 → Java 25 migration.",
    instruction=BRD_INSTRUCTION,
    output_key="brd",
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

test_agent = LlmAgent(
    name="java17_test",
    model=_MODEL,
    description="Generates JUnit 5 unit tests targeting >80% coverage for migrated Java 25 code.",
    instruction=TEST_INSTRUCTION,
    output_key="generated_tests_raw",
    include_contents="none",
)

validate_agent = LlmAgent(
    name="java17_validate",
    model=_MODEL,
    description="Validates that Java 25 source code and JUnit 5 tests are mutually consistent.",
    instruction=VALIDATE_INSTRUCTION,
    output_key="validation_result",
    include_contents="none",
)

fix_agent = LlmAgent(
    name="java17_fix",
    model=_MODEL,
    description="Fixes Java 25 source or test files to resolve validation failures.",
    instruction=FIX_INSTRUCTION,
    output_key="generated_fix_raw",
    include_contents="none",
)
