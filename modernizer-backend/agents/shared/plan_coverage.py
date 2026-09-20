"""
Deterministic conformance check of the migrated workspace against the File
Change Manifest in the plan the human confirmed.

`change_audit.py` asks whether a change *looks like* migration work, judged by
regex markers. This module asks the stricter, contractual question: did the run
do what the reviewer signed off on? The confirmed plan names every file it
intends to touch and what it will do to each, so three things are checkable
without an LLM:

  - **Planned but untouched** — the plan promised a change to a file that is
    byte-identical to the upload. Under-delivery: a manifest entry dropped
    between plan approval and the modifier run.
  - **Changed but unplanned** — a file nobody approved being edited. The plan
    is the scope agreement; anything outside it needs justifying.
  - **Contradicted** — an entry the plan explicitly marked "no change needed",
    which changed anyway.

Parsing is as forgiving as plan_tasks.py's, and for the same reason: the plan is
editable in the HITL review screen, so a reviewer's hand-edits must not silently
disable the check. Three manifest shapes are understood, because the plan skills
legitimately use different ones:

  - `### Task <id>` blocks with a `- Files:` line (the phased Java plan, whose
    task blocks are already load-bearing for the per-task modifier runs)
  - a `| \\`path\\` | change type | ... |` manifest table row
  - a bullet or checkbox line whose first backticked span is a path

Path matching is suffix-based, since a plan legitimately writes
`com/acme/Order.java` for `src/main/java/com/acme/Order.java`; a `*` anywhere
in the entry makes it a glob. Both are resolved against the real workspace
paths, never the other way round.
"""
import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path

from google.adk.tools import ToolContext

from .change_audit import changed_file_statuses, relevant_files
from .plan_tasks import parse_tasks

