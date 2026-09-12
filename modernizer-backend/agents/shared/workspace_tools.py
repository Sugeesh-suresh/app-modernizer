"""
Real filesystem + build-execution tools shared by every migration pattern.

Each pattern's agents unpack the uploaded repository into a real per-session
workspace directory (see main.py's upload handler, which sets session
state["workspace_dir"]) and let their re/modifier/validator/fixer agents
interact with real files there via the tools below — mirroring
https://github.com/SahitiDamineni/java-migration-agent, whose own tools.py
describes itself as: "The LLM supplies the judgment; the tools are dumb
I/O (list, read, write, run)."

Every tool takes a `tool_context: ToolContext` parameter (ADK injects it
automatically based on the type annotation) so the workspace root can be
read from session state without threading it through every call.

`list_files`/`read_file`/`write_file`/`signal_build_success` are pattern-
agnostic and used as-is. `run_command` is pattern-specific (a Java pattern
allows `mvn`/`gradle`, others allow nothing or a different toolchain) so
it is built per pattern via `make_run_command`.
"""
import shlex
import subprocess
from pathlib import Path

from google.adk.tools import ToolContext

EXCLUDED_DIRS = {
    ".git", "target", "build", "node_modules", ".gradle",
    "__pycache__", "bin", "obj", ".idea", ".vscode",
}
MAX_OUTPUT_CHARS = 20_000
COMMAND_TIMEOUT_SECONDS = 180


def workspace_root(tool_context: ToolContext) -> Path:
    root = (tool_context.state or {}).get("workspace_dir")
    if not root:
        raise ValueError("No workspace_dir set in session state.")
    return Path(root).resolve()


