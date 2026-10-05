"""
Deterministic (no model) extraction of what a repository is built from.

Pass 1 of stack discovery. Three kinds of fact, each with the file it came from:

- **Languages** — source files counted per language by extension.
- **Manifests** — every build/dependency manifest parsed for its declared
  dependencies: Maven `pom.xml` (XML), Gradle build scripts, npm `package.json`,
  Bower `bower.json`, Python `requirements*.txt` / `pyproject.toml` / `Pipfile`,
  Go `go.mod`, .NET `*.csproj`, PHP `composer.json`, Ruby `Gemfile`.
- **Imports** — what the code actually uses. Python files are parsed with the
  `ast` module (a real syntax tree, so strings and comments never count). Java,
  JavaScript and TypeScript import declarations are read from their declaration
  syntax: `import x.y.Z;`, `import … from 'm'`, `require('m')`, and AMD
  `define([...])` / `require([...])` (RequireJS, common in Backbone apps).
  Comments are stripped first. HTML/JSP pages contribute their
  `<script src="…">` includes, and committed library files (`backbone-min.js`)
  are recorded as vendored.

Nothing here decides what a stack is; stack_detector maps these facts to
stacks, and the dependency mapper agent reviews and extends that mapping.
"""
import ast
import json
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from .dependency_graph import EXCLUDED_DIRS

#: extension -> language
LANGUAGES: dict[str, str] = {
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala", ".groovy": "Groovy",
    ".jsp": "JSP", ".jspx": "JSP", ".jspf": "JSP", ".tag": "JSP", ".tagx": "JSP",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript (JSX)",
    ".ts": "TypeScript", ".tsx": "TypeScript (TSX)", ".vue": "Vue", ".svelte": "Svelte",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS", ".less": "LESS",
    ".hbs": "Handlebars", ".handlebars": "Handlebars", ".mustache": "Mustache", ".ejs": "EJS",
    ".py": "Python", ".rb": "Ruby", ".php": "PHP", ".go": "Go", ".cs": "C#", ".vb": "VB.NET",
    ".c": "C", ".h": "C/C++ header", ".cpp": "C++", ".cc": "C++", ".rs": "Rust", ".swift": "Swift",
    ".sql": "SQL", ".pls": "PL/SQL", ".pks": "PL/SQL", ".pkb": "PL/SQL", ".plsql": "PL/SQL",
    ".sh": "Shell", ".bat": "Batch", ".cmd": "Batch", ".ps1": "PowerShell",
    ".xml": "XML", ".xsd": "XML", ".xsl": "XSLT", ".xslt": "XSLT", ".wsdl": "WSDL",
    ".properties": "Properties", ".yml": "YAML", ".yaml": "YAML", ".json": "JSON",
    ".gradle": "Gradle", ".cbl": "COBOL", ".cob": "COBOL", ".pl": "Perl", ".r": "R",
}

_PY_STDLIB = set(sys.stdlib_module_names)
_MAX_FILE_BYTES = 1_000_000
_MAX_FILES = 20_000
_SAMPLES = 3

_JAVA_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+?)(?:\.\*)?\s*;", re.MULTILINE)
_JS_IMPORT = re.compile(
    r"""(?:^|[;\s])import\s+(?:[\w*{}\s,$]+\s+from\s+)?['"]([^'"]+)['"]"""
    r"""|\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)"""
    r"""|\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)""",
    re.MULTILINE,
)
_AMD = re.compile(r"""\b(?:define|require|requirejs)\s*\(\s*(?:['"][\w./-]+['"]\s*,\s*)?\[([^\]]*)\]""")
_QUOTED = re.compile(r"""['"]([^'"]+)['"]""")
_SCRIPT_SRC = re.compile(r"""<script[^>]+src\s*=\s*['"]([^'"]+)['"]""", re.IGNORECASE)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"(?m)^\s*//.*$")
_LIB_FILE = re.compile(r"^([a-z][a-z0-9_.-]*?)(?:[-.]v?\d[\w.]*)?(?:[-.]min)?\.js$", re.IGNORECASE)

_GRADLE_DEP = re.compile(
    r"""\b(?:implementation|api|compile|compileOnly|runtimeOnly|runtime|providedCompile|providedRuntime|"""
    r"""testImplementation|testCompile|testRuntimeOnly|annotationProcessor|kapt)\s*\(?\s*['"]([^'":]+):([^'":]+)(?::([^'"@]+))?""")