_BACKTICKED = re.compile(r"`([^`]+)`")
_TABLE_ROW = re.compile(r"^\s*\|(?P<cells>.+)\|\s*$", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*]\s+(?:\[[ xX]\]\s*)?(?P<body>.+?)\s*$", re.MULTILINE)
_FILES_LINE = re.compile(r"^\s*[-*]?\s*Files\s*:\s*(?P<files>.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_CHANGE_LINE = re.compile(r"^\s*[-*]?\s*Change\s*:\s*(?P<change>.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_TASK_HEADING = re.compile(r"^###\s+Task\s+([\w.\-]+)\s*:", re.MULTILINE)

# A path-shaped string has a separator or a known source/config extension —
# enough to keep prose out of the manifest without a filesystem lookup.
_PATH_LIKE = re.compile(
    r"[/\\]|\.(?:java|xml|yml|yaml|properties|gradle|kts|jsp|jspf|tag|tld|sql|pks|pkb|"
    r"js|jsx|ts|tsx|json|conf|cfg|md|txt)$",
    re.IGNORECASE,
)
_NO_CHANGE = re.compile(r"\bno\s+change(?:s)?\s+(?:needed|required)\b|\bunchanged\b", re.IGNORECASE)
_NOT_A_PATH = {"none", "n/a", "na", "file", "files", "path", "—", "-"}

_MAX_ROWS = 40
_MAX_TEXT = 160


@dataclass(frozen=True)
class PlannedFile:
    path: str
    change: str
    source: str
    no_change_expected: bool = False


@dataclass
class PlanCoverage:
    planned_total: int = 0
    changed_total: int = 0
    manifest_found: bool = True
    as_planned: list[tuple[PlannedFile, str]] = field(default_factory=list)
    missing: list[PlannedFile] = field(default_factory=list)
    unplanned: list[tuple[str, str]] = field(default_factory=list)
    contradicted: list[tuple[PlannedFile, str]] = field(default_factory=list)
    unresolved: list[PlannedFile] = field(default_factory=list)
    error: str = ""


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT] + " …"


#: Extensions a bare, directory-less filename may end in. Without this, every
#: dotted Java name in the plan's prose reads as a file: `org.apache.log4j`,
#: `com.fasterxml.jackson.databind` and `seq_order.NEXTVAL` all have the shape
#: of "stem dot extension" and none of them is a path.
_KNOWN_EXT = (
    ".java", ".xml", ".yml", ".yaml", ".properties", ".gradle", ".kts", ".jsp",
    ".jspf", ".tag", ".tld", ".sql", ".pks", ".pkb", ".plsql", ".js", ".jsx",
    ".ts", ".tsx", ".json", ".conf", ".cfg", ".md", ".html", ".css", ".txt",
)


def _looks_like_path(candidate: str) -> bool:
    candidate = candidate.strip().strip("`").strip()
    if not candidate or candidate.lower() in _NOT_A_PATH or " " in candidate:
        return False
    # Markup, not a path: a plan quotes `<packaging>jar</packaging>` to say what
    # a build file becomes, and the closing tag's slash otherwise reads as one.
    if "<" in candidate or ">" in candidate:
        return False
    if "/" not in candidate and "\\" not in candidate:
        # A bare filename needs a real stem and a known extension, so `pom.xml`
        # is kept while `.jsp` (prose about a file type) and `org.apache.log4j`
        # (a package name) are not.
        return (
            not candidate.startswith(".")
            and candidate.lower().endswith(_KNOWN_EXT)
        )
    return bool(_PATH_LIKE.search(candidate))


def _add(out: dict[str, PlannedFile], entry: PlannedFile) -> None:
    """First mention of a path wins, but a later entry that carries a real
    change description upgrades a bare one — a path can appear both in a task's
    `Files:` line and again in a stage's summary table."""
    existing = out.get(entry.path)
    if existing is None or (not existing.change and entry.change):
        out[entry.path] = entry


def parse_plan_manifest(plan: str) -> list[PlannedFile]:
    """Every file the confirmed plan says it will touch, with what it says will
    happen to it. Returns [] when the plan contains no recognisable manifest."""
    if not plan:
        return []
    out: dict[str, PlannedFile] = {}

    # 1 — task blocks (the phased Java plan). The task's `Change:` line is the
    # change description for every file on its `Files:` line.
    for task in parse_tasks(plan):
        change_match = _CHANGE_LINE.search(task.body)
        change = _clip(change_match.group("change")) if change_match else ""
        for path in task.files:
            if _looks_like_path(path):
                _add(out, PlannedFile(path.strip().strip("`"), change, f"Task {task.id}",
                                      bool(_NO_CHANGE.search(change))))

    # A `Files:` line outside any task block still names planned files.
    if not _TASK_HEADING.search(plan):
        for match in _FILES_LINE.finditer(plan):
            listed = match.group("files")
            found = _BACKTICKED.findall(listed) or [p.strip() for p in listed.split(",")]
            for path in found:
                if _looks_like_path(path):
                    _add(out, PlannedFile(path.strip().strip("`"), "", "Files: line"))

    # 2 — manifest table rows: | `path` | change type | what changes |
    for match in _TABLE_ROW.finditer(plan):
        cells = [c.strip() for c in match.group("cells").split("|")]
        if len(cells) < 2 or set("".join(cells)) <= set("-: "):
            continue
        backticked = _BACKTICKED.findall(cells[0])
        candidate = (backticked[0] if backticked else cells[0]).strip()
        if not _looks_like_path(candidate):
            continue
        # A cell holding only a dash is a deliberate blank (an unowned stage for a
        # "no change needed" row), not content — joining it yields "x — — — y".
        change = _clip(" — ".join(c for c in cells[1:] if c.strip(" -—–") ))
        _add(out, PlannedFile(candidate, change, "manifest table", bool(_NO_CHANGE.search(change))))

    # 3 — bullet / checkbox lines whose first backticked span is a path.
    for match in _BULLET.finditer(plan):
        body = match.group("body")
        backticked = _BACKTICKED.findall(body)
        if not backticked or not _looks_like_path(backticked[0]):
            continue
        path = backticked[0].strip()
        change = _clip(re.sub(r"^\s*[`]" + re.escape(path) + r"[`]\s*[—:-]*\s*", "", body))
        _add(out, PlannedFile(path, change, "manifest list", bool(_NO_CHANGE.search(change))))

    return sorted(out.values(), key=lambda e: e.path)


def _resolve(entry_path: str, actual_paths: list[str]) -> list[str]:
    """Real workspace paths an entry refers to.

    Exact match wins; then a glob if the entry has one; then a unique path
    suffix, so `com/acme/Order.java` resolves to the file under `src/main/java/`.
    An ambiguous suffix resolves to nothing — better unresolved and reported
    than silently matched to the wrong file.
    """
    raw = entry_path.strip().replace("\\", "/")
    normalised = raw.strip("/")
    if normalised in actual_paths:
        return [normalised]
    # A trailing slash means a directory: "_23 files under_ `src/main/com/acme/`"
    # is how a plan abbreviates a whole package, so resolve it to its contents.
    if raw.endswith("/"):
        prefix = normalised + "/"
        return [p for p in actual_paths if p.startswith(prefix) or f"/{prefix}" in p]
    if "*" in normalised or "?" in normalised:
        return [p for p in actual_paths if fnmatch.fnmatch(p, normalised) or fnmatch.fnmatch(p, f"*/{normalised}")]
    suffix_hits = [p for p in actual_paths if p == normalised or p.endswith("/" + normalised)]
    return suffix_hits if len(suffix_hits) == 1 else []


def compare_plan_to_changes(plan: str, baseline_dir: str, workspace_dir: str,
                            all_workspace_paths: list[str] | None = None) -> PlanCoverage:
    """Check the migrated workspace against the confirmed plan's manifest."""
    coverage = PlanCoverage()
    statuses = changed_file_statuses(baseline_dir, workspace_dir)
    if not baseline_dir or not workspace_dir:
        coverage.error = "baseline or workspace directory is unavailable — plan conformance could not be checked"
        return coverage

    changed = dict(statuses)
    coverage.changed_total = len(changed)

    planned = parse_plan_manifest(plan)
    coverage.planned_total = len(planned)
    if not planned:
        coverage.manifest_found = False
        coverage.unplanned = sorted(changed.items())
        return coverage

    # A planned file may resolve against a path that was never changed, so the
    # search space is every path the plan could mean, not just the changed ones.
    universe = sorted(set(changed) | set(all_workspace_paths or []))
    matched_actual: set[str] = set()

    for entry in planned:
        targets = _resolve(entry.path, universe)
        if not targets:
            # Fall back to the changed set alone, so the check still works when
            # the caller could not supply the full workspace listing.
            targets = _resolve(entry.path, sorted(changed))
        if not targets:
            coverage.unresolved.append(entry)
            continue
        touched = [t for t in targets if t in changed]
        matched_actual.update(touched)
        if not touched:
            if not entry.no_change_expected:
                coverage.missing.append(entry)
            continue
        for target in touched:
            if entry.no_change_expected:
                coverage.contradicted.append((entry, target))
            else:
                coverage.as_planned.append((entry, target))

    coverage.unplanned = sorted((p, s) for p, s in changed.items() if p not in matched_actual)
    return coverage


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _more(total: int) -> list[str]:
    return [f"  _(… and {total - _MAX_ROWS} more)_"] if total > _MAX_ROWS else []


def to_markdown(coverage: PlanCoverage) -> str:
    if coverage.error:
        return f"# Plan Conformance\n\nERROR: {coverage.error}"

    lines = [
        "# Plan Conformance (confirmed plan's manifest vs. what actually changed)",
        "",
        f"- Files named in the plan's manifest: **{coverage.planned_total}**",
        f"- Files actually changed: **{coverage.changed_total}**",
        f"- Changed exactly as planned: **{len(coverage.as_planned)}**",
    ]

    if not coverage.manifest_found:
        lines += [
            "",
            "## ⚠ No file manifest could be parsed from the confirmed plan",
            "",
            "The plan names no files in a recognisable manifest (a `### Task` block's `Files:` line, "
            "a manifest table row, or a bullet whose first backticked span is a path), so there is no "
            "approved scope to check this run against. Report this as a MEDIUM finding against the "
            "plan itself — a plan a human approved without a file list cannot be verified — and fall "
            "back to judging relevance from the change audit alone. Every changed file is listed "
            "below as unplanned purely because nothing was planned; do not report them individually.",
            "",
        ]
        for path, status in coverage.unplanned[:_MAX_ROWS]:
            lines.append(f"- `{path}` ({status})")
        lines += _more(len(coverage.unplanned))
        return "\n".join(lines)

    # 1 — planned but never touched.
    lines += ["", "## 1. Planned but NOT changed (under-delivery)", ""]
    if not coverage.missing:
        lines.append("None — every file the plan promised to change was changed.")
    else:
        lines.append(
            "The confirmed plan promised these files would change, and they are byte-identical to "
            "the upload. Unless a later stage owns the file, each is work the run agreed to do and "
            "did not — a HIGH finding, and the most likely cause of a migration that compiles but "
            "is incomplete. Quote the planned change when you report it."
        )
        lines.append("")
        for entry in coverage.missing[:_MAX_ROWS]:
            planned = f" — planned: {entry.change}" if entry.change else ""
            lines.append(f"- `{entry.path}` (from {entry.source}){planned}")
        lines += _more(len(coverage.missing))

    # 2 — changed without being planned.
    lines += ["", "## 2. Changed but NOT in the plan (unapproved scope)", ""]
    if not coverage.unplanned:
        lines.append("None — every changed file appears in the confirmed plan's manifest.")
    else:
        lines.append(
            "These files changed without appearing in the manifest a human approved. Some are "
            "legitimate: a build file the plan mentions only in prose, or a call site that had to "
            "follow a rename. Read each one and report the rest — an edit nobody approved is exactly "
            "what plan review exists to prevent."
        )
        lines.append("")
        for path, status in coverage.unplanned[:_MAX_ROWS]:
            lines.append(f"- `{path}` ({status})")
        lines += _more(len(coverage.unplanned))

    # 3 — explicitly excluded, changed anyway.
    if coverage.contradicted:
        lines += [
            "", "## 3. Marked \"no change needed\" in the plan, but changed", "",
            "The plan told the reviewer these files would be left alone. Each is a HIGH finding.", "",
        ]
        for entry, actual in coverage.contradicted[:_MAX_ROWS]:
            lines.append(f"- `{actual}` — plan said: {entry.change or 'no change needed'}")
        lines += _more(len(coverage.contradicted))

    # 4 — manifest entries that match no real file.
    if coverage.unresolved:
        lines += [
            "", "## 4. Manifest entries matching no file in the workspace", "",
            "The plan names these paths, but nothing in the repository matches them (or the path is "
            "ambiguous enough to match several). Usually a typo or an invented path in the plan "
            "itself, which means the work it described was never done — check each with list_files "
            "before deciding.", "",
        ]
        for entry in coverage.unresolved[:_MAX_ROWS]:
            lines.append(f"- `{entry.path}` (from {entry.source})")
        lines += _more(len(coverage.unresolved))

    lines += [
        "", "---", "",
        "Path matching is suffix-based and forgiving, and the plan is hand-editable, so confirm an "
        "entry with `read_file` or `list_files` before reporting it. A file listed under both this "
        "check and the change audit is one finding, not two: this says it was outside the approved "
        "scope, the audit says whether it was migration work at all.",
    ]
    return "\n".join(lines)


def compare_plan_to_actual_changes(tool_context: ToolContext) -> str:
    """Check what actually changed against the File Change Manifest in the plan
    the human confirmed — the approved scope for this run.

    Reports files the plan promised to change that are untouched (under-delivery),
    files that changed without being in the plan (unapproved scope), files the
    plan marked "no change needed" that changed anyway, and manifest entries
    matching no real file. Call this after audit_migration_changes: the audit
    says whether a change looks like migration work, this says whether it is
    work the reviewer actually signed off on.

    Returns:
        A markdown plan-conformance report, or a report saying the check could
        not run when the baseline snapshot or the plan is unavailable.
    """
    state = tool_context.state or {}
    workspace_dir = state.get("workspace_dir", "")
    plan = state.get("plan", "") or ""
    workspace_paths: list[str] = []
    if workspace_dir:
        root = Path(workspace_dir)
        if root.exists():
            workspace_paths = sorted(relevant_files(root.resolve()))
    return to_markdown(compare_plan_to_changes(
        plan, state.get("baseline_dir", ""), workspace_dir, workspace_paths,
    ))
