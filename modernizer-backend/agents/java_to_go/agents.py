import os
from google.adk.agents import LlmAgent
from .prompts import RE_INSTRUCTION, BRD_INSTRUCTION, PLAN_INSTRUCTION, CODE_INSTRUCTION, TEST_INSTRUCTION, VALIDATE_INSTRUCTION, FIX_INSTRUCTION

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

re_agent = LlmAgent(
    name="java_go_re",
    model=_MODEL,
    description="Reverse-engineers a Java codebase for a Java-to-Go migration.",
    instruction=RE_INSTRUCTION,
    output_key="analysis",
    include_contents="none",
)

brd_agent = LlmAgent(
    name="java_go_brd",
    model=_MODEL,
    description="Generates a BRD for rewriting a Java application in Go.",
    instruction=BRD_INSTRUCTION,
    output_key="brd",
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

test_agent = LlmAgent(
    name="java_go_test",
    model=_MODEL,
    description="Generates Go table-driven tests targeting >80% coverage for migrated Go code.",
    instruction=TEST_INSTRUCTION,
    output_key="generated_tests_raw",
    include_contents="none",
)

validate_agent = LlmAgent(
    name="java_go_validate",
    model=_MODEL,
    description="Validates that migrated Go source code and _test.go files are mutually consistent.",
    instruction=VALIDATE_INSTRUCTION,
    output_key="validation_result",
    include_contents="none",
)

fix_agent = LlmAgent(
    name="java_go_fix",
    model=_MODEL,
    description="Fixes Go source or test files to resolve validation failures.",
    instruction=FIX_INSTRUCTION,
    output_key="generated_fix_raw",
    include_contents="none",
)
