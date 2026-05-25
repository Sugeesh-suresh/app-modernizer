"""
Centralised runtime configuration for the App Modernizer agents.

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
# Test validation retry loop
# ---------------------------------------------------------------------------

# Maximum number of validate → fix cycles before accepting the best-effort result.
# Each cycle runs one validation agent call and (if validation fails) one fix
# agent call.  Set to 0 to skip validation entirely.
TEST_RETRY_ATTEMPTS: int = _int("TEST_RETRY_ATTEMPTS", 3)
