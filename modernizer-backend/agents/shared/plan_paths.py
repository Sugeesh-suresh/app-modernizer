"""
Reconcile the paths a plan names with the files that actually exist.

A planner shortens paths: `stella-ui-master/pom.xml` becomes `pom.xml`, which
matches no file at the root and every module's POM by suffix — so the task
that should edit the root POM edits nothing, and the reviewer later reports a
"manifest entry that does not exist". Checked right after planning, before a
person approves the plan:

- a path that exists is left alone;
- a path that resolves to exactly one file — under the repository's single
  top-level folder (how an uploaded ZIP usually wraps it), or as a unique
  suffix — is rewritten to the real path, in manifest rows and `Files:` lines
  only (prose that mentions "each module's `pom.xml`" is not touched);
- anything else is listed at the top of the plan, so the reviewer corrects it
  at plan review instead of discovering it after the run.
"""
import re
from pathlib import Path, PurePosixPath

from .dependency_graph import EXCLUDED_DIRS
from .plan_coverage import _resolve, parse_plan_manifest

NOTE_HEADING = "Paths not found in the repository"


def _workspace_paths(workspace_dir: str) -> list[str]:
    root = Path(workspace_dir)
    if not workspace_dir or not root.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and not (EXCLUDED_DIRS & set(p.relative_to(root).parts)))


def _real_path(entry: str, paths: list[str], tops: set[str]) -> str | None:
    """The one file `entry` means, or None when it is missing or ambiguous."""
    entry = entry.strip().strip("`").replace("\\", "/").strip("/")
    if entry in paths:
        return entry
    if len(tops) == 1:
        wrapped = f"{next(iter(tops))}/{entry}"
        if wrapped in paths:
            return wrapped
    hits = _resolve(entry, paths)
    return hits[0] if len(hits) == 1 else None


def reconcile(plan: str, workspace_dir: str) -> tuple[str, dict[str, str], list[str]]:
    """(plan, {written path: real path}, [paths not found or ambiguous])."""
    paths = _workspace_paths(workspace_dir)
    if not plan or not paths:
        return plan, {}, []
    tops = {p.split("/", 1)[0] for p in paths if "/" in p}
    if any("/" not in p for p in paths):
        tops = set()  # files at the root: no wrapper folder
    fixed: dict[str, str] = {}
    missing: list[str] = []
    for entry in parse_plan_manifest(plan):
        raw = entry.path.strip().strip("`")
        if raw.endswith("/") or "*" in raw or "?" in raw or raw in paths or raw in fixed or raw in missing:
            continue
        real = _real_path(raw, paths, tops)
        if real and real != raw:
            fixed[raw] = real
        elif not real and not entry.no_change_expected:
            missing.append(raw)

    if fixed:
        out = []
        for line in plan.splitlines(keepends=True):
            if line.lstrip().startswith("|") or re.match(r"\s*[-*]?\s*Files\s*:", line, re.IGNORECASE):
                for old, new in fixed.items():
                    line = line.replace(f"`{old}`", f"`{new}`")
            out.append(line)
        plan = "".join(out)

    if missing:
        listed = "\n".join(f"> - `{p}`" for p in missing)
        note = (f"> ⚠️ **{NOTE_HEADING}** — these planned paths match no file, or more than one. A task "
                "naming them will not change the file you intended. Correct them (or remove them) before "
                f"approving the plan; a file this migration creates should say so in its row.\n{listed}\n\n")
        plan = note + plan
    return plan, fixed, missing
