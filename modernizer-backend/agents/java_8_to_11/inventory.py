"""
Deterministic Java 11 inventory: the java-8-to-11 analysis step without a model.

The reverse-engineering agents read code through an agent loop that resends
everything read so far on every call — measured at 5.7x to 21x the size of the
source — which on a large monorepo exhausts the tokens-per-minute quota (429).
For a JDK-only upgrade the planner needs facts, not a narrative, and those
facts are mechanical: what every POM declares, where every API removed from the
JDK is used, which files are frozen, what the endpoints and tests are. This
module derives them by reading every file once, in plain Python, and renders
them in the same four-section format the agents produced, so the review
screen, the planner and the code steps are unchanged.

What it does not do: explain business intent, or judge whether a match is real
use or a comment. The document says so, and the planner and modifier (which
read the files they change) make those calls.
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..shared import scope_fence
from ..shared.pom_facts import below as _below, parse_pom as _parse_pom, resolver as _resolver
from ..shared.dependency_graph import EXCLUDED_DIRS
from ..shared.evidence import sample as _sample

PATTERN = "java-8-to-11"
_TEXT_SUFFIXES = {".java", ".jsp", ".jspf", ".jspx", ".tag", ".tagx", ".xml", ".properties", ".gradle", ".kts"}
_JSP = {".jsp", ".jspf", ".jspx", ".tag", ".tagx"}
_MAX_FILE_BYTES = 5_000_000


# ---------------------------------------------------------------------------
# What to look for
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Category:
    name: str
    regex: re.Pattern
    #: True: the code does not compile or run on Java 11 until changed (a manifest candidate).
    #: False: a behavioural risk to review; no change is required by Java 11 itself.
    change: bool
    fix: str


def _c(name, regex, change, fix, flags=0):
    return Category(name, re.compile(regex, flags), change, fix)


CATEGORIES: list[Category] = [
    _c("JAXB (javax.xml.bind)", r"\bjavax\.xml\.bind\b", True,
       "add javax.xml.bind:jaxb-api:2.3.1 (provided in a WildFly WAR/EAR)"),
    _c("JAX-WS / JWS / SAAJ", r"\bjavax\.(?:xml\.ws|jws|xml\.soap)\b", True,
       "add javax.xml.ws:jaxws-api:2.3.1 / javax.xml.soap-api (provided)"),
    _c("JAF (javax.activation)", r"\bjavax\.activation\b", True,
       "add javax.activation:javax.activation-api:1.2.0 (provided)"),
    _c("Common Annotations", r"\bjavax\.annotation\.(?:PostConstruct|PreDestroy|Resources?|Generated)\b", True,
       "add javax.annotation:javax.annotation-api:1.3.2 (provided)"),
    _c("JTA (javax.transaction)", r"\bjavax\.transaction\.(?!xa\b)[A-Za-z]", True,
       "add javax.transaction:javax.transaction-api:1.3 (provided)"),
    _c("CORBA / RMI-IIOP", r"\borg\.omg\.[A-Za-z]|\bjavax\.rmi\b|\bjavax\.activity\b", True,
       "no drop-in replacement — human decision"),
    _c("sun.misc BASE64 encoder/decoder", r"\bsun\.misc\.BASE64(?:En|De)coder\b", True,
       "java.util.Base64 (MIME variant keeps line wrapping)"),
    _c("JDK-internal API", r"\bsun\.reflect\.|\bsun\.misc\.Cleaner\b|\bsun\.security\.|\bsun\.net\.www\b|\bcom\.sun\.image\.codec\b", True,
       "public API (StackWalker, java.lang.ref.Cleaner, ...)"),
    _c("method removed in Java 11",
       r"\.runFinalizersOnExit\s*\(|\bcheckAwtEventQueueAccess\b|\bcheckTopLevelWindow\b|\bcheckSystemClipboardAccess\b|\bcheckMemberAccess\b|\bjavax\.security\.auth\.Policy\b", True,
       "rewrite on the replacement API"),
    _c("JavaFX (not in JDK 11)", r"\bjavafx\.", True, "OpenJFX dependency — human decision"),
    _c("system class loader cast to URLClassLoader", r"\(\s*URLClassLoader\s*\)", False,
       "ClassCastException on Java 9+ if the cast target is the system loader — check each"),
    _c("java.version parsing", r"getProperty\s*\(\s*\"java\.(?:specification\.)?version\"", False,
       "'1.x' assumptions break on '11' — Runtime.version()"),
    _c("reflective access (setAccessible)", r"\.setAccessible\s*\(\s*true\s*\)", False,
       "warns on JDK 11 when the target is a JDK class; check targets"),
    _c("locale-sensitive formatting (CLDR default since Java 9)",
       r"\bnew\s+(?:[\w$]+\.)*SimpleDateFormat\s*\(|\b(?:DateFormat|NumberFormat)\.get\w*Instance\s*\(", False,
       "output can change; -Djava.locale.providers=COMPAT,CLDR is a JVM (ops) option"),
]
_ANY_CATEGORY = re.compile("|".join(f"(?:{c.regex.pattern})" for c in CATEGORIES))

ENDPOINTS = [
    ("Servlet", re.compile(r"@(?:[\w$]+\.)*WebServlet\s*\(([^)]*)\)")),
    ("JAX-RS", re.compile(r"@(?:[\w$]+\.)*Path\s*\(\s*\"([^\"]*)\"")),
    ("SOAP web service", re.compile(r"@(?:[\w$]+\.)*WebService\b(?:\s*\(([^)]*)\))?")),
    ("EJB", re.compile(r"@(?:[\w$]+\.)*(Stateless|Stateful|Singleton)\b")),
    ("Message-driven bean", re.compile(r"@(?:[\w$]+\.)*MessageDriven\b(?:\s*\(([^)]*)\))?")),
    ("Scheduled", re.compile(r"@(?:[\w$]+\.)*Schedules?\s*\(([^)]*)\)")),
    ("Spring MVC", re.compile(r"@(?:[\w$]+\.)*(?:RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping)\s*\(([^)]*)\)")),
    ("Servlet filter/listener", re.compile(r"@(?:[\w$]+\.)*(WebFilter|WebListener)\b")),
]
_URL_PATTERN = re.compile(r"<url-pattern>\s*([^<]+?)\s*</url-pattern>")

TEST_FRAMEWORKS = [
    ("JUnit 3", re.compile(r"\bjunit\.framework\.TestCase\b")),
    ("JUnit 4", re.compile(r"\borg\.junit\.(?:Test|runner)\b")),
    ("JUnit 5 (Jupiter)", re.compile(r"\borg\.junit\.jupiter\b")),
    ("TestNG", re.compile(r"\borg\.testng\b")),
    ("Mockito", re.compile(r"\borg\.mockito\b")),
    ("PowerMock", re.compile(r"\borg\.powermock\b")),
    ("Arquillian", re.compile(r"\borg\.jboss\.arquillian\b")),
]

# (groupId regex or None, artifactId, first Java-11-capable version, note)
PLUGIN_FLOORS = [
    (None, "maven-compiler-plugin", "3.8.0", "older releases mishandle release 11 → 3.8.1+"),
    (None, "maven-surefire-plugin", "2.22.0", "cannot fork reliably on JDK 9+ → 2.22.2"),
    (None, "maven-failsafe-plugin", "2.22.0", "cannot fork reliably on JDK 9+ → 2.22.2"),
    (None, "maven-war-plugin", "3.2.2", "2.x fails on JDK 9+ → 3.4.0 (version only)"),
    (None, "maven-javadoc-plugin", "3.0.1", "JDK 9+ javadoc changes"),
    (None, "maven-shade-plugin", "3.2.0", "old ASM"),
    (None, "jacoco-maven-plugin", "0.8.2", "cannot read Java 11 class files → 0.8.8+"),
    (r"^org\.codehaus\.mojo$", "aspectj-maven-plugin", "1.14.0", "no Java 11 compliance level before 1.14.0"),
    (None, "jaxb2-maven-plugin", "2.5.0", "relies on JDK xjc removed in 11"),
]
PLUGIN_PRESENT = [
    (None, "findbugs-maven-plugin", "FindBugs cannot read Java 9+ class files → spotbugs-maven-plugin"),
    (r"^org\.codehaus\.mojo$", "jaxws-maven-plugin", "uses JDK wsimport removed in 11 → com.sun.xml.ws:jaxws-maven-plugin 2.3.x"),
    (None, "animal-sniffer-maven-plugin", "a java18 signature contradicts a release-11 build"),
]
LIBRARY_FLOORS = [
    (r"^org\.springframework$", r"^spring-", "5.1.0", "Spring 3/4 cannot run on Java 11 → 5.3.x (still javax)"),
    (r"^org\.hibernate$", r"^hibernate-core$", "5.3.0", "→ 5.4/5.6 (javax), unless WildFly provides it"),
    (r"^org\.ow2\.asm$|^asm$", r"^asm", "7.0", "cannot read Java 11 class files"),
    (r"^cglib$", r"^cglib", "3.3.0", "bundles an old ASM"),
    (r"^org\.aspectj$", r"^aspectj", "1.9.2", "no Java 11 support before 1.9.2"),
    (r"^org\.projectlombok$", r"^lombok$", "1.18.4", "no Java 11 support before 1.18.4"),
    (r"^org\.mockito$", r"^mockito-core$", "2.23.0", "Mockito 1.x cannot mock on Java 11 → 2.28.2"),
    (r"^org\.powermock$", r"^powermock", "2.0.0", "PowerMock 1.x needs Mockito 1 → 2.0.9"),
    (r"^org\.apache\.commons$", r"^commons-lang3$", "3.8", "misreads Java 9+ version strings"),
    (r"^org\.javassist$|^javassist$", r"^javassist$", "3.23.0", "old releases fail on Java 9+ class files"),
]
LIBRARY_PRESENT = [
    (r"^org\.mockito$", r"^mockito-all$", "Mockito 1.x all-in-one → mockito-core 2.28.2"),
]


# ---------------------------------------------------------------------------
# POM facts
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------

@dataclass
class Inventory:
    files_total: int = 0
    files_scanned: int = 0
    lines_scanned: int = 0
    skipped_large: list = field(default_factory=list)
    modules: list = field(default_factory=list)          # Pom
    build_findings: list = field(default_factory=list)   # (pom path, item, current, finding)
    dependency_rows: list = field(default_factory=list)  # (pom, g:a, version, scope, status)
    blockers: dict = field(default_factory=lambda: defaultdict(list))   # category -> [(file, [lines], sample)]
    jsp_risks: dict = field(default_factory=lambda: defaultdict(list))
    endpoints: list = field(default_factory=list)        # (type, value, file:line)
    tests: dict = field(default_factory=lambda: defaultdict(set))  # framework -> {files}
    test_files: dict = field(default_factory=lambda: defaultdict(int))  # module -> count
    frozen: dict = field(default_factory=lambda: defaultdict(int))  # (kind, top dir) -> count
    wildfly: list = field(default_factory=list)          # evidence strings
    module_of: dict = field(default_factory=dict)


def frozen_unit(rel: str) -> str:
    """The narrowest path that covers a frozen file and nothing that may change:
    the frozen directory (`pwm-web/src/main/webapp/`, `.../META-INF/`) when the
    file is inside one, else the file itself. A coarser key — the module folder —
    would declare the module's Java sources unchanged too."""
    fence = scope_fence.fence_for(PATTERN)
    for root in fence.frozen_roots:
        at = f"/{rel}".find(f"/{root}")
        if at >= 0:
            return rel[:at] + root if at else root
    parts = rel.split("/")
    for i, part in enumerate(parts[:-1]):
        if part in fence.frozen_segments:
            return "/".join(parts[: i + 1]) + "/"
    return rel


