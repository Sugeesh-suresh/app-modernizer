"""
Workspace tools for the Java 8 -> Java 11 pattern: the shared Java toolchain
tools, with `write_file` and `replace_in_file` wrapped in the pattern's scope
fence (agents/shared/scope_fence.py).

This pattern upgrades the JDK of an application that keeps its JSP views and
its WildFly deployment exactly as they are. The wrappers make that a property
of the tools rather than a request in a prompt: an agent holding them cannot
write a JSP, a WildFly descriptor, anything under `src/main/webapp/`, or any
file other than a `.java` source or a build file -- and cannot make a build or
source edit that changes the packaging, the archive name, the WildFly
deployment plugin, the WAR plugin's configuration, overshoots Java 11,
introduces Spring Boot, or adds a `jakarta.*` import. The refusal comes back
as an `ERROR:` string, the same channel every other tool failure uses, so the
agent reads why and adjusts.

`check_java11_invariants` is the validator's deterministic half: the build
loop exits green only when the real build passes AND this reports PASS.
"""
from google.adk.tools import ToolContext

from ..shared import scope_fence
from ..shared import workspace_tools as _ws
from ..shared.workspace_tools import (  # noqa: F401 (re-exported)
    list_files,
    make_run_command,
    read_file,
)

PATTERN = "java-8-to-11"

run_command = make_run_command({"mvn", "mvnw", "./mvnw", "gradle", "gradlew", "./gradlew", "javac", "java"})


def _relative(tool_context: ToolContext, path: str) -> str | None:
    try:
        target = _ws.resolve_within_workspace(tool_context, path)
    except ValueError:
        return None
    return target.relative_to(_ws.workspace_root(tool_context)).as_posix()


def _current_text(tool_context: ToolContext, path: str) -> str:
    try:
        target = _ws.resolve_within_workspace(tool_context, path)
        return target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
    except (ValueError, OSError):
        return ""


def _refusal(tool_context: ToolContext, path: str, before: str, after: str) -> str | None:
    rel = _relative(tool_context, path)
    if rel is None:
        return None  # let the shared tool report the bad path in its own words
    ok, reason = scope_fence.writable(PATTERN, rel)
    if not ok:
        return f"ERROR: refused to write '{rel}': {reason}."
    problems = scope_fence.check_edit(PATTERN, rel, before, after)
    if problems:
        return (
            f"ERROR: refused the edit to '{rel}' — it would break the Java 11 migration's fence:\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\nMake the change without breaking these, or report it for a human if it cannot be done."
        )
    return None


def write_file(tool_context: ToolContext, path: str, content: str,
               allow_full_overwrite: bool = False) -> str:
    """Write a new file, or replace an existing file's entire content.

    Scope: only `.java` sources and build files (pom.xml, build.gradle,
    settings.gradle, gradle.properties, wrapper properties) may be written.
    JSP files, WildFly/JBoss descriptors, web.xml, anything under
    src/main/webapp, WEB-INF or META-INF, and container launch configuration
    are frozen and every write to them is refused.

    Parent directories are created automatically. For an edit to an existing
    file, prefer replace_in_file: it costs far fewer tokens and cannot drop
    the parts of the file you did not send. Overwriting a file that is larger
    than one read window is refused unless you have actually read every
    window of it and pass allow_full_overwrite=True.

    Args:
        path: File path relative to the workspace root.
        content: The complete new content of the file.
        allow_full_overwrite: Set True only after reading the whole file, to
            confirm a deliberate full rewrite of a large file.

    Returns:
        A short confirmation message, or a string starting with "ERROR:"
        on failure or refusal.
    """
    refusal = _refusal(tool_context, path, _current_text(tool_context, path), content)
    if refusal:
        return refusal
    return _ws.write_file(tool_context, path, content, allow_full_overwrite)


def replace_in_file(tool_context: ToolContext, path: str, old_text: str, new_text: str,
                    expected_count: int = 1) -> str:
    """Replace an exact snippet inside one file, leaving everything else untouched.

    This is the preferred way to edit an existing file — an import, a method
    body, a dependency block. Scope: only `.java` sources and build files may
    be edited; JSP, WildFly/JBoss descriptors, web.xml and everything under
    src/main/webapp, WEB-INF or META-INF are frozen and refused.

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
        on failure or refusal.
    """
    before = _current_text(tool_context, path)
    # Only simulate an edit the shared tool would actually apply; anything else
    # (text not found, wrong count) is left to it to report precisely.
    after = before.replace(old_text, new_text) if old_text and before.count(old_text) == expected_count else before
    refusal = _refusal(tool_context, path, before, after)
    if refusal:
        return refusal
    return _ws.replace_in_file(tool_context, path, old_text, new_text, expected_count)


def check_java11_invariants(tool_context: ToolContext) -> str:
    """Deterministically check the migrated workspace against the Java 11
    migration's fence, comparing it with the pristine uploaded baseline.

    Checks that every JSP / WildFly / web-root file is byte-identical to the
    upload; that no pom.xml changed its packaging, finalName, WildFly/JBoss
    plugin or maven-war-plugin configuration; that no build introduced Spring
    Boot or a Java level past 11; that no `jakarta.*` import was added; and
    that every build file declaring a Java level declares exactly 11.

    Returns:
        A plain-text report ending in "OVERALL: PASS" or "OVERALL: FAIL".
        FAIL means validation failed, even if the build itself succeeded.
    """
    state = tool_context.state or {}
    problems, notes = scope_fence.verify_invariants(
        PATTERN, state.get("baseline_dir", ""), state.get("workspace_dir", ""),
    )
    return scope_fence.to_markdown(PATTERN, problems, notes)


def signal_build_success(tool_context: ToolContext) -> str:
    """Call this ONLY after the build command succeeded (exit code 0, no
    compiler errors) AND check_java11_invariants reported OVERALL: PASS.
    Ends the validate/fix loop immediately instead of running the remaining
    iterations. Refused while the Java 11 fence invariants still fail, so a
    green build can never end the loop with a frozen file changed.
    """
    state = tool_context.state or {}
    problems, _ = scope_fence.verify_invariants(
        PATTERN, state.get("baseline_dir", ""), state.get("workspace_dir", ""),
    )
    if problems:
        return (
            "ERROR: build success NOT signalled — the Java 11 fence invariants fail, so validation "
            "has failed even though the build may have passed. Report these as errors:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )
    return _ws.signal_build_success(tool_context)


__all__ = [
    "list_files", "read_file", "replace_in_file", "write_file", "run_command",
    "signal_build_success", "check_java11_invariants",
]
