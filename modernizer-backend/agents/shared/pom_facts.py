"""
Maven POM facts shared by the deterministic migration inventories.

Every in-repo POM is parsed namespace-agnostically (the default xmlns varies by
model version) and `${property}` references are resolved through the POM's
in-repo parent chain, which is where a multi-module monorepo keeps its versions.
Kept in one place so every pattern's inventory reads a POM the same way.
"""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from . import scope_fence


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child(el, name):
    return next((c for c in el if local(c.tag) == name), None)


def text(el, name) -> str:
    c = child(el, name) if el is not None else None
    return (c.text or "").strip() if c is not None and c.text else ""


def version_key(v: str) -> tuple:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:4]) if nums else ()


def below(version: str, floor: str) -> bool | None:
    """True/False, or None when the version is unknown or unresolved."""
    if not version or "${" in version:
        return None
    a, b = version_key(version), version_key(floor)
    return a < b if a else None


@dataclass
class Pom:
    path: str
    artifact: str
    group: str
    packaging: str
    parent: str
    final_name: str
    properties: dict = field(default_factory=dict)
    plugins: list = field(default_factory=list)       # (group, artifact, version, block text)
    dependencies: list = field(default_factory=list)  # (group, artifact, version, scope, managed)
    levels: list = field(default_factory=list)        # (setting, level)
    raw: str = ""


def parse_pom(root: Path, rel: str) -> Pom | None:
    path = root / rel
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        el = ET.fromstring(raw)
    except Exception:
        return None
    parent = child(el, "parent")
    build = child(el, "build")
    pom = Pom(
        path=rel, artifact=text(el, "artifactId"),
        group=text(el, "groupId") or text(parent, "groupId"),
        packaging=text(el, "packaging") or "jar", parent=text(parent, "artifactId"),
        final_name=text(build, "finalName"), raw=raw,
    )
    props = child(el, "properties")
    if props is not None:
        pom.properties = {local(p.tag): (p.text or "").strip() for p in props}
    for node in el.iter():
        tag = local(node.tag)
        if tag == "plugin":
            pom.plugins.append((text(node, "groupId") or "org.apache.maven.plugins", text(node, "artifactId"),
                                text(node, "version"), ET.tostring(node, encoding="unicode")))
    for section, managed in (("dependencies", False), ("dependencyManagement", True)):
        container = child(el, section)
        if container is None:
            continue
        deps = child(container, "dependencies") if managed else container
        for d in (deps if deps is not None else []):
            if local(d.tag) == "dependency":
                pom.dependencies.append((text(d, "groupId"), text(d, "artifactId"), text(d, "version"),
                                         text(d, "scope") or ("" if managed else "compile"), managed))
    pom.levels = scope_fence.declared_java_levels(rel, raw)
    return pom


def resolver(poms: dict[str, Pom]):
    """Resolve `${property}` through a POM and its in-repo parents."""
    by_artifact = {p.artifact: p for p in poms.values()}

    def chain(pom: Pom):
        seen = set()
        while pom and pom.artifact not in seen:
            seen.add(pom.artifact)
            yield pom
            pom = by_artifact.get(pom.parent)

    def resolve(pom: Pom, value: str, depth: int = 0) -> str:
        if not value or "${" not in value or depth > 5:
            return value
        def repl(m):
            key = m.group(1)
            if key in ("project.version", "version"):
                return m.group(0)
            for p in chain(pom):
                if key in p.properties:
                    return p.properties[key]
            return m.group(0)
        return resolve(pom, re.sub(r"\$\{([^}]+)\}", repl, value), depth + 1)

    def managed_version(pom: Pom, group: str, artifact: str) -> str:
        for p in chain(pom):
            for g, a, v, _, managed in p.dependencies:
                if managed and a == artifact and (not group or g == group) and v:
                    return resolve(p, v)
        return ""

    return resolve, managed_version