def _module_of(rel: str, modules: list[str]) -> str:
    best = ""
    for m in modules:
        if m and rel.startswith(m + "/") and len(m) > len(best):
            best = m
    return best or "."


def build(workspace_dir: str) -> Inventory:
    root = Path(workspace_dir)
    inv = Inventory()
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if EXCLUDED_DIRS & set(rel.parts):
            continue
        files.append(rel.as_posix())
    files.sort()
    inv.files_total = len(files)

    # -- build files ---------------------------------------------------------
    poms = {rel: p for rel in files if PurePosixPath(rel).name == "pom.xml" and (p := _parse_pom(root, rel))}
    inv.modules = list(poms.values())
    module_dirs = [str(PurePosixPath(p).parent) if "/" in p else "" for p in poms]
    resolve, managed_version = _resolver(poms)
    for pom in poms.values():
        for g, a, v, block in pom.plugins:
            version = resolve(pom, v) or managed_version(pom, g, a)
            for grp, art, floor, note in PLUGIN_FLOORS:
                if a == art and (not grp or re.search(grp, g)):
                    below = _below(version, floor)
                    if below is not False:
                        inv.build_findings.append((pom.path, f"{g}:{a}", version or "(inherited/unset)",
                                                   f"{'must move' if below else 'verify'}: {note}"))
            for grp, art, note in PLUGIN_PRESENT:
                if a == art and (not grp or re.search(grp, g)):
                    inv.build_findings.append((pom.path, f"{g}:{a}", version or "(unset)", f"must change: {note}"))
            if a == "maven-enforcer-plugin" and re.search(r"<requireJavaVersion>.*?<version>\s*\[?1\.[5-8]", block, re.S):
                inv.build_findings.append((pom.path, f"{g}:{a}", version, "must change: requireJavaVersion range excludes 11"))
            if "wildfly" in a or "jboss-as" in a:
                inv.wildfly.append(f"`{pom.path}`: plugin {g}:{a}:{version or '?'} (frozen)")
        for g, a, v, scope, managed in pom.dependencies:
            version = resolve(pom, v) or ("" if managed else managed_version(pom, g, a))
            status = ""
            for grp, art, floor, note in LIBRARY_FLOORS:
                if re.search(grp, g or "") and re.search(art, a or ""):
                    below = _below(version, floor)
                    if below:
                        status = f"must move: {note}"
                    elif below is None:
                        status = f"verify version: {note}"
            for grp, art, note in LIBRARY_PRESENT:
                if re.search(grp, g or "") and re.search(art, a or ""):
                    status = f"must change: {note}"
            if scope == "provided" and status:
                status = "container-provided (WildFly owns it — do not bump); " + status
            if re.search(r"jboss-javaee|wildfly-javaee|jboss-.*-api_", a or ""):
                inv.wildfly.append(f"`{pom.path}`: spec artifact {g}:{a}:{version or '?'} ({scope or 'managed'})")
            if status:
                inv.dependency_rows.append((pom.path, f"{g}:{a}", version or "(unresolved)",
                                            "managed" if managed else scope, status))
    for rel in files:
        name = PurePosixPath(rel).name
        if name in ("build.gradle", "build.gradle.kts"):
            inv.build_findings.append((rel, "Gradle build", "", "Gradle build present — levels: "
                                       + (", ".join(f"{s}={l}" for s, l in scope_fence.declared_java_levels(rel, (root / rel).read_text(errors="replace"))) or "none literal")))

    # -- sources, JSP, descriptors ---------------------------------------------
    for rel in files:
        suffix = PurePosixPath(rel).suffix.lower()
        reason = scope_fence.frozen_reason(PATTERN, rel)
        if reason:
            inv.frozen[(reason.split(" — ")[0], frozen_unit(rel))] += 1
        if suffix not in _TEXT_SUFFIXES:
            continue
        path = root / rel
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                inv.skipped_large.append(rel)
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        inv.files_scanned += 1
        inv.lines_scanned += text.count("\n") + 1
        module = _module_of(rel, module_dirs)

        if suffix == ".xml":
            for m in re.finditer(r"urn:jboss:domain:[\w.:-]+", text):
                inv.wildfly.append(f"`{rel}`: `{m.group(0)}`")
                break
            if PurePosixPath(rel).name == "web.xml":
                for m in _URL_PATTERN.finditer(text):
                    inv.endpoints.append(("web.xml url-pattern", m.group(1), rel))
            continue
        if suffix not in (".java",) and suffix not in _JSP:
            continue

        is_test = "/src/test/" in f"/{rel}"
        if is_test and suffix == ".java":
            inv.test_files[module] += 1
            for name, rx in TEST_FRAMEWORKS:
                if rx.search(text):
                    inv.tests[name].add(rel)

        if _ANY_CATEGORY.search(text):
            lines = text.splitlines()
            target = inv.jsp_risks if suffix in _JSP else inv.blockers
            for cat in CATEGORIES:
                hit_lines = [i for i, line in enumerate(lines, 1) if cat.regex.search(line)]
                if hit_lines:
                    target[cat.name].append((rel, hit_lines, _sample(lines[hit_lines[0] - 1])))

        if suffix == ".java" and not is_test:
            for kind, rx in ENDPOINTS:
                for m in rx.finditer(text):
                    line = text.count("\n", 0, m.start()) + 1
                    value = (m.group(1) if m.groups() and m.group(1) else "").strip()[:120]
                    inv.endpoints.append((kind, value, f"{rel}:{line}"))
    return inv


