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
import fnmatch
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from google.adk.tools import ToolContext

# Single source of truth — this used to be a byte-identical copy, free to drift
# from the one the diff and the change audit use.
from .. import config
from .dependency_graph import EXCLUDED_DIRS  # noqa: F401

#: Every budget is read from `config` at CALL time inside the tools below, not
#: bound at import, so a deployment can raise it by environment variable and a
#: test can override it -- the same way main.py reads the ingestion caps.
#:
#: These two names are kept only as a compatibility shim for existing importers
#: (tests/test_workspace_tools_edit.py reads MAX_OUTPUT_CHARS). Nothing in this
#: module uses them, and because they are bound at import they will NOT track a
#: runtime override of config -- read `config.READ_FILE_MAX_CHARS` /
#: `config.COMMAND_TIMEOUT_SECONDS` directly instead.
MAX_OUTPUT_CHARS = config.READ_FILE_MAX_CHARS
COMMAND_TIMEOUT_SECONDS = config.COMMAND_TIMEOUT_SECONDS


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


def _directory_summary(paths: list[str], depth: int = 2) -> str:
    """`dir → file count` rollup, for a tree too big to list path by path.

    Lets an agent see the shape of a monorepo -- which modules exist and how big
    each one is -- and then page into the parts that matter, instead of spending
    its whole context on a flat listing of paths most of which it will never read.
    """
    counts: dict[str, int] = {}
    for rel in paths:
        parts = rel.split("/")
        key = "/".join(parts[:depth]) if len(parts) > depth else ("/".join(parts[:-1]) or ".")
        counts[key] = counts.get(key, 0) + 1
    widest = max((len(k) for k in counts), default=0)
    return "\n".join(
        f"  {key.ljust(widest)}  {count:>7,} files"
        for key, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    )


