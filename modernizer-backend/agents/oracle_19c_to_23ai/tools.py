"""
Workspace tools for the Oracle 19c -> 23ai pattern.

There is no live Oracle database to connect to in this environment, so
validation is a deterministic static syntax/heuristic check of SQL and
PL/SQL source files instead of a real execution — balanced block
structure, statement terminators, and a scan for deprecated packages/
syntax. The validator agent still does the judgment (reading the report
and deciding pass/fail as JSON) — only the fact-gathering is deterministic.
"""
import re

from google.adk.tools import ToolContext

from ..shared.workspace_tools import (  # noqa: F401 (re-exported)
    EXCLUDED_DIRS,
    list_files,
    read_file,
    signal_build_success,
    workspace_root,
    write_file,
)

_SQL_SUFFIXES = {".sql", ".pks", ".pkb", ".ddl", ".plsql", ".prc", ".fnc", ".trg"}

_BLOCK_OPENERS = re.compile(r"\b(BEGIN|CASE)\b", re.IGNORECASE)
_BLOCK_CLOSERS = re.compile(r"\bEND\b\s*(?:IF|LOOP|CASE)?\s*;", re.IGNORECASE)

_DEPRECATED_PATTERNS: list[tuple[str, str]] = [
    (r"\bDBMS_JAVA\b", "DBMS_JAVA usage found — review against 23ai's JVM/Java-in-database changes."),
    (r"\bDBMS_AQADM\.CREATE_QUEUE_TABLE\b.*\bcompatible\s*=>\s*'8\.", "AQ queue table created with a very old 'compatible' level — bump to a current release level."),
    (r"\bRAW\(\s*\d+\s*\)\s+DEFAULT\s+SYS_GUID\(\)", None),
    (r"\bCONNECT\s+BY\s+NOCYCLE\b", None),
    (r"\bLONG\b\s+(RAW\b)?", "LONG/LONG RAW columns are long-deprecated — migrate to CLOB/BLOB before or during this migration."),
    (r"\bDBMS_LOB\.SUBSTR\s*\([^)]*,\s*32767", "DBMS_LOB.SUBSTR with the old 32767-byte VARCHAR2 ceiling — 23ai supports larger VARCHAR2/LOB handling; review if this limit is now artificial."),
    (r"\bALTER\s+SESSION\s+SET\s+OPTIMIZER_FEATURES_ENABLE\s*=\s*'11\.", "OPTIMIZER_FEATURES_ENABLE pinned to an 11g-era value — review whether this still needs to be pinned on 23ai."),
]

def validate_sql_syntax(tool_context: ToolContext) -> str:
    """Statically validate every SQL/PLSQL file in the workspace.

    For each `.sql`/`.pks`/`.pkb`/`.ddl`/`.plsql`/`.prc`/`.fnc`/`.trg` file,
    checks that BEGIN/CASE blocks are balanced against END statements, that
    the file does not end mid-statement (missing terminating `;` or `/`),
    and scans for packages/syntax known to be deprecated or worth
    reviewing on the way to Oracle 23ai.

    Returns a plain-text report — one line per file checked, and one line
    per issue found (or "No issues found." if the file is clean). Read
    this report and decide pass/fail yourself; this tool does not decide
    anything.
    """
    root = workspace_root(tool_context)
    checked: list[str] = []
    lines: list[str] = []
    any_issue = False

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SQL_SUFFIXES:
            continue
        rel_parts = path.relative_to(root).parts
        if EXCLUDED_DIRS & set(rel_parts):
            continue
        rel = str(path.relative_to(root))
        checked.append(rel)

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            lines.append(f"{rel}: ISSUES FOUND")
            lines.append(f"  - could not read file — {exc}")
            any_issue = True
            continue

        file_issues: list[str] = []

        openers = len(_BLOCK_OPENERS.findall(text))
        closers = len(_BLOCK_CLOSERS.findall(text))
        if openers > closers:
            file_issues.append(
                f"possible unbalanced block — {openers} BEGIN/CASE opener(s) vs {closers} matching END terminator(s)"
            )

        stripped = text.rstrip()
        if stripped and not stripped.endswith((";", "/")):
            file_issues.append("file does not end with a statement terminator (';' or '/') — possible truncated statement")

        for pattern, message in _DEPRECATED_PATTERNS:
            if message and re.search(pattern, text, re.IGNORECASE):
                file_issues.append(message)

        if file_issues:
            any_issue = True
            lines.append(f"{rel}: ISSUES FOUND")
            for issue in file_issues:
                lines.append(f"  - {issue}")
        else:
            lines.append(f"{rel}: No issues found.")

    if not checked:
        return "No SQL/PLSQL files (.sql/.pks/.pkb/.ddl/.plsql/.prc/.fnc/.trg) found in the workspace."

    header = f"Checked {len(checked)} SQL/PLSQL file(s)."
    footer = "OVERALL: issues found." if any_issue else "OVERALL: no issues found."
    return "\n".join([header, *lines, footer])
