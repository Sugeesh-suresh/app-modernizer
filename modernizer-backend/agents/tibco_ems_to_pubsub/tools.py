"""
Workspace tools for the TIBCO EMS -> Google Cloud Pub/Sub pattern.

Migrated output is usually a Java/Spring application using the Google
Cloud Pub/Sub client library, in which case validation is a real
`mvn`/`gradle` compile exactly like the Java pattern. When the workspace
has no `pom.xml`/`build.gradle` (e.g. only topic/subscription mapping
config was migrated, no application code), validation falls back to a
deterministic JSON/YAML well-formedness + topic-mapping completeness
check instead. validator_agent decides which applies by listing the
workspace first.
"""
import json
from pathlib import Path

from google.adk.tools import ToolContext

from ..shared.workspace_tools import (  # noqa: F401 (re-exported)
    EXCLUDED_DIRS,
    list_files,
    make_run_command,
    read_file,
    signal_build_success,
    workspace_root,
    write_file,
)

run_command = make_run_command({"mvn", "mvnw", "./mvnw", "gradle", "gradlew", "./gradlew", "javac", "java"})

_MAPPING_FILENAMES_HINT = ("pubsub", "topic", "subscription", "mapping", "destination")


def _try_parse(text: str, suffix: str):
    if suffix in (".json",):
        return json.loads(text)
    if suffix in (".yaml", ".yml"):
        import yaml  # PyYAML is already a transitive dependency of google-adk

        return yaml.safe_load(text)
    return None


def validate_pubsub_mapping(tool_context: ToolContext) -> str:
    """Statically validate JSON/YAML topic/subscription mapping config files
    in the workspace (used when there is no pom.xml/build.gradle to
    compile — i.e. no generated application code, config-only output).

    Checks well-formedness of every `.json`/`.yaml`/`.yml` file whose name
    hints at a Pub/Sub topic/subscription mapping, and flags any entry that
    still contains a TIBCO EMS-style queue/topic reference or a `jms://`
    connection string that should have been translated to a Pub/Sub
    topic/subscription resource name.

    Returns a plain-text report. Read it and decide pass/fail yourself;
    this tool does not decide anything.
    """
    root = workspace_root(tool_context)
    checked: list[str] = []
    lines: list[str] = []
    any_issue = False

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".json", ".yaml", ".yml"):
            continue
        rel_parts = path.relative_to(root).parts
        if EXCLUDED_DIRS & set(rel_parts):
            continue
        name_lower = path.name.lower()
        if not any(hint in name_lower for hint in _MAPPING_FILENAMES_HINT):
            continue

        rel = str(path.relative_to(root))
        checked.append(rel)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            lines.append(f"{rel}: ISSUES FOUND\n  - could not read file — {exc}")
            any_issue = True
            continue

        file_issues: list[str] = []
        try:
            _try_parse(text, path.suffix.lower())
        except Exception as exc:
            file_issues.append(f"parse error — {exc}")

        if "jms:" in text or "TIBCO" in text.upper() or "tibjms" in text.lower():
            file_issues.append("still references a TIBCO/JMS connection string or vendor name — should be fully translated to Pub/Sub topic/subscription resource names")

        if file_issues:
            any_issue = True
            lines.append(f"{rel}: ISSUES FOUND")
            for issue in file_issues:
                lines.append(f"  - {issue}")
        else:
            lines.append(f"{rel}: No issues found.")

    if not checked:
        return "No Pub/Sub topic/subscription mapping config files found in the workspace."

    header = f"Checked {len(checked)} mapping config file(s)."
    footer = "OVERALL: issues found." if any_issue else "OVERALL: no issues found."
    return "\n".join([header, *lines, footer])


__all__ = [
    "list_files", "read_file", "write_file", "run_command",
    "signal_build_success", "validate_pubsub_mapping",
]
