#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ ! -f .env ]; then
  echo "ERROR: .env file not found. Copy .env.example and add your GEMINI_API_KEY."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

# Always `.venv/bin/python -m <tool>`, never `.venv/bin/<tool>`. A venv's console
# scripts carry an ABSOLUTE shebang written when the venv was created, so a .venv
# that was copied here from another checkout keeps launching THAT checkout's
# interpreter — and with it that checkout's google-adk, which is the one pin this
# backend cannot be wrong about (see requirements.txt). `.venv/bin/python` is a
# relative symlink and always resolves to this venv.
.venv/bin/python -m pip install -q -r requirements.txt

echo "Starting backend on http://localhost:8000"
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
