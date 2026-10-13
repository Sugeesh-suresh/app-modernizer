"""Walking a repository without entering what no scan wants.

`root.rglob("*")` visits every file under `node_modules`, `target`, `build` and `.git` and the caller then
throws them away by name. On a real application that is tens of thousands of files per scan — and every run
scans many times (the inventory, the companion detection, the audit, the change list, each discovery section).
`files()` never descends into an excluded folder, so the cost follows the sources, not the build output.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Iterator


def files(root: str | Path, pattern: str = "*", excluded: frozenset[str] | set[str] | None = None) -> Iterator[Path]:
    """Every file under `root` whose name matches `pattern` (fnmatch), in no particular order (sort if you
    need one), skipping any folder named in `excluded` (default: dependency_graph.EXCLUDED_DIRS — build
    output, dependencies, VCS and IDE folders). Symlinked folders are not followed."""
    if excluded is None:
        from .dependency_graph import EXCLUDED_DIRS
        excluded = EXCLUDED_DIRS
    base = os.fspath(root)
    match_all = pattern == "*"
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in excluded]
        for name in filenames:
            if match_all or fnmatch.fnmatchcase(name, pattern):
                yield Path(dirpath, name)