def resolve_within_workspace(tool_context: ToolContext, relative_path: str) -> Path:
    """Resolve *relative_path* against the workspace root, rejecting any path
    that would escape it (e.g. via '..' or an absolute path)."""
    root = workspace_root(tool_context)
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
        start = resolve_within_workspace(tool_context, subdir)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not start.exists():
        return f"ERROR: '{subdir}' does not exist in the workspace."

    root = workspace_root(tool_context)
    paths: list[str] = []
    for path in sorted(start.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if EXCLUDED_DIRS & set(rel_parts):
            continue
        paths.append(str(path.relative_to(root)))
    return "\n".join(paths) if paths else "(no files found)"


def read_file(tool_context: ToolContext, path: str, start_line: int = 1, max_lines: int = 0) -> str:
    """Read one file from the repository workspace, one window at a time.

    A file too large for a single response comes back in windows. The header
    line always says which lines you received and how to ask for the rest —
    never assume the file ends where a window ends.

    Args:
        path: File path relative to the workspace root, exactly as
            returned by list_files.
        start_line: 1-based line number to start reading from. Defaults to
            the first line.
        max_lines: Maximum number of lines to return. 0 (the default) means
            as many as fit in one window.

    Returns:
        A header line ("# <path> — lines A-B of N") followed by that window
        of the file, or a string starting with "ERROR:" if it cannot be read.
    """
    try:
        target = resolve_within_workspace(tool_context, path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not target.is_file():
        return f"ERROR: '{path}' is not a file in the workspace."
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"ERROR: could not read '{path}': {exc}"

    lines = content.splitlines()
    total = len(lines)
    if total == 0:
        return f"# {path} — empty file (0 lines)"
    start = max(start_line, 1)
    if start > total:
        return f"ERROR: '{path}' has {total} lines; start_line={start} is past the end."

    window = lines[start - 1:]
    if max_lines > 0:
        window = window[:max_lines]

    # Trim to the output budget on a line boundary, so a window is never a half line.
    kept: list[str] = []
    used = 0
    for line in window:
        used += len(line) + 1
        if used > MAX_OUTPUT_CHARS and kept:
            break
        kept.append(line)

    end = start + len(kept) - 1
    header = f"# {path} — lines {start}-{end} of {total}"
    if end < total:
        header += f" (not the whole file: call read_file again with start_line={end + 1})"
    return header + "\n" + "\n".join(kept)


def write_file(tool_context: ToolContext, path: str, content: str,
               allow_full_overwrite: bool = False) -> str:
    """Write a new file, or replace an existing file's entire content.

    Parent directories are created automatically. For an edit to an existing
    file, prefer replace_in_file: it costs far fewer tokens and cannot drop
    the parts of the file you did not send. Overwriting a file that is larger
    than one read window is refused unless you have actually read every
    window of it and pass allow_full_overwrite=True — otherwise the content
    you never saw would be silently deleted.

    Args:
        path: File path relative to the workspace root.
        content: The complete new content of the file.
        allow_full_overwrite: Set True only after reading the whole file, to
            confirm a deliberate full rewrite of a large file.

    Returns:
        A short confirmation message, or a string starting with "ERROR:"
        on failure.
    """
    try:
        target = resolve_within_workspace(tool_context, path)
    except ValueError as exc:
        return f"ERROR: {exc}"

    if target.is_file() and not allow_full_overwrite:
        try:
            existing = target.stat().st_size
        except OSError:
            existing = 0
        if existing > MAX_OUTPUT_CHARS:
            return (
                f"ERROR: '{path}' is {existing} chars, larger than one {MAX_OUTPUT_CHARS}-char read "
                "window, so a full overwrite would delete content you have not read. Use "
                "replace_in_file for targeted edits, or read every window of the file first and "
                "call write_file again with allow_full_overwrite=True."
            )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except Exception as exc:
        return f"ERROR: could not write '{path}': {exc}"
    return f"Wrote {len(content)} chars to {path}."


def replace_in_file(tool_context: ToolContext, path: str, old_text: str, new_text: str,
                    expected_count: int = 1) -> str:
    """Replace an exact snippet inside one file, leaving everything else untouched.

    This is the preferred way to edit an existing file — an import, an
    annotation, a method body, a dependency block. It costs a fraction of the
    tokens of a full rewrite and cannot truncate the rest of the file.

    Args:
        path: File path relative to the workspace root.
        old_text: The exact text to replace, copied verbatim from read_file
            output including indentation. Include enough surrounding lines to
            make it unique within the file.
        new_text: The replacement text. Pass "" to delete old_text.
        expected_count: How many occurrences you expect to replace. The edit
            is refused unless the file contains exactly this many.

    Returns:
        A short confirmation message, or a string starting with "ERROR:"
        on failure.
    """
    try:
        target = resolve_within_workspace(tool_context, path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not target.is_file():
        return f"ERROR: '{path}' is not a file in the workspace."
    if not old_text:
        return "ERROR: old_text is empty — use write_file to create or fully replace a file."
    if old_text == new_text:
        return "ERROR: old_text and new_text are identical — nothing to do."

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"ERROR: could not read '{path}': {exc}"

    found = content.count(old_text)
    if found == 0:
        return (
            f"ERROR: old_text was not found in '{path}'. Copy it verbatim from read_file output "
            "(indentation and line breaks must match exactly)."
        )
    if found != expected_count:
        return (
            f"ERROR: old_text occurs {found} times in '{path}', not {expected_count}. Add surrounding "
            f"lines to make it unique, or pass expected_count={found} to replace them all."
        )

    updated = content.replace(old_text, new_text)
    try:
        target.write_text(updated, encoding="utf-8")
    except Exception as exc:
        return f"ERROR: could not write '{path}': {exc}"
    return f"Replaced {found} occurrence(s) in {path} (file is now {len(updated)} chars)."


def make_run_command(allowed_commands: set[str]):
    """Build a `run_command` tool restricted to *allowed_commands* executables.

    Each pattern has a different toolchain (Java: mvn/gradle; others: no
    real compiler at all, in which case the pattern simply omits this tool
    and relies solely on its deterministic `validate_*` tool instead).
    """
    allowed = set(allowed_commands)
    allowed_list = ", ".join(sorted(allowed))

    def run_command(tool_context: ToolContext, command: str, subdir: str = ".") -> str:
        try:
            root = workspace_root(tool_context)
            cwd = resolve_within_workspace(tool_context, subdir)
        except ValueError as exc:
            return f"ERROR: {exc}"
        if not cwd.exists():
            return f"ERROR: '{subdir}' does not exist in the workspace."

        try:
            args = shlex.split(command)
        except ValueError as exc:
            return f"ERROR: could not parse command: {exc}"
        if not args:
            return "ERROR: empty command."

        executable = Path(args[0]).name
        if executable not in allowed:
            return f"ERROR: '{executable}' is not permitted. Allowed commands: {allowed_list}."

        try:
            result = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            return f"ERROR: '{executable}' is not installed in this environment."
        except subprocess.TimeoutExpired:
            return f"ERROR: command timed out after {COMMAND_TIMEOUT_SECONDS}s."

        output = (result.stdout or "") + (result.stderr or "")
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\n\n[TRUNCATED]"
        return f"exit_code={result.returncode}\n{output}"

    run_command.__doc__ = (
        "Run one build/compile command inside the repository workspace (or one "
        "subdirectory of it, e.g. a `backend/` or `frontend/` tree generated by "
        "a multi-target pipeline).\n\n"
        f"Only these executables are permitted: {allowed_list} (e.g. "
        f'"{sorted(allowed)[0]} -q -DskipTests compile"). No shell is invoked, so '
        "operators like ';', '&&', or '|' are not supported — issue one command "
        "per call.\n\n"
        "Args:\n"
        "    command: The command line to execute.\n"
        "    subdir: Directory to run the command in, relative to the workspace "
        "root. Defaults to the workspace root itself.\n\n"
        "Returns:\n    The command's exit code and combined stdout/stderr "
        "(truncated if very long), or a string starting with \"ERROR:\" if "
        "the command could not be run at all."
    )
    return run_command


def signal_build_success(tool_context: ToolContext) -> str:
    """Call this ONLY after the validation tool shows the build/config
    succeeded (e.g. exit code 0, no compiler errors, no config errors).
    Ends the validate/fix loop immediately instead of running the
    remaining iterations.
    """
    tool_context.actions.escalate = True
    tool_context.actions.skip_summarization = True
    return "Build success signalled — exiting the build loop."
