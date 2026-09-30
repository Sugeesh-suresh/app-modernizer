"""
Mechanical rewrites for the Java 8 -> 11 run: changes that are exact,
behaviour-preserving and too numerous to spend a model task per file on.

`org.mockito.runners.MockitoJUnitRunner` -> `org.mockito.junit.MockitoJUnitRunner`.
In Mockito 2.x and 3.x the old class is a deprecated subclass of the new one
(verified against mockito-core 2.28.2 and 3.12.4), so the rewrite changes no
behaviour; it removes a deprecation and an import that Mockito 4 deletes. A
large monolith can have hundreds of these test files — in real runs the
modifier left most of them untouched, and a reviewer reported them all.

The rewrite runs only once every Mockito declared in the build is 2.1 or
newer: `org.mockito.junit.MockitoJUnitRunner` does not exist in 1.x, so on a
build still on Mockito 1 it would break every test class it touched.
"""
import re
from pathlib import Path, PurePosixPath

from ..shared import scope_fence
from ..shared.dependency_graph import EXCLUDED_DIRS

_PATTERN = "java-8-to-11"
_OLD = "org.mockito.runners.MockitoJUnitRunner"
_NEW = "org.mockito.junit.MockitoJUnitRunner"
_OLD_RX = re.compile(r"\borg\.mockito\.runners\.MockitoJUnitRunner\b")


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def mockito_ready(workspace_dir: str) -> tuple[bool, str]:
    """Whether every Mockito the build declares is 2.1+ (the new runner's
    package exists). Returns (ready, reason)."""
    coords = scope_fence._resolved_coordinates(workspace_dir)
    mockito = {(rel, a): v for (rel, g, a), v in coords.items() if g == "org.mockito"
               and a in ("mockito-core", "mockito-all")}
    if not mockito:
        return False, "no Mockito version is declared in the build (managed elsewhere) — left as is"
    old = [f"`{rel}` {a}:{v}" for (rel, a), v in mockito.items()
           if a == "mockito-all" or _version_tuple(v) < (2, 1)]
    if old:
        return False, "the build still declares Mockito below 2.1: " + ", ".join(old[:5])
    return True, ""


def _dedupe_import(text: str) -> str:
    """A file that imported both runners now imports the new one twice; keep the first."""
    seen = False
    out = []
    for line in text.splitlines(keepends=True):
        if line.strip() == f"import {_NEW};":
            if seen:
                continue
            seen = True
        out.append(line)
    return "".join(out)


def rewrite_mockito_runner(workspace_dir: str) -> tuple[list[str], str]:
    """Rewrite the runner reference in every writable .java file. Returns
    (changed paths, reason when nothing was attempted)."""
    ready, reason = mockito_ready(workspace_dir)
    if not ready:
        return [], reason
    root = Path(workspace_dir)
    changed: list[str] = []
    for path in sorted(root.rglob("*.java")):
        rel = path.relative_to(root)
        if EXCLUDED_DIRS & set(rel.parts):
            continue
        rel_s = PurePosixPath(*rel.parts).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _OLD not in text:
            continue
        ok, _why = scope_fence.writable(_PATTERN, rel_s)
        if not ok:
            continue
        new = _dedupe_import(_OLD_RX.sub(_NEW, text))
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(rel_s)
    return changed, ""
