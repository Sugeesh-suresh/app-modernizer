"""
Per-file diff computation between the pristine uploaded workspace and the
migrated one, used for the final "Changed Files" view.

`snapshot_workspace` is called once, right after the repository is unpacked
and before any agent touches it. `compute_changed_files` is called once, at
the very end of the code-generation phase, comparing the snapshot against
the (now migrated) workspace — after which both directories are deleted.
"""
import difflib
import shutil
import tempfile
from pathlib import Path
from typing import Literal, TypedDict

from .dependency_graph import EXCLUDED_DIRS

_MAX_DIFF_CHARS = 20_000


class ChangedFile(TypedDict):
    path: str
    status: Literal["added", "modified", "deleted"]
    diff: str


def snapshot_workspace(workspace_dir: str) -> str:
    """Copy the workspace tree to a sibling temp directory before any agent
    modifies it. Returns the baseline directory path."""
    baseline_dir = tempfile.mkdtemp(prefix="modernizer-baseline-")
    shutil.copytree(workspace_dir, baseline_dir, dirs_exist_ok=True)
    return baseline_dir


def _list_relative_files(root: Path) -> set[str]:
    out: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if EXCLUDED_DIRS & set(path.relative_to(root).parts):
            continue
        out.add(str(path.relative_to(root)))
    return out


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def compute_changed_files(baseline_dir: str, workspace_dir: str) -> list[ChangedFile]:
    baseline_root = Path(baseline_dir).resolve()
    workspace_root = Path(workspace_dir).resolve()
    if not baseline_root.exists() or not workspace_root.exists():
        return []

    before_files = _list_relative_files(baseline_root)
    after_files = _list_relative_files(workspace_root)

    changed: list[ChangedFile] = []

    for rel in sorted(before_files | after_files):
        before_path = baseline_root / rel
        after_path = workspace_root / rel
        before_exists = rel in before_files
        after_exists = rel in after_files

        if before_exists and not after_exists:
            status: Literal["added", "modified", "deleted"] = "deleted"
            before_text, after_text = _read_text(before_path), ""
        elif after_exists and not before_exists:
            status = "added"
            before_text, after_text = "", _read_text(after_path)
        else:
            before_text = _read_text(before_path)
            after_text = _read_text(after_path)
            if before_text == after_text:
                continue
            status = "modified"

        diff_lines = list(
            difflib.unified_diff(
                before_text.splitlines(keepends=True),
                after_text.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )
        diff_text = "".join(diff_lines)
        if len(diff_text) > _MAX_DIFF_CHARS:
            diff_text = diff_text[:_MAX_DIFF_CHARS] + "\n\n[TRUNCATED — diff too large]"

        changed.append({"path": rel, "status": status, "diff": diff_text})

    return changed
