"""
Workspace tools for the test-coverage pipeline: the writer may add tests and nothing else.

Writes go through a fence: a path must be under `src/test/java` (or `src/test/resources`) of a module, and a
file the repository already had when the run started is frozen — it can be neither edited nor deleted. A file
this run created can be edited, replaced or deleted (a new test that cannot be made to pass is removed, never
skipped). Builds run on the JDK the run's environment check chose, with the repository's Maven settings.
"""
from pathlib import Path

from ..shared import coverage, java_env
from ..shared.workspace_tools import (  # noqa: F401 (re-exported)
    list_files,
    make_run_command,
    read_file,
    resolve_within_workspace,
    search_files,
    workspace_root,
)
from ..shared import workspace_tools as _wt


def _refusal(tool_context, path: str) -> str:
    """"" when `path` may be written, else the reason."""
    try:
        target = resolve_within_workspace(tool_context, path)
        rel = target.relative_to(workspace_root(tool_context)).as_posix()
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not coverage.is_test_path(rel):
        return (f"ERROR: '{path}' is not a test file. This run writes only under src/test/java (and "
                "src/test/resources); production code and build files are read-only.")
    if rel.startswith(".modernizer/"):
        return "ERROR: `.modernizer/` holds the run's state — save your output with save_output instead."
    baseline = (getattr(tool_context, "state", None) or {}).get("baseline_dir", "")
    if baseline and (Path(baseline) / rel).is_file():
        return (f"ERROR: '{path}' is a test the repository already had — existing tests are frozen. Create a NEW test "
                "class (a different file) instead.")
    return ""


def write_file(tool_context, path: str, content: str, allow_full_overwrite: bool = False) -> str:
    return _refusal(tool_context, path) or _wt.write_file(tool_context, path, content, allow_full_overwrite)


def replace_in_file(tool_context, path: str, old_text: str, new_text: str, expected_count: int = 1) -> str:
    return _refusal(tool_context, path) or _wt.replace_in_file(tool_context, path, old_text, new_text, expected_count)


def delete_file(tool_context, path: str) -> str:
    return _refusal(tool_context, path) or _wt.delete_file(tool_context, path)


def _env(tool_context):
    home = (getattr(tool_context, "state", None) or {}).get("java_home", "")
    return java_env.build_env(home or None)


run_command = make_run_command({"mvn", "mvnw", "./mvnw"}, env_factory=_env, extra_args=java_env.maven_settings_args)


def signal_build_success(tool_context) -> str:
    return "ERROR: this pipeline has no validator step — the pipeline measures coverage itself."


__all__ = ["delete_file", "list_files", "read_file", "replace_in_file", "run_command", "search_files", "write_file"]
