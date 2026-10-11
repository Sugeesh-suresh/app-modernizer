"""The installable form of the Gemini CLI extension (gemini-cli/build-release.mjs): the layout
`gemini extensions install <repo> --ref=stable` expects, and a backend that runs from it."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    out = tmp_path_factory.mktemp("release") / "ext"
    subprocess.run(["node", str(REPO / "gemini-cli" / "build-release.mjs"), "--out", str(out)], check=True,
                   capture_output=True, text=True)
    return out


def test_the_extension_is_at_the_root_with_real_skill_files(release):
    manifest = json.loads((release / "gemini-extension.json").read_text())
    assert manifest["mcpServers"]["modernizer"]["args"] == ["${extensionPath}${/}launch.mjs"]
    for name in ("GEMINI.md", "launch.mjs", "RELEASE.json", "commands/modernize/start.toml",
                 "commands/reverse-engineer.toml", "agents/modernizer-coder.md", "skills/java-8-to-25/SKILL.md",
                 "modernizer-backend/cli/mcp_server.py", "modernizer-backend/requirements-cli.txt"):
        assert (release / name).is_file(), name
    assert not (release / "skills").is_symlink()
    # No web app, tests, caches or local settings; no link that an install copy would leave dangling.
    for absent in ("modernizer-backend/main.py", "modernizer-backend/tests", "modernizer-backend/.env",
                   "modernizer-backend/agents/skills", "install.mjs", "build-release.mjs"):
        assert not (release / absent).exists() and not (release / absent).is_symlink(), absent
    assert not list(release.rglob("__pycache__"))


def test_the_backend_runs_from_the_release_once_its_skills_link_exists(release, tmp_path):
    (release / "modernizer-backend" / "agents" / "skills").symlink_to(release / "skills", target_is_directory=True)
    code = ("from cli import mcp_server, pipeline; from agents.shared import skill_steps; "
            "assert skill_steps.exists('java-8-to-25:modify'); print('ok')")
    r = subprocess.run([sys.executable, "-c", code], cwd=release / "modernizer-backend", capture_output=True, text=True)
    assert r.stdout.strip().endswith("ok"), r.stderr[-2000:]
