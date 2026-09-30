"""
Splits a repository into bounded units for chunked reverse engineering.

One reverse-engineering agent run over a whole monolith resends every file it
has read on every model call (ADK includes the current turn's tool calls and
responses in each request), so request size grows with each read and the total
tokens sent grow quadratically -- measured at ~529k characters on the 31st call
of a 30-file run. That exhausts tokens-per-minute quotas (429) and eventually
the context window, whatever the retry policy.

So the repository is analysed one unit at a time, each unit in a fresh agent
run: a unit is a Maven/Gradle module, and a module larger than `max_files` is
split further along its directory tree. Every file belongs to exactly one unit,
so nothing is left out and nothing is analysed twice. Deterministic: the same
repository always yields the same units, in path order.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .dependency_graph import EXCLUDED_DIRS

BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts")


@dataclass
class Unit:
    """One bounded slice of the repository, analysed by its own agent run."""
    id: str
    module: str                 # module directory ("" for the repository root)
    #: What the unit covers: whole directories (ending in "/") or single files.
    #: For an unsplit module this is just the module directory.
    scope: list[str] = field(default_factory=list)
    files: int = 0
    part: int = 0               # 1-based part number when a module was split
    parts: int = 0

    @property
    def label(self) -> str:
        name = self.module or "(repository root)"
        return f"{name} (part {self.part}/{self.parts})" if self.parts > 1 else name

    def describe(self) -> str:
        """The scope, as the unit's agent is given it."""
        lines = [f"Unit {self.id}: {self.label} — {self.files} file(s)."]
        if self.parts > 1 or self.scope != [self._module_dir()]:
            lines.append("Covers ONLY these paths (a directory ends in '/'):")
            lines += [f"- `{s}`" for s in self.scope]
        else:
            lines.append(f"Covers everything under `{self._module_dir()}` that is not inside a nested module "
                         "(nested modules are separate units).")
        return "\n".join(lines)

    def _module_dir(self) -> str:
        return f"{self.module}/" if self.module else "./"


def _relevant_files(root: Path) -> list[str]:
    out = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if EXCLUDED_DIRS & set(rel.parts):
            continue
        out.append(rel.as_posix())
    return sorted(out)


def _owner(rel: str, modules: list[str]) -> str:
    """The deepest module directory containing *rel* ("" = repository root)."""
    best = ""
    for module in modules:
        if module and (rel.startswith(module + "/")) and len(module) > len(best):
            best = module
    return best


def _split(files: list[str], prefix: str, max_files: int) -> list[tuple[list[str], int]]:
    """Scopes (paths) and file counts covering *files* under *prefix*, each at
    most *max_files* unless a single directory level cannot be divided further."""
    if len(files) <= max_files:
        return [([prefix or "./"], len(files))]
    direct: list[str] = []
    children: dict[str, list[str]] = defaultdict(list)
    for rel in files:
        rest = rel[len(prefix):]
        if "/" in rest:
            children[prefix + rest.split("/", 1)[0] + "/"].append(rel)
        else:
            direct.append(rel)

    pieces: list[tuple[list[str], int]] = []
    for child in sorted(children):
        pieces += _split(children[child], child, max_files)
    # Files sitting directly in a directory: listed individually, in bounded batches.
    for i in range(0, len(direct), max_files):
        batch = direct[i:i + max_files]
        pieces.append((batch, len(batch)))

    # Pack neighbouring small pieces together, so a module with many small
    # packages becomes a handful of units rather than one per package.
    packed: list[tuple[list[str], int]] = []
    for scope, count in pieces:
        if packed and packed[-1][1] + count <= max_files:
            packed[-1] = (packed[-1][0] + scope, packed[-1][1] + count)
        else:
            packed.append((list(scope), count))
    return packed


def plan_units(workspace_dir: str, max_files: int) -> list[Unit]:
    """Every unit of the repository, in path order."""
    root = Path(workspace_dir)
    files = _relevant_files(root)
    modules = sorted({
        str(PurePosixPath(rel).parent) if "/" in rel else ""
        for rel in files if PurePosixPath(rel).name in BUILD_FILES
    } | {""})
    modules = [m if m != "." else "" for m in modules]

    owned: dict[str, list[str]] = defaultdict(list)
    for rel in files:
        owned[_owner(rel, modules)].append(rel)

    units: list[Unit] = []
    for module in sorted(owned):
        prefix = f"{module}/" if module else ""
        # A nested module's files are not in `owned[module]`, so a split never
        # reaches into it; an unsplit module's scope is its directory, which the
        # description qualifies ("not inside a nested module").
        pieces = _split(owned[module], prefix, max(1, max_files))
        for part, (scope, count) in enumerate(pieces, 1):
            units.append(Unit(
                id=str(len(units) + 1), module=module, scope=scope, files=count,
                part=part, parts=len(pieces),
            ))
    return units


def unit_of(units: list[Unit], rel: str) -> Unit | None:
    """The unit a file belongs to — the inverse of plan_units, for tests and checks."""
    modules = sorted({u.module for u in units})
    owner = _owner(rel, modules)
    for unit in units:
        if unit.module != owner:
            continue
        for s in unit.scope:
            if s in ("./", f"{owner}/" if owner else "./") and unit.parts == 1:
                return unit
            if (s.endswith("/") and rel.startswith(s)) or s == rel:
                return unit
    return None
