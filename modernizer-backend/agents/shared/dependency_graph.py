"""
Deterministic (non-LLM) dependency-graph extraction and migration-group
sequencing, run once right after a repository is unpacked to its workspace
directory — before any agent sees the code.

`build_dependency_graph(workspace_dir, pattern)` dispatches to a per-pattern
extractor that returns a plain dict of `{nodes, edges}`, then
`_topological_groups` (Kahn's algorithm) turns the edge list into ordered
"migration groups" — group 0 has no in-repo dependencies, group N depends
only on nodes in groups < N. `to_text` renders the whole thing as a
plain-text tree (one block per group, each item listing what it depends
on) embedded in a ```text block of the Technical Specification markdown,
which the frontend shows verbatim (see `BRDReview.tsx`'s `MarkdownWithDiagrams`).

This is intentionally simple, static analysis — a best-effort first pass
for sequencing the migration, not a full build-system dependency resolver.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TypedDict

#: Directories that are never repository source: VCS metadata, IDE state, and
#: build output for every toolchain the patterns generate into. Missing the
#: JS/TS outputs meant a generated frontend's `dist/` (~40 files from one
#: `npm run build`) dominated the change audit and the Changed Files view.
EXCLUDED_DIRS = {
    ".git", ".gradle", ".idea", ".vscode", "__pycache__",
    # JVM build output
    "target", "build", "bin", "obj",
    # JS/TS dependencies and build output
    "node_modules", "dist", "out", "coverage",
    ".next", ".nuxt", ".svelte-kit", ".output", ".turbo", ".parcel-cache", ".vite",
}


class DependencyGraph(TypedDict):
    nodes: list[str]
    edges: list[tuple[str, str]]  # (from_node, to_node) == from_node depends on to_node
    groups: list[list[str]]


def _iter_files(root: Path, suffixes: set[str]) -> list[Path]:
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if EXCLUDED_DIRS & set(path.relative_to(root).parts):
            continue
        if path.suffix.lower() in suffixes:
            out.append(path)
    return out


def _topological_groups(nodes: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    """Kahn's algorithm, batched into waves instead of a single ordering.

    edges are (dependant, dependency) pairs: dependant must be migrated
    after dependency. Cycles are broken by dumping any node that never
    reaches an in-degree of 0 into the final group.
    """
    depends_on: dict[str, set[str]] = {n: set() for n in nodes}
    for a, b in edges:
        if a in depends_on and b in depends_on and a != b:
            depends_on[a].add(b)

    remaining = set(nodes)
    groups: list[list[str]] = []
    while remaining:
        ready = sorted(n for n in remaining if not (depends_on[n] & remaining))
        if not ready:
            # Cycle (or self-referential mess) — dump the rest as one final group.
            groups.append(sorted(remaining))
            break
        groups.append(ready)
        remaining -= set(ready)
    return groups


# ---------------------------------------------------------------------------
# Java: pom.xml / build.gradle modules + import-statement graph
# ---------------------------------------------------------------------------

_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)(?:\.\*)?\s*;", re.MULTILINE)


def _java_graph(root: Path) -> DependencyGraph:
    java_files = _iter_files(root, {".java"})
    # node = file path relative to root; also track which package each file declares,
    # so intra-repo imports (import com.acme.foo.Bar) can be resolved back to a file.
    package_owner: dict[str, list[str]] = {}  # "com.acme.foo.Bar" -> [file paths declaring it]
    file_package: dict[str, str] = {}
    nodes: list[str] = []

    for f in java_files:
        rel = str(f.relative_to(root))
        nodes.append(rel)
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        pkg_match = _PACKAGE_RE.search(text)
        pkg = pkg_match.group(1) if pkg_match else ""
        file_package[rel] = pkg
        fq_class = f"{pkg}.{f.stem}" if pkg else f.stem
        package_owner.setdefault(fq_class, []).append(rel)

    edges: list[tuple[str, str]] = []
    for f in java_files:
        rel = str(f.relative_to(root))
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for imp in _IMPORT_RE.findall(text):
            for target_file in package_owner.get(imp, []):
                if target_file != rel:
                    edges.append((rel, target_file))

    return {"nodes": nodes, "edges": edges, "groups": _topological_groups(nodes, edges)}


# ---------------------------------------------------------------------------
# Solr: cores/collections + configSet references (solr.xml / core.properties)
# ---------------------------------------------------------------------------

def _solr_graph(root: Path) -> DependencyGraph:
    nodes: list[str] = []
    edges: list[tuple[str, str]] = []
    configset_of: dict[str, str] = {}

    for props in _iter_files(root, {".properties"}):
        if props.name != "core.properties":
            continue
        core_name = props.parent.name
        nodes.append(core_name)
        try:
            text = props.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        m = re.search(r"^\s*configSet\s*=\s*(\S+)", text, re.MULTILINE)
        if m:
            configset_of[core_name] = m.group(1)

    for solr_xml in _iter_files(root, {".xml"}):
        if solr_xml.name != "solr.xml":
            continue
        try:
            tree = ET.parse(solr_xml)
        except ET.ParseError:
            continue
        for core in tree.getroot().iter("core"):
            name = core.get("name")
            if name and name not in nodes:
                nodes.append(name)

    # A configSet shared by two cores is modelled as a node too, with both
    # cores "depending on" (i.e. must move together / after) that shared config.
    for core, configset in configset_of.items():
        cs_node = f"configSet:{configset}"
        if cs_node not in nodes:
            nodes.append(cs_node)
        edges.append((core, cs_node))

    if not nodes:
        # Fall back to one node per top-level conf directory found.
        for conf_dir in sorted({p.parent.name for p in _iter_files(root, {".xml"}) if p.stem in ("schema", "solrconfig")}):
            nodes.append(conf_dir)

    return {"nodes": nodes, "edges": edges, "groups": _topological_groups(nodes, edges)}


# ---------------------------------------------------------------------------
# Oracle: DDL/PLSQL object dependency graph (tables -> views -> packages)
# ---------------------------------------------------------------------------

_SQL_OBJECT_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(TABLE|VIEW|PACKAGE(?:\s+BODY)?|PROCEDURE|FUNCTION|TRIGGER|MATERIALIZED\s+VIEW)\s+"
    r"\"?([A-Za-z0-9_$#.]+)\"?",
    re.IGNORECASE,
)
_SQL_REF_RE = re.compile(r"\b(?:FROM|JOIN|REFERENCES|CALL)\s+\"?([A-Za-z0-9_$#.]+)\"?", re.IGNORECASE)


def _oracle_graph(root: Path) -> DependencyGraph:
    sql_files = _iter_files(root, {".sql", ".pks", ".pkb", ".ddl", ".plsql"})
    object_owner: dict[str, str] = {}  # object name (upper) -> defining file
    nodes: list[str] = []

    file_text: dict[Path, str] = {}
    for f in sql_files:
        try:
            file_text[f] = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            file_text[f] = ""

    for f, text in file_text.items():
        for _, name in _SQL_OBJECT_RE.findall(text):
            key = name.upper().split(".")[-1]
            object_owner[key] = str(f.relative_to(root))
            if str(f.relative_to(root)) not in nodes:
                nodes.append(str(f.relative_to(root)))

    edges: list[tuple[str, str]] = []
    for f, text in file_text.items():
        rel = str(f.relative_to(root))
        if rel not in nodes:
            nodes.append(rel)
        for ref in _SQL_REF_RE.findall(text):
            key = ref.upper().split(".")[-1]
            owner = object_owner.get(key)
            if owner and owner != rel:
                edges.append((rel, owner))

    return {"nodes": nodes, "edges": edges, "groups": _topological_groups(nodes, edges)}


# ---------------------------------------------------------------------------
# TIBCO EMS: destination (queue/topic) graph from config + producer/consumer refs
# ---------------------------------------------------------------------------

_EMS_DEST_RE = re.compile(r'\b(?:queue|topic)\s*[:=]\s*"?([\w./-]+)"?', re.IGNORECASE)


def _tibco_ems_graph(root: Path) -> DependencyGraph:
    candidate_files = _iter_files(
        root, {".xml", ".conf", ".config", ".properties", ".json", ".bwp", ".substvar"}
    )
    dest_files: dict[str, set[str]] = {}
    nodes: list[str] = []

    for f in candidate_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        dests = set(_EMS_DEST_RE.findall(text))
        if not dests:
            continue
        rel = str(f.relative_to(root))
        nodes.append(rel)
        for d in dests:
            dest_files.setdefault(d, set()).add(rel)

    edges: list[tuple[str, str]] = []
    # Files sharing a destination are grouped together by making every later
    # file in that group "depend on" the first file that referenced it —
    # i.e. they should migrate in the same wave.
    for dest, files in dest_files.items():
        dest_node = f"destination:{dest}"
        nodes.append(dest_node)
        for f in files:
            edges.append((f, dest_node))

    return {"nodes": nodes, "edges": edges, "groups": _topological_groups(nodes, edges)}


# ---------------------------------------------------------------------------
# JSP: page -> include/taglib dependency graph (which pages/fragments must
# migrate together vs. independently)
# ---------------------------------------------------------------------------

_JSP_STATIC_INCLUDE_RE = re.compile(r'<%@\s*include\s+file\s*=\s*"([^"]+)"\s*%>')
_JSP_DYNAMIC_INCLUDE_RE = re.compile(r'<jsp:include\s+page\s*=\s*"([^"]+)"')
_JSP_TAGLIB_RE = re.compile(r'<%@\s*taglib\s+[^%]*uri\s*=\s*"([^"]+)"[^%]*%>')


def _resolve_jsp_ref(current: Path, root: Path, ref: str) -> str | None:
    """Resolve a JSP include reference (which may be relative or webapp-root-relative)
    to a path relative to *root*, if the target file actually exists."""
    candidates = []
    if ref.startswith("/"):
        candidates.append(root / ref.lstrip("/"))
    else:
        candidates.append(current.parent / ref)
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and root in resolved.parents:
            return str(resolved.relative_to(root))
    return None


def _jsp_graph(root: Path) -> DependencyGraph:
    jsp_files = _iter_files(root, {".jsp", ".jspf", ".jspx", ".tag"})
    nodes = [str(f.relative_to(root)) for f in jsp_files]
    edges: list[tuple[str, str]] = []
    taglib_users: dict[str, set[str]] = {}

    for f in jsp_files:
        rel = str(f.relative_to(root))
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for ref in [*_JSP_STATIC_INCLUDE_RE.findall(text), *_JSP_DYNAMIC_INCLUDE_RE.findall(text)]:
            target = _resolve_jsp_ref(f, root, ref)
            if target and target != rel:
                edges.append((rel, target))

        for uri in _JSP_TAGLIB_RE.findall(text):
            taglib_users.setdefault(uri, set()).add(rel)

    # Pages sharing a custom taglib are modelled as depending on a shared
    # "taglib:<uri>" node, so they land in the same or a later migration group.
    for uri, users in taglib_users.items():
        if len(users) < 2:
            continue
        taglib_node = f"taglib:{uri}"
        nodes.append(taglib_node)
        for page in users:
            edges.append((page, taglib_node))

    return {"nodes": nodes, "edges": edges, "groups": _topological_groups(nodes, edges)}


_EXTRACTORS = {
    "java-8-to-25": _java_graph,
    "solr-4-to-9": _solr_graph,
    "oracle-19c-to-23ai": _oracle_graph,
    "tibco-ems-to-pubsub": _tibco_ems_graph,
    "jsp-to-react-bff": _jsp_graph,
}


def build_dependency_graph(workspace_dir: str, pattern: str) -> DependencyGraph:
    extractor = _EXTRACTORS.get(pattern, _java_graph)
    root = Path(workspace_dir).resolve()
    if not root.exists():
        return {"nodes": [], "edges": [], "groups": []}
    return extractor(root)


def to_text(graph: DependencyGraph, max_nodes_per_group: int = 25, max_deps_per_node: int = 5) -> str:
    """Render a dependency graph as a plain-text tree, one block per migration
    group (wave) in migration order, each item followed by the in-repo
    artefacts it depends on. Plain text rather than a diagram DSL, so it
    displays verbatim with no client-side diagram renderer to fail."""
    if not graph["nodes"]:
        return "No structural dependencies detected — treat as a single migration group."

    group_of = {n: gi for gi, group in enumerate(graph["groups"]) for n in group}
    deps_of: dict[str, list[str]] = {}
    for a, b in graph["edges"]:
        if a in group_of and b in group_of and b not in deps_of.setdefault(a, []):
            deps_of[a].append(b)

    lines: list[str] = []
    for gi, group in enumerate(graph["groups"]):
        lines.append(f"Group {gi + 1}  ({len(group)} item{'s' if len(group) != 1 else ''})")
        shown = group[:max_nodes_per_group]
        hidden = len(group) - len(shown)
        for ni, n in enumerate(shown):
            last = ni == len(shown) - 1 and not hidden
            lines.append(f"  {'└─' if last else '├─'} {n}")
            stem = "     " if last else "  │  "
            deps = deps_of.get(n, [])
            for d in deps[:max_deps_per_node]:
                lines.append(f"{stem}  → {d}  (Group {group_of[d] + 1})")
            if len(deps) > max_deps_per_node:
                lines.append(f"{stem}  → …and {len(deps) - max_deps_per_node} more")
        if hidden:
            lines.append(f"  └─ …and {hidden} more")
        lines.append("")
    return "\n".join(lines).rstrip()


def to_markdown_section(graph: DependencyGraph, pattern: str) -> str:
    """Render the full '## Dependency Graph & Migration Groups' section
    prepended to the Technical Specification before brd-ready fires."""
    lines = [
        "## Dependency Graph & Migration Groups",
        "",
        "_Computed deterministically by static analysis of the uploaded repository "
        "— not generated by the AI. Migration groups are ordered so that each group "
        "depends only on artefacts in earlier groups; `→` lists what an item depends on._",
        "",
        "```text",
        to_text(graph),
        "```",
        "",
    ]
    return "\n".join(lines)
