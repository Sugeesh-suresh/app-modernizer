"""
Centralised runtime configuration for the Stella Modernizer agents.

All values are driven by environment variables so that local (.env) and
production (cloud secret / env injection) environments can co-exist without
code changes.
"""
import os


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ---------------------------------------------------------------------------
# Model call retries (429 quota / rate limits, 408, 5xx, timeouts)
# ---------------------------------------------------------------------------

# With no retry options the Google GenAI SDK makes exactly one attempt, so the
# first 429 RESOURCE_EXHAUSTED ended the run. These drive the SDK's own retry
# (exponential backoff with jitter). Defaults are sized for per-minute quotas:
# 8 attempts waiting ~2, 4, 8, 16, 32, 60, 60 s — about three minutes in all
# before a call is given up. Set LLM_RETRY_ATTEMPTS=1 to disable.
LLM_RETRY_ATTEMPTS: int = _int("LLM_RETRY_ATTEMPTS", 8)
LLM_RETRY_INITIAL_DELAY: float = float(os.getenv("LLM_RETRY_INITIAL_DELAY", "2") or 2)
LLM_RETRY_MAX_DELAY: float = float(os.getenv("LLM_RETRY_MAX_DELAY", "60") or 60)

# ---------------------------------------------------------------------------
# Test validation retry loop
# ---------------------------------------------------------------------------

# Maximum number of validate → fix cycles before accepting the best-effort result.
# Each cycle runs one validation agent call and (if validation fails) one fix
# agent call.  Set to 0 to skip validation entirely.
TEST_RETRY_ATTEMPTS: int = _int("TEST_RETRY_ATTEMPTS", 3)

# ---------------------------------------------------------------------------
# Build/validate/fix loop (all 4 workspace-based patterns)
# ---------------------------------------------------------------------------

# Maximum validate -> fix iterations per build_loop (per stage, for the
# java-8-to-25 incremental strategy). The loop exits early as soon as
# validator_agent calls signal_build_success.
BUILD_LOOP_MAX_ITERATIONS: int = _int("BUILD_LOOP_MAX_ITERATIONS", 3)

# How long one build/compile command may run. The old fixed 180s could not
# complete a multi-module Maven reactor build on a large repository, so the
# build loop failed on the clock rather than on the code -- and then reported a
# build failure indistinguishable from a real one. 30 minutes covers a
# multi-hundred-thousand-line reactor build; raise it for bigger trees.
COMMAND_TIMEOUT_SECONDS: int = _int("COMMAND_TIMEOUT_SECONDS", 1800)

# ---------------------------------------------------------------------------
# Workspace ingestion limits
# ---------------------------------------------------------------------------

# Ceilings on what one upload may unpack. These exist to stop a runaway archive
# filling the disk, NOT to define the supported repository size -- when a repo
# exceeds them the excess is reported (see main.py's ExtractionResult), never
# silently dropped, because every later stage reasons about "every file in the
# repository" and a quietly partial workspace makes all of it wrong.
#
# Raised from 5,000 files / 100 MB, which truncated any real monorepo: 2M lines
# of Java is roughly 15k-25k files.
WORKSPACE_MAX_FILES: int = _int("WORKSPACE_MAX_FILES", 60_000)
WORKSPACE_MAX_TOTAL_BYTES: int = _int("WORKSPACE_MAX_TOTAL_BYTES", 2_000_000_000)

# ---------------------------------------------------------------------------
# Agent tool output budgets
# ---------------------------------------------------------------------------

# Characters of file content one read_file window returns.
READ_FILE_MAX_CHARS: int = _int("READ_FILE_MAX_CHARS", 20_000)

# Paths one list_files call returns before it paginates. A flat unpaginated
# listing of a 20k-file monorepo is ~1.2 MB (~300k tokens) in the first tool
# response of every RE run, spent before a single file has been read.
LIST_FILES_MAX_PATHS: int = _int("LIST_FILES_MAX_PATHS", 2_000)

# ---------------------------------------------------------------------------
# Chunked reverse engineering (java-8-to-11) — see agents/shared/re_units.py
# ---------------------------------------------------------------------------

# Files per reverse-engineering unit. Each unit is analysed in its own agent
# run, so this bounds how much one run can read (and resend on every call).
RE_UNIT_MAX_FILES: int = _int("RE_UNIT_MAX_FILES", 300)

# Characters of findings kept per unit. Longer findings are cut, and the cut is
# stated in the document — never silent.
RE_FINDINGS_MAX_CHARS: int = _int("RE_FINDINGS_MAX_CHARS", 20_000)

# Characters of findings one combining request may carry (~4 chars per token).
# Above it, findings are first merged in batches that each fit.
RE_SYNTHESIS_MAX_CHARS: int = _int("RE_SYNTHESIS_MAX_CHARS", 400_000)

# Matches one search_files call returns before it paginates. The total is always
# reported, so a capped page never reads as the whole answer.
SEARCH_MAX_RESULTS: int = _int("SEARCH_MAX_RESULTS", 200)

# Files larger than this are skipped by search_files (and counted as skipped):
# generated bundles and data dumps are not source, and regex over them is slow.
SEARCH_MAX_FILE_BYTES: int = _int("SEARCH_MAX_FILE_BYTES", 2_000_000)

# Characters of build output one run_command returns. Compiler diagnostics
# cluster at the END of a Maven reactor build, so the window is split head/tail
# rather than truncated head-first (see workspace_tools._clip_command_output).
COMMAND_OUTPUT_MAX_CHARS: int = _int("COMMAND_OUTPUT_MAX_CHARS", 40_000)

# ---------------------------------------------------------------------------
# Result collection
# ---------------------------------------------------------------------------

# Files included in the browsable result payload held in session state. The
# downloadable ZIP is built from the workspace on disk and is NOT subject to
# this -- it always contains every file (see main.py's _archive_workspace).
RESULT_PREVIEW_MAX_FILES: int = _int("RESULT_PREVIEW_MAX_FILES", 2_000)
RESULT_PREVIEW_MAX_TOTAL_BYTES: int = _int("RESULT_PREVIEW_MAX_TOTAL_BYTES", 40_000_000)