_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*([=<>!~]=?\s*[^;#\s]+)?")
_GO_REQ = re.compile(r"^\s*(?:require\s+)?([\w.\-/]+\.[\w.\-/]+)\s+(v[\w.\-+]+)", re.MULTILINE)
_GEM = re.compile(r"""^\s*gem\s+['"]([^'"]+)['"](?:\s*,\s*['"]([^'"]+)['"])?""", re.MULTILINE)


def _files(root: Path):
    count = 0
    for path in sorted(root.rglob("*")):
        if count >= _MAX_FILES:
            return
        if not path.is_file():
            continue
        parts = set(path.relative_to(root).parts)
        if EXCLUDED_DIRS & parts or "node_modules" in parts or "bower_components" in parts:
            continue
        count += 1
        yield path


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------

def _pom(text: str) -> list[dict]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    deps = []
    # The parent POM is where a Spring Boot version usually comes from.
    for el in root:
        if _local(el.tag) == "parent":
            fields = {_local(c.tag): (c.text or "").strip() for c in el}
            if fields.get("groupId") and fields.get("artifactId"):
                deps.append({"name": f"{fields['groupId']}:{fields['artifactId']}",
                             "version": fields.get("version", ""), "scope": "parent"})
    for el in root.iter():
        if _local(el.tag) != "dependency":
            continue
        fields = {_local(c.tag): (c.text or "").strip() for c in el}
        if fields.get("groupId") and fields.get("artifactId"):
            deps.append({"name": f"{fields['groupId']}:{fields['artifactId']}",
                         "version": fields.get("version", ""), "scope": fields.get("scope", "")})
    return deps


_KEY_PROPERTY = re.compile(r"(?:^|\.)(?:java\.version|release|source|target)$|version$|encoding$", re.I)


def pom_properties(text: str) -> dict[str, str]:
    """The POM's version-like properties (java.version, maven.compiler.*, *.version)."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    out = {}
    for el in root:
        if _local(el.tag) == "properties":
            for prop in el:
                name, value = _local(prop.tag), (prop.text or "").strip()
                if value and _KEY_PROPERTY.search(name):
                    out[name] = value
    return dict(list(out.items())[:20])


def _package_json(text: str, keys=("dependencies", "devDependencies", "peerDependencies")) -> list[dict]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    deps = []
    for key in keys:
        for name, version in (data.get(key) or {}).items() if isinstance(data, dict) else []:
            deps.append({"name": name, "version": str(version),
                         "scope": "dev" if key == "devDependencies" else ""})
    return deps


def _requirements(text: str) -> list[dict]:
    deps = []
    for line in text.splitlines():
        if line.strip().startswith(("#", "-")):
            continue
        m = _REQ_LINE.match(line)
        if m:
            deps.append({"name": m.group(1).lower(), "version": (m.group(2) or "").strip(), "scope": ""})
    return deps


def _pyproject(text: str) -> list[dict]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    names = list((data.get("project") or {}).get("dependencies") or [])
    poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
    deps = _requirements("\n".join(names))
    deps += [{"name": n.lower(), "version": str(v) if isinstance(v, str) else "", "scope": ""}
             for n, v in poetry.items() if n.lower() != "python"]
    return deps


def _csproj(text: str) -> list[dict]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    return [{"name": el.get("Include", ""), "version": el.get("Version", ""), "scope": ""}
            for el in root.iter() if _local(el.tag) == "PackageReference" and el.get("Include")]


def _manifest(path: Path, text: str) -> tuple[str, list[dict]] | None:
    name = path.name.lower()
    if name == "pom.xml":
        return "maven", _pom(text)
    if name.endswith((".gradle", ".gradle.kts")):
        return "gradle", [{"name": f"{g}:{a}", "version": v or "", "scope": ""}
                          for g, a, v in _GRADLE_DEP.findall(text)]
    if name == "package.json":
        return "npm", _package_json(text)
    if name == "bower.json":
        return "bower", _package_json(text, ("dependencies", "devDependencies"))
    if name == "composer.json":
        return "composer", _package_json(text, ("require", "require-dev"))
    if re.fullmatch(r"requirements[\w.-]*\.txt", name):
        return "pip", _requirements(text)
    if name == "pyproject.toml":
        return "pip", _pyproject(text)
    if name == "pipfile":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return "pip", []
        return "pip", [{"name": n.lower(), "version": str(v) if isinstance(v, str) else "", "scope": ""}
                       for section in ("packages", "dev-packages") for n, v in (data.get(section) or {}).items()]
    if name == "go.mod":
        return "go", [{"name": n, "version": v, "scope": ""} for n, v in _GO_REQ.findall(text)]
    if name.endswith(".csproj"):
        return "nuget", _csproj(text)
    if name == "gemfile":
        return "bundler", [{"name": n, "version": v or "", "scope": ""} for n, v in _GEM.findall(text)]
    return None


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

def _python_imports(text: str) -> set[str]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


def _java_imports(text: str) -> set[str]:
    text = _BLOCK_COMMENT.sub(" ", text)
    out = set()
    for name in _JAVA_IMPORT.findall(text):
        parts = name.split(".")
        # Package, not class: drop trailing capitalised segments.
        while len(parts) > 1 and parts[-1][:1].isupper():
            parts.pop()
        out.add(".".join(parts[:3]))
    return out


def _js_module(spec: str) -> str | None:
    spec = spec.strip()
    if not spec or spec.startswith((".", "/")) or "://" in spec:
        return None
    if spec.startswith("@"):
        return "/".join(spec.split("/")[:2])
    return spec.split("/")[0]


def _js_imports(text: str) -> set[str]:
    text = _LINE_COMMENT.sub(" ", _BLOCK_COMMENT.sub(" ", text))
    out = set()
    for groups in _JS_IMPORT.findall(text):
        mod = _js_module(next(g for g in groups if g) if any(groups) else "")
        if mod:
            out.add(mod)
    for deps in _AMD.findall(text):
        for spec in _QUOTED.findall(deps):
            mod = _js_module(spec)
            if mod:
                out.add(mod)
    return out


def library_name(file_name: str) -> str | None:
    """`backbone-min.js` / `jquery-1.11.3.min.js` / `underscore.js` -> library name."""
    m = _LIB_FILE.match(file_name)
    return m.group(1).lower() if m else None


# ---------------------------------------------------------------------------

def fingerprint(workspace_dir: str) -> dict:
    """{languages: {lang: {"files": n, "samples": [...]}},
        manifests: [{path, kind, dependencies: [{name, version, scope}]}],
        imports: {ecosystem: {module: {"files": n, "samples": [...]}}},
        scripts: {library: [page paths]}, vendored: {library: [file paths]}}"""
    root = Path(workspace_dir).resolve()
    languages: dict[str, dict] = defaultdict(lambda: {"files": 0, "samples": []})
    manifests: list[dict] = []
    imports: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: {"files": 0, "samples": []}))
    scripts: dict[str, list[str]] = defaultdict(list)
    vendored: dict[str, list[str]] = defaultdict(list)
    if not root.exists():
        return {"languages": {}, "manifests": [], "imports": {}, "scripts": {}, "vendored": {}}

    def note(bucket: dict, rel: str):
        bucket["files"] += 1
        if len(bucket["samples"]) < _SAMPLES:
            bucket["samples"].append(rel)

    for path in _files(root):
        rel = path.relative_to(root).as_posix()
        name, suffix = path.name.lower(), path.suffix.lower()
        lang = "Gradle" if name.endswith(".gradle.kts") else LANGUAGES.get(suffix)
        if lang:
            note(languages[lang], rel)

        reads_text = suffix in (".java", ".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue",
                                ".html", ".htm", ".jsp", ".jspf", ".jspx", ".tag", ".hbs", ".ftl", ".vm")
        is_manifest = name in ("pom.xml", "package.json", "bower.json", "composer.json", "pyproject.toml",
                               "pipfile", "go.mod", "gemfile") or name.endswith(
            (".gradle", ".gradle.kts", ".csproj")) or re.fullmatch(r"requirements[\w.-]*\.txt", name)
        if not (reads_text or is_manifest):
            continue
        text = _read(path)
        if not text:
            continue

        if is_manifest:
            parsed = _manifest(path, text)
            if parsed:
                manifests.append({"path": rel, "kind": parsed[0], "dependencies": parsed[1],
                                  "properties": pom_properties(text) if parsed[0] == "maven" else {}})
            continue

        if suffix == ".java":
            for mod in _java_imports(text):
                if not mod.startswith("java."):          # the JDK itself is not a dependency
                    note(imports["java"][mod], rel)
        elif suffix == ".py":
            for mod in _python_imports(text) - _PY_STDLIB:
                note(imports["python"][mod], rel)
        elif suffix in (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue"):
            lib = library_name(path.name) if suffix == ".js" else None
            # A committed copy of a library (lib/backbone-min.js) is vendored, not app code.
            if lib and re.search(r"(?:^|/)(?:lib|libs|vendor|vendors|third[-_]?party|external)/", rel, re.I):
                vendored[lib].append(rel)
                continue
            for mod in _js_imports(text):
                note(imports["javascript"][mod], rel)
        if suffix in (".html", ".htm", ".jsp", ".jspf", ".jspx", ".tag", ".hbs", ".ftl", ".vm", ".vue"):
            for src in _SCRIPT_SRC.findall(text):
                # Thymeleaf link expressions: th:src="@{/vendor/jquery/jquery-3.6.0.min.js}"
                src = re.sub(r"^\s*@\{\s*|\s*\}\s*$", "", src)
                lib = library_name(src.split("?")[0].split("(")[0].rsplit("/", 1)[-1])
                if lib and rel not in scripts[lib]:
                    scripts[lib].append(rel)

    return {
        "languages": dict(sorted(languages.items(), key=lambda kv: -kv[1]["files"])),
        "manifests": manifests,
        "imports": {eco: dict(sorted(mods.items(), key=lambda kv: -kv[1]["files"]))
                    for eco, mods in imports.items()},
        "scripts": dict(scripts),
        "vendored": dict(vendored),
    }


def to_markdown(fp: dict, max_deps: int | None = 40, max_imports: int | None = 25) -> str:
    """The fingerprint as document sections: languages, manifests and their
    declared dependencies, the libraries the code imports, and script includes."""
    lines = ["## Repository Fingerprint", "",
             "_Extracted deterministically from the files — not generated by the AI._", ""]
    if fp.get("languages"):
        lines += ["### Languages", "", "| Language | Files | Examples |", "|---|---|---|"]
        for lang, info in fp["languages"].items():
            lines.append(f"| {lang} | {info['files']} | " + ", ".join(f"`{s}`" for s in info["samples"]) + " |")
        lines.append("")
    if fp.get("manifests"):
        lines += ["### Build & Dependency Manifests", ""]
        for m in fp["manifests"]:
            deps = m["dependencies"]
            lines.append(f"**`{m['path']}`** ({m['kind']}, {len(deps)} declared dependenc"
                         f"{'y' if len(deps) == 1 else 'ies'})")
            if m.get("properties"):
                lines.append("Key properties: " + ", ".join(f"`{k}` = {v}" for k, v in m["properties"].items()))
            if deps:
                lines += ["", "| Dependency | Version | Scope |", "|---|---|---|"]
                for d in deps[:max_deps]:
                    lines.append(f"| `{d['name']}` | {d['version'] or '—'} | {d['scope'] or '—'} |")
                if max_deps is not None and len(deps) > max_deps:
                    lines.append(f"| …and {len(deps) - max_deps} more | | |")
            lines.append("")
    for eco, mods in (fp.get("imports") or {}).items():
        if not mods:
            continue
        lines += [f"### Libraries Imported by the Code ({eco})", "",
                  "| Package / module | Files | Examples |", "|---|---|---|"]
        for mod, info in list(mods.items())[:max_imports]:
            lines.append(f"| `{mod}` | {info['files']} | " + ", ".join(f"`{s}`" for s in info["samples"]) + " |")
        if max_imports is not None and len(mods) > max_imports:
            lines.append(f"| …and {len(mods) - max_imports} more | | |")
        lines.append("")
    if fp.get("scripts") or fp.get("vendored"):
        lines += ["### Script Includes & Vendored Libraries", "", "| Library | Where |", "|---|---|"]
        for lib, pages in sorted((fp.get("scripts") or {}).items()):
            lines.append(f"| `{lib}` | loaded by " + ", ".join(f"`{p}`" for p in pages[:3])
                         + (f" (+{len(pages) - 3})" if len(pages) > 3 else "") + " |")
        for lib, files in sorted((fp.get("vendored") or {}).items()):
            lines.append(f"| `{lib}` | committed as " + ", ".join(f"`{f}`" for f in files[:3]) + " |")
        lines.append("")
    return "\n".join(lines).rstrip()


def to_prompt(fp: dict) -> str:
    """Compact form for the dependency mapper's instruction."""
    out = []
    langs = ", ".join(f"{lang} ({info['files']})" for lang, info in fp.get("languages", {}).items())
    out.append(f"Languages (files): {langs or 'none'}")
    for m in fp.get("manifests", []):
        names = ", ".join(d["name"] + (f"@{d['version']}" if d["version"] else "") for d in m["dependencies"][:60])
        props = ", ".join(f"{k}={v}" for k, v in (m.get("properties") or {}).items())
        out.append(f"{m['path']} ({m['kind']}): {names or 'no dependencies declared'}"
                   + (f"; properties: {props}" if props else ""))
    for eco, mods in (fp.get("imports") or {}).items():
        out.append(f"Imports ({eco}): " + ", ".join(f"{m} ({i['files']})" for m, i in list(mods.items())[:40]))
    if fp.get("scripts"):
        out.append("Script includes: " + ", ".join(f"{lib} ({pages[0]})" for lib, pages in fp["scripts"].items()))
    if fp.get("vendored"):
        out.append("Vendored libraries: " + ", ".join(f"{lib} ({files[0]})" for lib, files in fp["vendored"].items()))
    return "\n".join(out)
