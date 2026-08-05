"""
Real filesystem + build-execution tools for the java11-to-java25 agent
pipeline.

Every other pattern in this app has a single LLM call read a full text
dump of the codebase and write back a full text dump of the migrated
code. This pattern instead unpacks the uploaded repository into a real
per-session workspace directory (see main.py's upload handler, which sets
session state["workspace_dir"]) and lets the scanner/modifier/validator/
fixer agents interact with real files there via the tools below —
mirroring https://github.com/SahitiDamineni/java-migration-agent, whose
own tools.py describes itself as: "The LLM supplies the judgment; the
tools are dumb I/O (list, read, write, run)."

Every tool takes a `tool_context: ToolContext` parameter (ADK injects it
automatically based on the type annotation) so the workspace root can be
read from session state without threading it through every call.
"""
import shlex
import subprocess
from pathlib import Path

from google.adk.tools import ToolContext

_EXCLUDED_DIRS = {
    ".git", "target", "build", "node_modules", ".gradle",
    "__pycache__", "bin", "obj", ".idea", ".vscode",
}
_ALLOWED_COMMANDS = {"mvn", "mvnw", "./mvnw", "gradle", "gradlew", "./gradlew", "javac", "java"}
_MAX_OUTPUT_CHARS = 20_000
_COMMAND_TIMEOUT_SECONDS = 180


def _workspace_root(tool_context: ToolContext) -> Path:
    root = (tool_context.state or {}).get("workspace_dir")
    if not root:
        raise ValueError("No workspace_dir set in session state.")
    return Path(root).resolve()


def _resolve_within_workspace(tool_context: ToolContext, relative_path: str) -> Path:
    """Resolve *relative_path* against the workspace root, rejecting any path
    that would escape it (e.g. via '..' or an absolute path)."""
    root = _workspace_root(tool_context)
    candidate = (root / relative_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path '{relative_path}' escapes the workspace root")
    return candidate


def list_files(tool_context: ToolContext, subdir: str = ".") -> str:
    """List every file in the repository workspace (or one subdirectory).

    Call this first, with subdir="." to see the whole repository tree,
    before reading any individual file.

    Args:
        subdir: Directory to list, relative to the workspace root.
            Defaults to the root of the repository.

    Returns:
        A newline-separated list of file paths relative to the workspace
        root, or a string starting with "ERROR:" on failure.
    """
    try:
        start = _resolve_within_workspace(tool_context, subdir)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not start.exists():
        return f"ERROR: '{subdir}' does not exist in the workspace."

    root = _workspace_root(tool_context)
    paths: list[str] = []
    for path in sorted(start.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if _EXCLUDED_DIRS & set(rel_parts):
            continue
        paths.append(str(path.relative_to(root)))
    return "\n".join(paths) if paths else "(no files found)"


def read_file(tool_context: ToolContext, path: str) -> str:
    """Read the full text content of one file in the repository workspace.

    Args:
        path: File path relative to the workspace root, exactly as
            returned by list_files.

    Returns:
        The file's text content, or a string starting with "ERROR:" if
        the file cannot be read.
    """
    try:
        target = _resolve_within_workspace(tool_context, path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not target.is_file():
        return f"ERROR: '{path}' is not a file in the workspace."
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"ERROR: could not read '{path}': {exc}"
    if len(content) > _MAX_OUTPUT_CHARS:
        return content[:_MAX_OUTPUT_CHARS] + f"\n\n[TRUNCATED — file exceeds {_MAX_OUTPUT_CHARS} chars]"
    return content


def write_file(tool_context: ToolContext, path: str, content: str) -> str:
    """Write (create or overwrite) one file in the repository workspace.

    Parent directories are created automatically. Always write the
    complete new content of the file — this is a full overwrite, not a
    patch/diff.

    Args:
        path: File path relative to the workspace root.
        content: The complete new content of the file.

    Returns:
        A short confirmation message, or a string starting with "ERROR:"
        on failure.
    """
    try:
        target = _resolve_within_workspace(tool_context, path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except Exception as exc:
        return f"ERROR: could not write '{path}': {exc}"
    return f"Wrote {len(content)} chars to {path}."


def run_command(tool_context: ToolContext, command: str) -> str:
    """Run one build/compile command inside the repository workspace.

    Only Maven, Gradle, and javac/java invocations are permitted (e.g.
    "mvn -q -DskipTests compile", "./mvnw test", "javac -d out Foo.java").
    The command runs with the workspace root as its working directory.
    No shell is invoked, so operators like ';', '&&', or '|' are not
    supported — issue one command per call.

    Args:
        command: The command line to execute, e.g.
            "mvn -q -DskipTests compile".

    Returns:
        The command's exit code and combined stdout/stderr (truncated if
        very long), or a string starting with "ERROR:" if the command
        could not be run at all.
    """
    try:
        root = _workspace_root(tool_context)
    except ValueError as exc:
        return f"ERROR: {exc}"

    try:
        args = shlex.split(command)
    except ValueError as exc:
        return f"ERROR: could not parse command: {exc}"
    if not args:
        return "ERROR: empty command."

    executable = Path(args[0]).name
    if executable not in _ALLOWED_COMMANDS:
        return (
            f"ERROR: '{executable}' is not permitted. Allowed commands: "
            f"{', '.join(sorted(_ALLOWED_COMMANDS))}."
        )

    try:
        result = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return f"ERROR: '{executable}' is not installed in this environment."
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {_COMMAND_TIMEOUT_SECONDS}s."

    output = (result.stdout or "") + (result.stderr or "")
    if len(output) > _MAX_OUTPUT_CHARS:
        output = output[:_MAX_OUTPUT_CHARS] + "\n\n[TRUNCATED]"
    return f"exit_code={result.returncode}\n{output}"


def signal_build_success(tool_context: ToolContext) -> str:
    """Call this ONLY after run_command shows the build succeeded (exit
    code 0, no compiler errors). Ends the validate/fix loop immediately
    instead of running the remaining iterations.
    """
    tool_context.actions.escalate = True
    tool_context.actions.skip_summarization = True
    return "Build success signalled — exiting the build loop."