# ---------------------------------------------------------------------------
# Rendering — the four-section document the planner reads
# ---------------------------------------------------------------------------

def _clip(lines: list[str], max_rows: int, what: str) -> list[str]:
    if len(lines) <= max_rows:
        return lines
    return lines[:max_rows] + [f"", f"> **{len(lines) - max_rows} more {what} not listed here** "
                               "(INVENTORY_MAX_ROWS). They exist in the repository and must still be planned."]


def _blocker_tables(inv, change, risk, max_rows) -> list[str]:
    out: list[str] = []
    out += ["", "## Java 11 Blockers (must change)", "",
            "One row per file. These are the File Change Manifest candidates.", "",
            "| File | Lines | Category | First match | Fix |", "|---|---|---|---|---|"]
    rows = []
    for c in change:
        for f, lines, sample in inv.blockers.get(c.name, []):
            shown = ", ".join(map(str, lines[:8])) + (" …" if len(lines) > 8 else "")
            rows.append(f"| `{f}` | {shown} | {c.name} | `{sample}` | {c.fix} |")
    out += _clip(rows, max_rows, "blocker rows") or ["| — | — | none found | — | — |"]
    out += ["", "## Behavioural Risks (review; no change required by Java 11)", "",
            "| Category | Files | Examples | Note |", "|---|---|---|---|"]
    for c in risk:
        hits = inv.blockers.get(c.name, [])
        if hits:
            ex = ", ".join(f"`{f}:{l[0]}`" for f, l, _ in hits[:3])
            out.append(f"| {c.name} | {len(hits)} | {ex} | {c.fix} |")
    if not any(inv.blockers.get(c.name) for c in risk):
        out.append("| none found | 0 | — | — |")
    out += ["", "## Frozen-Zone Runtime Risks (JSP compiled by WildFly on its JDK — report only)", "",
            "| File | Lines | Category | First match |", "|---|---|---|---|"]
    jsp_rows = [f"| `{f}` | {', '.join(map(str, l[:8]))} | {c.name} | `{s.replace('|', '/')}` |"
                for c in change for f, l, s in inv.jsp_risks.get(c.name, [])]
    out += _clip(jsp_rows, max_rows, "JSP rows") or ["| — | — | none found | — |"]
    return out


