"""
Approved versions: the exact dependency and plugin versions a migration may
introduce, maintained by the people who know what the internal repository
(Nexus / Artifactory) actually serves.

A model choosing a version picks one it has seen somewhere — often one the
internal repository does not proxy or mirror, so the build fails to download
it (commonly as 401 from the repository manager). With this list, the version
is not the model's choice:

- the planner, the modifier and the fixer are given the list verbatim, as the
  only versions to use for those artifacts;
- validation fails, deterministically, on any version this migration
  introduced or changed that contradicts the list — or, with
  APPROVED_VERSIONS_STRICT, on any introduced version that is not on it;
- the preflight checks that every listed version actually downloads through
  the configured Maven settings, so a wrong list is caught before planning.

File format (APPROVED_VERSIONS_FILE, default approved-versions.txt next to
main.py) — one entry per line, `#` starts a comment:

    org.mockito:mockito-core = 2.28.2
    org.springframework:* = 5.3.34                    # every artifact of the group

    [java-8-to-25]                                    # only that pipeline
    org.springframework:* = 6.2.11

    [java-8-to-25 stage 3]                            # only that incremental stage
    org.springframework:* = 5.3.39

Entries before any section apply to every pipeline. The most specific entry
for an artifact wins: stage, then pipeline, then global. In an incremental
Java 8 -> 25 run that has stage sections, a stage is held to its own section
(plus global entries for artifacts no stage section mentions), so an
intermediate version set by an earlier stage is not flagged against the final
one.

Enforced in every pipeline that edits build files: the shared
`signal_build_success` refuses to end a build loop while a version this
migration introduced or changed contradicts the list (gate()).
"""
import re
from dataclasses import dataclass
from pathlib import Path

from .. import config

_LINE = re.compile(r"^\s*([\w.\-]+)\s*:\s*([\w.\-*]+)\s*[=:]\s*([^\s#]+)\s*(?:#\s*(.*))?$")


_SECTION = re.compile(r"^\[\s*([\w.\-]+)(?:\s+stage\s+(\d+))?\s*\]$", re.IGNORECASE)


@dataclass(frozen=True)
class Entry:
    group: str
    artifact: str          # "*" = every artifact of the group
    version: str
    note: str = ""
    line: int = 0
    pattern: str = ""      # "" = every pipeline
    stage: int | None = None

    @property
    def coordinate(self) -> str:
        return f"{self.group}:{self.artifact}"


def load(path: str | None = None) -> tuple[list[Entry], list[str]]:
    """(entries, problems with the file). A missing file is an empty list."""
    p = Path(path if path is not None else config.APPROVED_VERSIONS_FILE)
    if not p.is_file():
        return [], []
    entries: list[Entry] = []
    problems: list[str] = []
    seen: dict[tuple, Entry] = {}
    pattern, stage = "", None
    for n, raw in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        text = raw.split("#", 1)[0].strip() if raw.strip().startswith("[") else raw.strip()
        if not text or text.startswith("#"):
            continue
        sec = _SECTION.match(text)
        if sec:
            pattern, stage = sec.group(1).lower(), int(sec.group(2)) if sec.group(2) else None
            continue
        if text.startswith("["):
            problems.append(f"line {n}: `{text}` is not a section header like `[java-8-to-25]` or "
                            "`[java-8-to-25 stage 3]`")
            continue
        m = _LINE.match(text)
        if not m:
            problems.append(f"line {n}: `{text}` is not `groupId:artifactId = version`")
            continue
        entry = Entry(m.group(1), m.group(2), m.group(3), (m.group(4) or "").strip(), n, pattern, stage)
        key = (entry.coordinate, pattern, stage)
        if key in seen and seen[key].version != entry.version:
            problems.append(f"line {n}: `{entry.coordinate}` is listed twice in the same section with different "
                            f"versions ({seen[key].version}, {entry.version})")
            continue
        seen[key] = entry
        entries.append(entry)
    return entries, problems


def effective(entries: list[Entry], pattern: str | None = None, stage: int | None = None) -> list[Entry]:
    """The entries that apply to `pattern` (and incremental `stage`), the most
    specific per artifact. With stage sections for this pattern, a stage gets
    its own section plus global entries for artifacts no stage section names."""
    stage_sections = [e for e in entries if e.pattern == pattern and e.stage is not None]
    if stage is not None and stage_sections:
        staged = {e.coordinate for e in stage_sections}
        layers = [[e for e in entries if not e.pattern and e.coordinate not in staged],
                  [e for e in entries if e.pattern == pattern and e.stage == stage]]
    else:
        layers = [[e for e in entries if not e.pattern],
                  [e for e in entries if pattern and e.pattern == pattern and e.stage is None]]
    merged: dict[str, Entry] = {}
    for layer in layers:
        for e in layer:
            merged[e.coordinate] = e
    return list(merged.values())