def list_files(tool_context: ToolContext, subdir: str = ".", offset: int = 0,
               max_paths: int = 0, summary: bool = False) -> str:
    """List files in the repository workspace, one page at a time.

    Call this first with subdir="." to see the repository. On a large repository
    the first page comes back with a directory rollup showing where the files
    are, so you can list or read the parts that matter instead of paging through
    everything. Never assume the repository ends where a page ends -- the header
    always says how many files there are in total.

    Args:
        subdir: Directory to list, relative to the workspace root. Defaults to
            the root of the repository.
        offset: 0-based index into the sorted file list to start from. Use the
            value the previous page's header tells you.
        max_paths: Maximum number of paths to return in this page. 0 (the
            default) means the server's page size.
        summary: True returns ONLY the directory rollup with no individual
            paths -- the cheapest way to understand a big tree's layout.

    Returns:
        A header line saying which files you received and how many exist,
        followed by that page of paths, or a string starting with "ERROR:".
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
        rel = path.relative_to(root)
        if EXCLUDED_DIRS & set(rel.parts):
            continue
        paths.append(rel.as_posix())

    total = len(paths)
    if total == 0:
        return f"# {subdir} — (no files found)"

    if summary:
        return (
            f"# {subdir} — {total:,} files, directory rollup only\n"
            f"{_directory_summary(paths)}\n"
            "# Call list_files again without summary=True (or with a narrower subdir) for paths."
        )

    limit = max_paths if max_paths > 0 else config.LIST_FILES_MAX_PATHS
    begin = max(offset, 0)
    if begin >= total:
        return f"ERROR: '{subdir}' has {total} files; offset={begin} is past the end."
    page = paths[begin:begin + limit]
    end = begin + len(page)

    header = f"# {subdir} — files {begin + 1}-{end} of {total:,}"
    parts = []
    if end < total:
        header += f" (more remain: call list_files again with offset={end})"
        # The rollup only earns its tokens when there is more than one page; on a
        # small repo the listing itself already shows the layout.
        parts.append(
            f"# Where the {total:,} files are (top-2 levels):\n{_directory_summary(paths)}\n"
            "# Narrowing with subdir= is usually cheaper than paging through every file."
        )
    return "\n".join([header, *parts, "\n".join(page)])


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
        if used > config.READ_FILE_MAX_CHARS and kept:
            break
        kept.append(line)

    end = start + len(kept) - 1
    header = f"# {path} — lines {start}-{end} of {total}"
    if end < total:
        header += f" (not the whole file: call read_file again with start_line={end + 1})"
    return header + "\n" + "\n".join(kept)


_SEARCH_LINE_CHARS = 200


def search_files(tool_context: ToolContext, pattern: str, glob: str = "*", subdir: str = ".",
                 ignore_case: bool = False, files_only: bool = False, offset: int = 0) -> str:
    """Search the CONTENTS of workspace files for a regular expression.

    This is how to find every use of an API, import or configuration key
    across the repository without reading each file. It is read-only and runs
    no code. Combine related terms into one pattern with `|` rather than
    making one call per term.

    Args:
        pattern: A Python regular expression, matched line by line
            (e.g. `sun[.]misc[.]BASE64|javax[.]xml[.]bind`; `[.]` is a literal dot).
        glob: Which files to search, matched against the path relative to the
            workspace root. `*` matches across folders, so `*.java` means every
            Java file at any depth and `*.jsp` every JSP. Several globs may be
            separated by `,` (e.g. `*.jsp,*.jspf,*.tag`). Defaults to all files.
        subdir: Only search under this directory. Defaults to the whole repository.
        ignore_case: Match case-insensitively.
        files_only: Return one line per matching file with its match count,
            instead of every matching line — the cheap way to size a finding
            or count files per category.
        offset: 0-based index of the first result to return. Use the value the
            previous page's header tells you.

    Returns:
        A header stating the total matches and files and which page this is,
        then `path:line: text` lines (or `path: N matches` with files_only),
        or a string starting with "ERROR:".
    """
    try:
        start = resolve_within_workspace(tool_context, subdir)
        root = workspace_root(tool_context)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not start.exists():
        return f"ERROR: '{subdir}' does not exist in the workspace."
    try:
        regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        return f"ERROR: invalid regular expression {pattern!r}: {exc}"
    globs = [g.strip() for g in (glob or "*").split(",") if g.strip()] or ["*"]

    hits: list[str] = []
    per_file: list[tuple[str, int]] = []
    scanned = skipped_large = 0
    for path in sorted(start.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if EXCLUDED_DIRS & set(rel.parts):
            continue
        rel_posix = rel.as_posix()
        if not any(fnmatch.fnmatch(rel_posix, g) or fnmatch.fnmatch(path.name, g) for g in globs):
            continue
        try:
            if path.stat().st_size > config.SEARCH_MAX_FILE_BYTES:
                skipped_large += 1
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        count = 0
        for number, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                count += 1
                if not files_only:
                    line = line.strip()
                    if len(line) > _SEARCH_LINE_CHARS:
                        line = line[:_SEARCH_LINE_CHARS] + " …"
                    hits.append(f"{rel_posix}:{number}: {line}")
        if count:
            per_file.append((rel_posix, count))

    total_matches = sum(c for _, c in per_file)
    results = [f"{p}: {c} match{'es' if c != 1 else ''}" for p, c in per_file] if files_only else hits
    page_size = config.SEARCH_MAX_RESULTS
    offset = max(offset, 0)
    page = results[offset:offset + page_size]

    header = (
        f"# search {pattern!r} in {', '.join(globs)}: {total_matches} matching line(s) in "
        f"{len(per_file)} file(s); {scanned} file(s) searched"
    )
    if skipped_large:
        header += (f"; {skipped_large} file(s) over {config.SEARCH_MAX_FILE_BYTES:,} bytes NOT searched")
    if not results:
        return header + " — no matches."
    end = offset + len(page)
    header += f" — showing {offset + 1}-{end} of {len(results)}"
    if end < len(results):
        header += f" (not all: call search_files again with offset={end})"
    return header + "\n" + "\n".join(page)


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
        if existing > config.READ_FILE_MAX_CHARS:
            return (
                f"ERROR: '{path}' is {existing} chars, larger than one "
                f"{config.READ_FILE_MAX_CHARS}-char read "
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


def _clip_command_output(output: str, budget: int = 0) -> str:
    """Trim build output to *budget* chars, keeping both ends.

    Head-first truncation was actively harmful here: a Maven reactor build opens
    with hundreds of lines of module banners and dependency resolution, and puts
    every `[ERROR]` diagnostic and the reactor summary at the END. Cutting the
    tail handed the fixer the part with no errors in it and hid the part it
    needed, so it "fixed" what it could see and the loop burned its iterations.
    """
    budget = budget or config.COMMAND_OUTPUT_MAX_CHARS
    if len(output) <= budget:
        return output

    # Two thirds to the tail: that is where diagnostics and the failure summary
    # are, while the head still shows which command and which modules ran.
    tail_chars = (budget * 2) // 3
    head_chars = budget - tail_chars
    head = output[:head_chars]
    tail = output[-tail_chars:]
    dropped = len(output) - head_chars - tail_chars
    return (
        f"{head}\n\n[... {dropped:,} characters omitted from the MIDDLE of the output. "
        "The head and tail are shown; compiler diagnostics and the build summary are in the "
        "tail below. If you need the omitted middle, re-run a narrower build (e.g. one "
        "module via subdir=) rather than assuming what it said. ...]\n\n"
        f"{tail}"
    )


_WINDOWS = os.name == "nt"
#: Suffixes Windows launchers carry that the allow-list does not: `mvn` is really
#: `mvn.cmd`, the Maven/Gradle wrappers are `mvnw.cmd` / `gradlew.bat`.
_WINDOWS_SUFFIXES = (".cmd", ".bat", ".exe")
_WRAPPERS = {"mvnw", "gradlew"}


def _split_command(command: str) -> list[str]:
    """Split *command* into argv. POSIX rules eat backslashes, which are path
    separators on Windows, so there the non-POSIX splitter is used and the
    quotes it leaves around a token are removed."""
    if not _WINDOWS:
        return shlex.split(command)
    return [
        arg[1:-1] if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in "\"'" else arg
        for arg in shlex.split(command, posix=False)
    ]


def _command_name(arg0: str) -> str:
    """The allow-list key for an executable: its bare name, without a Windows
    launcher suffix, so `mvn.cmd` and `.\\mvnw.cmd` are checked as `mvn`/`mvnw`."""
    name = arg0.replace("\\", "/").rsplit("/", 1)[-1]
    lowered = name.lower()
    for suffix in _WINDOWS_SUFFIXES:
        if lowered.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _resolve_executable(arg0: str, cwd: Path) -> str:
    """The program to hand to subprocess.

    On Linux/macOS this is *arg0* unchanged. On Windows, CreateProcess does not
    consult PATHEXT, so a bare `mvn`/`gradle`/`npm` is never found even when it
    is installed -- every build reported "not installed". PATH lookups go
    through shutil.which, which does, and a repository's own wrapper (`mvnw`,
    `./gradlew`) resolves to the `.cmd`/`.bat` twin Maven and Gradle ship
    beside the shell script, which Windows cannot run.
    """
    if not _WINDOWS:
        return arg0
    path_like = "/" in arg0 or "\\" in arg0
    name = _command_name(arg0)
    if path_like or name in _WRAPPERS:
        folder = (cwd / arg0).parent if path_like else cwd
        for suffix in _WINDOWS_SUFFIXES:
            candidate = folder / (name + suffix)
            if candidate.is_file():
                return str(candidate)
        return arg0
    return shutil.which(arg0) or arg0


def make_run_command(allowed_commands: set[str], env_factory=None, extra_args=None):
    """Build a `run_command` tool restricted to *allowed_commands* executables.

    Each pattern has a different toolchain (Java: mvn/gradle; others: no
    real compiler at all, in which case the pattern simply omits this tool
    and relies solely on its deterministic `validate_*` tool instead).

    env_factory() returns the process environment (e.g. JAVA_HOME for a
    specific JDK); extra_args(args) returns arguments to add to a Maven call
    (e.g. `-s settings.xml`). Both default to the server's own environment.
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
            args = _split_command(command)
        except ValueError as exc:
            return f"ERROR: could not parse command: {exc}"
        if not args:
            return "ERROR: empty command."

        executable = _command_name(args[0])
        if executable not in allowed:
            return f"ERROR: '{executable}' is not permitted. Allowed commands: {allowed_list}."

        if extra_args and executable in ("mvn", "mvnw", "./mvnw"):
            args = [args[0], *extra_args(args[1:]), *args[1:]]
        try:
            result = subprocess.run(
                [_resolve_executable(args[0], cwd), *args[1:]],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=config.COMMAND_TIMEOUT_SECONDS,
                env=env_factory() if env_factory else None,
            )
        except FileNotFoundError:
            return f"ERROR: '{executable}' is not installed in this environment."
        except subprocess.TimeoutExpired:
            # Named as a timeout rather than a build failure: a reactor build that
            # ran out of clock says nothing about whether the code compiles, and
            # reporting it as a failure sends the fixer hunting for errors that
            # were never emitted.
            return (
                f"ERROR: command timed out after {config.COMMAND_TIMEOUT_SECONDS}s without "
                "finishing. "
                "This is a TIMEOUT, not a compile failure — no diagnostics were produced, so do "
                "not infer any. Either build one module at a time with subdir=, or ask for "
                "COMMAND_TIMEOUT_SECONDS to be raised."
            )

        output = _clip_command_output((result.stdout or "") + (result.stderr or ""))
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