def to_document(inv: Inventory, max_rows: int = 400) -> str:
    change = [c for c in CATEGORIES if c.change]
    risk = [c for c in CATEGORIES if not c.change]
    blocker_files = sorted({f for c in change for f, _, _ in inv.blockers.get(c.name, [])})
    must_build = [r for r in inv.build_findings if r[3].startswith("must")]
    must_deps = [r for r in inv.dependency_rows if r[4].startswith("must") and "container-provided" not in r[4]]
    levels = [(p.path, s, l) for p in inv.modules for s, l in p.levels]

    method = (
        "_Generated deterministically — no language model read this repository. Every file was scanned "
        "once: POMs were parsed (properties resolved through in-repo parents), and every `.java` and JSP "
        "file was matched against the Java 11 checklist. A match means the text occurs; whether it is a "
        "real use or a comment is decided when the file is changed. Business intent is not inferred._"
    )
    out = ["<!-- SECTION: ANALYSIS -->", "", "# Java 11 Inventory — Analysis", "", method, "",
           "## Scope and Coverage", "",
           f"- Files in the repository (build output excluded): **{inv.files_total:,}**",
           f"- Files scanned: **{inv.files_scanned:,}** ({inv.lines_scanned:,} lines)",
           f"- Maven modules: **{len(inv.modules)}**",
           f"- Files needing a Java 11 code change: **{len(blocker_files)}**",
           f"- Build findings that must change: **{len(must_build)}**; libraries that must move: **{len(must_deps)}**",
           f"- JSP/tag files with Java 11 runtime risks (frozen — report only): "
           f"**{len({f for c in change for f, _, _ in inv.jsp_risks.get(c.name, [])})}**",
           "", "The file-by-file tables (Java 11 Blockers, Behavioural Risks, Frozen-Zone Runtime Risks) are in "
           "the Technical Specification, which is what the planner reads."]
    if inv.skipped_large:
        out.append(f"- **Not scanned (over {_MAX_FILE_BYTES:,} bytes):** " + ", ".join(f"`{f}`" for f in inv.skipped_large[:20]))
    out += ["", "## Open Questions", "",
            "- Does the WildFly runtime run on Java 11 at deployment time? Evidence found: "
            + ("; ".join(inv.wildfly[:5]) if inv.wildfly else "none in the repository — confirm with the platform owner."),
            "- CORBA / JavaFX / URLClassLoader matches, if any, need a human decision per file."]

    out += ["", "<!-- SECTION: BRD -->", "", "# Java 11 Inventory — Scope", "", method, "",
            "## Objective", "", "Compile and package the unchanged application at Java release 11, deployable to "
            "the same WildFly with the same JSPs. No business behaviour changes.", "",
            "## In Scope", "", f"- {len(blocker_files)} Java source file(s) listed under Java 11 Blockers",
            f"- {len(inv.modules)} build file(s): compiler release, plugins and libraries listed in the Technical Specification",
            "", "## Frozen (never modified)", "", "| Path | Kind | Files | Status |", "|---|---|---|---|"]
    out += _clip([f"| `{path}` | {kind} | {n} | frozen — unchanged |" for (kind, path), n in sorted(inv.frozen.items(), key=lambda kv: kv[0][1])],
                 max_rows, "frozen paths") or ["| — | — | 0 | — |"]
    out += ["", "## Out of Scope", "", "Spring Boot, Jakarta (`jakarta.*`), Java 17+, JSP replacement, container "
            "upgrade, optional language modernisation, and EOL libraries that still run on Java 11.",
            "", "## Behaviour to Preserve", "",
            f"{len(inv.endpoints)} entry point(s) found by annotation and `web.xml` — listed in the Technical "
            "Specification's API Contracts. Every one must behave the same after the upgrade."]

    out += ["", "<!-- SECTION: TECHNICAL_SPECIFICATION -->", "", "# Java 11 Inventory — Technical Specification", "",
            "## Modules", "", "| POM | artifactId | Packaging | finalName | Parent |", "|---|---|---|---|---|"]
    out += [f"| `{p.path}` | {p.artifact} | {p.packaging} | {p.final_name or '—'} | {p.parent or '—'} |" for p in inv.modules]
    out += ["", "## Declared Java Levels", "", "| File | Setting | Level |", "|---|---|---|"]
    out += [f"| `{f}` | {s} | {l} |" for f, s, l in levels] or ["| — | none declared literally | — |"]
    out += ["", "## Build Plugins", "", "| POM | Plugin | Version | Finding |", "|---|---|---|---|"]
    out += _clip([f"| `{p}` | {i} | {v} | {f} |" for p, i, v, f in inv.build_findings], max_rows, "plugin rows") \
        or ["| — | — | — | nothing Java 11 needs to change |"]
    out += ["", "## Dependencies Affected by Java 11", "", "| POM | Coordinate | Version | Scope | Finding |", "|---|---|---|---|---|"]
    out += _clip([f"| `{p}` | {c} | {v} | {s} | {f} |" for p, c, v, s, f in inv.dependency_rows], max_rows, "dependency rows") \
        or ["| — | — | — | — | none |"]
    out += _blocker_tables(inv, change, risk, max_rows)
    out += ["", "## Removed-JDK-Module Usage", "", "| Category | Files | Fix |", "|---|---|---|"]
    out += [f"| {c.name} | {len(inv.blockers[c.name])} | {c.fix} |" for c in change if inv.blockers.get(c.name)] \
        or ["| — | 0 | — |"]
    out += ["", "## API Contracts (entry points)", "", "| Type | Value | Where |", "|---|---|---|"]
    out += _clip([f"| {k} | `{v.replace('|', '/')}` | `{w}` |" if v else f"| {k} | — | `{w}` |" for k, v, w in inv.endpoints],
                 max_rows, "entry points") or ["| — | — | none found |"]
    out += ["", "## WildFly Evidence (frozen)", ""] + ([f"- {e}" for e in dict.fromkeys(inv.wildfly)] or ["- none found"])

    out += ["", "<!-- SECTION: TEST_INVENTORY -->", "", "# Java 11 Inventory — Tests", "",
            "| Framework | Test files | Java 11 impact |", "|---|---|---|"]
    impact = {"Mockito": "Mockito 1.x cannot mock on Java 11 — check the version in Dependencies",
              "PowerMock": "PowerMock 1.x requires Mockito 1 — 2.0.x needed", "JUnit 3": "runs on 11; deprecated",
              "JUnit 4": "runs on 11", "Arquillian": "needs a running WildFly on Java 11"}
    out += [f"| {n} | {len(fs)} | {impact.get(n, '—')} |" for n, fs in sorted(inv.tests.items())] or ["| — | 0 | — |"]
    out += ["", "| Module | Test source files |", "|---|---|"]
    out += [f"| `{m}` | {n} |" for m, n in sorted(inv.test_files.items())] or ["| — | 0 |"]
    out += ["", "No tests were executed. The build loop compiles and packages (test sources included) but does "
            "not run them — running the suite on JDK 11 is a human step.", "", "<!-- SECTION: END -->", ""]
    return "\n".join(out)
