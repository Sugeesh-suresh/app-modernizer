"""
Java/Spring → Quarkus agent pipeline.

Agents:
  re_agent    — reverse-engineering + BRD + TechSpec (run separately)
  plan_agent  — migration plan (run separately)
  code_pipeline — SequentialAgent:
      code_agent       — generates full Quarkus codebase
      validation_loop  — LoopAgent(validate_agent, fix_agent, max_iterations=4)
          validate_agent — checks for compilation/build errors; exits loop early on pass
          fix_agent      — fixes errors and re-outputs the complete codebase

validate_agent and fix_agent read generated_code_raw and validation_result
from session state via template variables so they don't need the full
conversation history.
"""
import os
from google.adk.agents import LlmAgent, SequentialAgent, LoopAgent
from .prompts import (
    RE_INSTRUCTION,
    PLAN_INSTRUCTION,
    CODE_INSTRUCTION,
    VALIDATE_INSTRUCTION,
    FIX_INSTRUCTION,
)
from ..shared.callbacks import make_validation_exit_callback

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ── Step 1: Reverse Engineering ────────────────────────────────────────────
re_agent = LlmAgent(
    name="quarkus_re",
    model=_MODEL,
    description="Reverse-engineers a Java/Spring codebase and produces Analysis, BRD, and Technical Specification for a Quarkus migration.",
    instruction=RE_INSTRUCTION,
    output_key="analysis",
    include_contents="none",
)

# ── Step 2: Plan ───────────────────────────────────────────────────────────
plan_agent = LlmAgent(
    name="quarkus_plan",
    model=_MODEL,
    description="Creates a detailed Java/Spring-to-Quarkus migration plan.",
    instruction=PLAN_INSTRUCTION,
    output_key="plan",
    include_contents="none",
)

# ── Step 3a: Code Generation ───────────────────────────────────────────────
code_agent = LlmAgent(
    name="quarkus_code",
    model=_MODEL,
    description="Generates Quarkus source files from a Java/Spring codebase.",
    instruction=CODE_INSTRUCTION,
    output_key="generated_code_raw",
    include_contents="none",
)

# ── Step 3b: Validate ──────────────────────────────────────────────────────
# Reads generated_code_raw from session state via {generated_code_raw} in the
# instruction. Exits the LoopAgent early when validation passes.
validate_agent = LlmAgent(
    name="quarkus_validate",
    model=_MODEL,
    description="Reviews generated Quarkus code for compilation/build errors; outputs JSON.",
    instruction=VALIDATE_INSTRUCTION,
    output_key="validation_result",
    include_contents="none",
    after_agent_callback=make_validation_exit_callback("validation_result"),
)

# ── Step 3c: Fix ───────────────────────────────────────────────────────────
# Reads generated_code_raw and validation_result from session state.
# Overwrites generated_code_raw with the corrected full codebase.
fix_agent = LlmAgent(
    name="quarkus_fix",
    model=_MODEL,
    description="Fixes compilation/build errors; outputs the complete corrected Quarkus codebase.",
    instruction=FIX_INSTRUCTION,
    output_key="generated_code_raw",
    include_contents="none",
)

# ── Validation loop: validate → fix, up to 4 iterations ───────────────────
validation_loop = LoopAgent(
    name="quarkus_validation_loop",
    description="Iteratively validates and fixes generated Quarkus code (max 4 iterations).",
    sub_agents=[validate_agent, fix_agent],
    max_iterations=4,
)

# ── Code pipeline: generate then validate/fix ──────────────────────────────
code_pipeline = SequentialAgent(
    name="quarkus_code_pipeline",
    description="Generates Quarkus code then auto-validates and fixes compilation errors.",
    sub_agents=[code_agent, validation_loop],
)
