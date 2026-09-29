#!/bin/bash
# Linux/macOS (and Git Bash on Windows). All the work is in dev.py, which
# finds the virtual environment's interpreter for this OS itself.
set -e
cd "$(cd "$(dirname "$0")" && pwd)"
PY=$(command -v python3 || command -v python)
exec "$PY" dev.py run --host 0.0.0.0 "$@"