def state_key(pattern: str, stage: int | None = None) -> str:
    """Session-state key holding the list for a pattern (and stage), for `{key?}` templating."""
    key = "approved_versions_" + re.sub(r"\W", "_", pattern)
    return key + (f"_stage{stage}" if stage is not None else "")


def state_values(patterns, stages_by_pattern: dict[str, list[int]] | None = None) -> dict[str, str]:
    """Every per-pattern (and per-stage) list as markdown, keyed by state_key."""
    entries, _ = load()
    out = {}
    for pattern in patterns:
        out[state_key(pattern)] = to_markdown(effective(entries, pattern))
        for stage in (stages_by_pattern or {}).get(pattern, []):
            out[state_key(pattern, stage)] = to_markdown(effective(entries, pattern, stage))
    return out


def gate(state: dict) -> list[str]:
    """Approved-version problems for the session's pattern (and current
    incremental stage), comparing the workspace with its uploaded baseline."""
    pattern = state.get("pattern") or ""
    if not pattern or not state.get("workspace_dir") or not state.get("baseline_dir"):
        return []
    entries, _ = load()
    stage = state.get("approved_stage")
    stage = int(stage) if str(stage or "").isdigit() else None
    scoped = effective(entries, pattern, stage)
    if not scoped and not config.APPROVED_VERSIONS_STRICT:
        return []
    return problems(state["baseline_dir"], state["workspace_dir"], scoped)


def lookup(entries: list[Entry], group: str, artifact: str) -> Entry | None:
    """The entry for g:a — an exact artifact entry wins over a group wildcard."""
    exact = next((e for e in entries if e.group == group and e.artifact == artifact), None)
    return exact or next((e for e in entries if e.group == group and e.artifact == "*"), None)


def to_markdown(entries: list[Entry], strict: bool | None = None) -> str:
    """The section the planner, modifier and fixer are given."""
    strict = config.APPROVED_VERSIONS_STRICT if strict is None else strict
    if not entries:
        return ("No approved-versions list is configured. Use only versions named by a build error, the "
                "plan's matrix, or the specification — never one you have not seen there.")
    rows = "\n".join(f"| `{e.coordinate}` | `{e.version}` | {e.note or ''} |" for e in entries)
    rule = ("**Strict:** these are the ONLY versions this migration may introduce. Any dependency or plugin "
            "version you would add or change that is not listed here must stay as uploaded — report it as "
            "needing an approved version instead of choosing one." if strict else
            "For any artifact listed here, use exactly this version — never another, never a newer or "
            "\"compatible\" one. For artifacts not listed, follow the plan's matrix.")
    return ("These versions were chosen by your organisation because they are available in its internal "
            "repository. A version that is not available there fails to download (often as 401). "
            "`groupId:*` applies to every artifact of that group.\n\n" + rule + "\n\n"
            "| Artifact | Version | Note |\n|---|---|---|\n" + rows)


def problems(baseline_dir: str, workspace_dir: str, entries: list[Entry] | None = None,
             strict: bool | None = None) -> list[str]:
    """Versions this migration introduced or changed that contradict the list
    (or, strict, are missing from it). Versions as uploaded are never flagged."""
    from .scope_fence import _resolved_coordinates
    if entries is None:
        entries = effective(load()[0], "java-8-to-11")
    strict = config.APPROVED_VERSIONS_STRICT if strict is None else strict
    if not entries and not strict:
        return []
    before = _resolved_coordinates(baseline_dir) if baseline_dir else {}
    after = _resolved_coordinates(workspace_dir) if workspace_dir else {}
    unchanged = set(before.items())
    out: list[str] = []
    for (rel, g, a), version in sorted(after.items()):
        if ((rel, g, a), version) in unchanged:
            continue
        entry = lookup(entries, g, a)
        if entry and entry.version != version:
            out.append(f"`{rel}` — `{g}:{a}:{version}` contradicts the approved version `{entry.version}` "
                       f"(approved-versions list, line {entry.line}) — use exactly `{entry.version}`")
            continue
        elif not entry and strict:
            out.append(f"`{rel}` — `{g}:{a}:{version}` is not on the approved-versions list "
                       "(APPROVED_VERSIONS_STRICT): restore the uploaded version, or have the version "
                       "approved and added to the list")
    return out
