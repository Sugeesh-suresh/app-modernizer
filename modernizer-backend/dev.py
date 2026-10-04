#!/usr/bin/env python3
"""
Cross-platform launcher for the backend: no virtual-environment activation needed.

A virtual environment keeps its interpreter in `.venv/bin/` on Linux/macOS but
`.venv/Scripts/` on Windows, so `source .venv/bin/activate` has no Windows
equivalent that works in every shell. This script never activates anything: it
finds the environment's own interpreter for the current OS and runs everything
through it, which is all activation does anyway.

    python dev.py              set up if needed, then start the API with auto-reload
    python dev.py setup        create .venv and install requirements, nothing else
    python dev.py setup-ui     setup, then build the optional UI-screenshot tools
    python dev.py test         run the test suite (installs pytest into .venv first)
    python dev.py run --port 9000 --host 0.0.0.0 --no-reload

Use `python3` on Linux/macOS, and `py` or `python` on Windows. Setup is
idempotent: requirements are reinstalled only when requirements.txt changes.
Standard library only, so it runs before any dependency is installed.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV / ".requirements.sha256"
WINDOWS = os.name == "nt"


def venv_python(venv: Path = VENV, windows: bool = WINDOWS) -> Path:
    """The virtual environment's interpreter — `Scripts\\python.exe` on Windows,
    `bin/python` everywhere else."""
    return venv / "Scripts" / "python.exe" if windows else venv / "bin" / "python"


def activate_hint(windows: bool = WINDOWS) -> str:
    """How to activate the environment by hand in this OS's usual shells."""
    if windows:
        return (r"PowerShell: .venv\Scripts\Activate.ps1    "
                r"cmd.exe: .venv\Scripts\activate.bat    Git Bash: source .venv/Scripts/activate")
    return "source .venv/bin/activate"


def requirements_hash(path: Path | None = None) -> str:
    return hashlib.sha256((path or REQUIREMENTS).read_bytes()).hexdigest()


def needs_install(stamp: Path | None = None, requirements: Path | None = None) -> bool:
    try:
        return (stamp or STAMP).read_text(encoding="utf-8").strip() != requirements_hash(requirements)
    except OSError:
        return True


def _run(argv: list) -> int:
    print("$ " + " ".join(str(a) for a in argv), flush=True)
    try:
        return subprocess.call([str(a) for a in argv], cwd=ROOT)
    except KeyboardInterrupt:
        return 130


RENDERER = ROOT / "tools" / "thymeleaf-render"
RENDERER_JAR = RENDERER / "target" / "thymeleaf-render.jar"


def renderer_is_stale() -> bool:
    if not RENDERER_JAR.exists():
        return True
    built = RENDERER_JAR.stat().st_mtime
    sources = [RENDERER / "pom.xml", *(RENDERER / "src").rglob("*.java")]
    return any(s.stat().st_mtime > built for s in sources)


def setup_ui() -> int:
    """Optional tools for stack discovery's UI screenshots: the Thymeleaf renderer
    (Java 17+ and Maven) and Playwright's Chromium. Without them the option is
    shown as unavailable, with the reason; nothing else depends on them."""
    code = setup()
    if code:
        return code
    mvn = shutil.which("mvn") or shutil.which("mvn.cmd")
    if not (mvn and shutil.which("java")):
        print("ERROR: Java 17+ and Maven are needed to build the Thymeleaf renderer.", file=sys.stderr)
        return 1
    print("Building the Thymeleaf renderer for UI screenshots ...")
    code = _run([mvn, "-q", "-f", RENDERER / "pom.xml", "package"])
    if code:
        return code
    if os.environ.get("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD") == "1":
        print("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1: not installing Chromium (set UI_SCREENSHOTS_CHROMIUM instead).")
        return 0
    return _run([venv_python(), "-m", "playwright", "install", "chromium"])


def setup() -> int:
    python = venv_python()
    if not python.exists():
        print(f"Creating virtual environment in {VENV} ...")
        code = _run([sys.executable, "-m", "venv", VENV])
        if code or not python.exists():
            print(f"ERROR: could not create the virtual environment (expected {python}).", file=sys.stderr)
            return code or 1
    if needs_install():
        print("Installing requirements ...")
        code = _run([python, "-m", "pip", "install", "-r", REQUIREMENTS])
        if code:
            return code
        STAMP.write_text(requirements_hash(), encoding="utf-8")
    else:
        print("Requirements already installed.")
    if renderer_is_stale():
        print("Optional: `python dev.py setup-ui` builds the tools for stack discovery's UI screenshots.")
    print(f"Environment ready. To use it in your own shell — {activate_hint()}")
    return 0


def run(host: str, port: int, reload: bool) -> int:
    if not (ROOT / ".env").exists():
        print("ERROR: .env not found. Copy .env.example to .env and set either GEMINI_API_KEY or the Vertex AI settings.", file=sys.stderr)
        return 1
    code = setup()
    if code:
        return code
    print(f"Starting backend on http://{host}:{port}")
    argv = [venv_python(), "-m", "uvicorn", "main:app", "--host", host, "--port", str(port)]
    return _run(argv + (["--reload"] if reload else []))


def test(pytest_args: list) -> int:
    code = setup()
    if code:
        return code
    python = venv_python()
    if subprocess.call([str(python), "-c", "import pytest"], cwd=ROOT, stderr=subprocess.DEVNULL):
        code = _run([python, "-m", "pip", "install", "pytest"])
        if code:
            return code
    return _run([python, "-m", "pytest", "tests/", "-q", *pytest_args])


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run", help="set up if needed, then start the API (default)")
    run_p.add_argument("--host", default="127.0.0.1")
    run_p.add_argument("--port", type=int, default=8000)
    run_p.add_argument("--no-reload", action="store_true")
    sub.add_parser("setup", help="create .venv and install requirements")
    sub.add_parser("setup-ui", help="also build the UI screenshot tools (Thymeleaf renderer, Chromium)")
    test_p = sub.add_parser("test", help="run the test suite")
    test_p.add_argument("pytest_args", nargs=argparse.REMAINDER)

    args = parser.parse_args(argv)
    if args.command == "setup":
        return setup()
    if args.command == "setup-ui":
        return setup_ui()
    if args.command == "test":
        return test(args.pytest_args)
    if args.command == "run":
        return run(args.host, args.port, not args.no_reload)
    return run("127.0.0.1", 8000, True)


if __name__ == "__main__":
    sys.exit(main())
