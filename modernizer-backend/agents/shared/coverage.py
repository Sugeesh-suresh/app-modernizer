"""
Measuring unit-test coverage of a Maven repository, and reading it.

The test-coverage pipeline (cli/coverage_run.py) asks a model for tests and trusts nothing it says about them:
the number comes from here. `measure()` runs the repository's own tests under the JaCoCo agent and reads the
report; `rank_gaps()` says which classes are worth the next round; `scan_tests()` finds tests that assert nothing;
`digests()` / `diff_digests()` prove that only test files were written.

The agent is attached through JAVA_TOOL_OPTIONS, not through the pom: a Surefire `<argLine>` written out in the
pom (very common) silently defeats `jacoco:prepare-agent`, and the repository's build files must stay as they are.
`includes=` limits it to the repository's own packages, so Maven's JVM is not instrumented in any useful sense.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from . import build_summary, fswalk, java_env, progress, toolchain

TEST_PATH = re.compile(r"(?:^|/)src/test/(?:java|resources|groovy|kotlin)/")
_ACCESSOR = re.compile(r"^(?:get|set|is|has)[A-Z0-9_]|^(?:toString|hashCode|equals|canEqual)$")


class CoverageError(RuntimeError):
    """The measurement could not be made; the message says what to fix."""


# ═════════════════════════════════════════════════════════════════════════════
# The coverage report
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ClassCov:
    """One source file's coverage (nested and anonymous classes are part of their file)."""
    module: str                               # path of the module's folder relative to the repository ("" = root)
    package: str                              # com.acme.shop
    source: str                               # Order.java
    lines_missed: int = 0
    lines_covered: int = 0
    branches_missed: int = 0
    branches_covered: int = 0
    methods_missed: int = 0
    methods_covered: int = 0
    missed: list[int] = field(default_factory=list)       # uncovered line numbers
    partial: list[int] = field(default_factory=list)      # lines with an untaken branch
    trivial: bool = False                                 # only accessors / toString / equals / hashCode

    @property
    def name(self) -> str:
        stem = self.source[:-5] if self.source.endswith(".java") else self.source
        return f"{self.package}.{stem}" if self.package else stem

    @property
    def lines(self) -> int:
        return self.lines_missed + self.lines_covered

    @property
    def branches(self) -> int:
        return self.branches_missed + self.branches_covered

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("module", "package", "source", "lines_missed", "lines_covered",
                                              "branches_missed", "branches_covered", "methods_missed",
                                              "methods_covered", "missed", "partial", "trivial")}

    @classmethod
    def from_dict(cls, d: dict) -> "ClassCov":
        return cls(**d)


@dataclass
class Totals:
    lines_missed: int = 0
    lines_covered: int = 0
    branches_missed: int = 0
    branches_covered: int = 0
    classes: int = 0

    @property
    def line_pct(self) -> float:
        n = self.lines_missed + self.lines_covered
        return round(100.0 * self.lines_covered / n, 1) if n else 0.0

    @property
    def branch_pct(self) -> float:
        n = self.branches_missed + self.branches_covered
        return round(100.0 * self.branches_covered / n, 1) if n else 0.0

    def add(self, c: ClassCov) -> None:
        self.lines_missed += c.lines_missed
        self.lines_covered += c.lines_covered
        self.branches_missed += c.branches_missed
        self.branches_covered += c.branches_covered
        self.classes += 1


@dataclass
class Report:
    classes: list[ClassCov] = field(default_factory=list)

    def selected(self, scope: list[str] | None = None, exclude: list[str] | None = None) -> list[ClassCov]:
        """The classes the person's scope covers: under one of the packages in `scope` (all when empty), and
        matching none of the `exclude` patterns (fnmatch on the class name, e.g. `*.generated.*`, `*Dto`)."""
        out = []
        for c in self.classes:
            if scope and not any(c.name == s or c.name.startswith(s.rstrip(".") + ".") for s in scope):
                continue
            if exclude and any(fnmatch.fnmatchcase(c.name, pat) for pat in exclude):
                continue
            out.append(c)
        return out

    def totals(self, scope: list[str] | None = None, exclude: list[str] | None = None) -> Totals:
        t = Totals()
        for c in self.selected(scope, exclude):
            t.add(c)
        return t

    def by_package(self, scope: list[str] | None = None, exclude: list[str] | None = None) -> dict[str, Totals]:
        out: dict[str, Totals] = {}
        for c in self.selected(scope, exclude):
            out.setdefault(c.package or "(default)", Totals()).add(c)
        return dict(sorted(out.items()))

    def get(self, name: str) -> ClassCov | None:
        return next((c for c in self.classes if c.name == name), None)

    def to_json(self) -> list[dict]:
        return [c.to_dict() for c in self.classes]

    @classmethod
    def from_json(cls, rows: list[dict]) -> "Report":
        return cls([ClassCov.from_dict(r) for r in rows])


def _counter(el: ET.Element, kind: str) -> tuple[int, int]:
    for c in el.findall("counter"):
        if c.get("type") == kind:
            return int(c.get("missed", 0)), int(c.get("covered", 0))
    return 0, 0


def parse_jacoco_xml(path: Path, module: str = "") -> list[ClassCov]:
    """Every source file of a JaCoCo `jacoco.xml`, with its uncovered and partially covered lines."""
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        raise CoverageError(f"Could not read the coverage report {path}: {exc}") from None
    out: list[ClassCov] = []
    for pkg in tree.getroot().iter("package"):
        package = (pkg.get("name") or "").replace("/", ".")
        trivial: dict[str, bool] = {}
        for cls in pkg.findall("class"):
            src = cls.get("sourcefilename") or ""
            names = [m.get("name") or "" for m in cls.findall("method") if (m.get("name") or "") not in ("<init>", "<clinit>")
                     and not (m.get("name") or "").startswith("lambda$")]
            only_accessors = bool(names) and all(_ACCESSOR.match(n) for n in names)
            trivial[src] = trivial.get(src, True) and (only_accessors or not names)
        for sf in pkg.findall("sourcefile"):
            name = sf.get("name") or ""
            lm, lc = _counter(sf, "LINE")
            bm, bc = _counter(sf, "BRANCH")
            mm, mc = _counter(sf, "METHOD")
            row = ClassCov(module=module, package=package, source=name, lines_missed=lm, lines_covered=lc,
                           branches_missed=bm, branches_covered=bc, methods_missed=mm, methods_covered=mc,
                           trivial=trivial.get(name, False))
            for line in sf.findall("line"):
                nr = int(line.get("nr", 0))
                if int(line.get("ci", 0)) == 0 and int(line.get("mi", 0)) > 0:
                    row.missed.append(nr)
                elif int(line.get("mb", 0)) > 0:
                    row.partial.append(nr)
            out.append(row)
    return out


def load_reports(root: Path) -> Report:
    """Every module's `target/site/jacoco/jacoco.xml` under `root`, as one report."""
    classes: list[ClassCov] = []
    for xml in sorted(root.rglob("jacoco.xml")):
        if xml.parent.name != "jacoco" or xml.parent.parent.name != "site":
            continue
        module = xml.parents[3].relative_to(root).as_posix()
        classes += parse_jacoco_xml(xml, "" if module == "." else module)
    return Report(classes)


def rank_gaps(report: Report, scope: list[str] | None = None, exclude: list[str] | None = None,
              skip: set[str] | None = None, min_lines: int | None = None, include_trivial: bool = False) -> list[ClassCov]:
    """The classes worth the next round, most valuable first: uncovered lines, with untaken branches counting
    half. A class below `min_lines` uncovered lines, a class of accessors only, and one a writer already
    reported as untestable (`skip`) are left out."""
    floor = config.COVERAGE_MIN_CLASS_LINES if min_lines is None else min_lines
    rows = [c for c in report.selected(scope, exclude)
            if c.lines_missed >= floor and c.name not in (skip or set()) and (include_trivial or not c.trivial)]
    return sorted(rows, key=lambda c: (-(c.lines_missed + 0.5 * c.branches_missed), c.name))


def pick_batch(gaps: list[ClassCov], max_classes: int | None = None, max_lines: int | None = None) -> list[ClassCov]:
    """The top of `gaps` up to a number of classes and of uncovered lines (always at least one class)."""
    max_classes = max_classes or config.COVERAGE_BATCH_CLASSES
    max_lines = max_lines or config.COVERAGE_BATCH_LINES
    batch: list[ClassCov] = []
    lines = 0
    for c in gaps:
        if batch and (len(batch) >= max_classes or lines + c.lines_missed > max_lines):
            break
        batch.append(c)
        lines += c.lines_missed
    return batch


def ranges(numbers: list[int]) -> str:
    """`[3, 4, 5, 9]` -> `3-5, 9`."""
    out, start, prev = [], None, None
    for n in sorted(set(numbers)):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if prev != start else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if prev != start else str(start))
    return ", ".join(out)


# ═════════════════════════════════════════════════════════════════════════════
# The repository's test stack
# ═════════════════════════════════════════════════════════════════════════════

_STACK_MARKERS = (
    ("JUnit 4", r"org\.junit\.(?:Test|Assert|Before|After|Rule|runner)"),
    ("JUnit 5", r"org\.junit\.jupiter"),
    ("TestNG", r"org\.testng"),
    ("Mockito", r"org\.mockito"),
    ("PowerMock", r"org\.powermock"),
    ("EasyMock", r"org\.easymock"),
    ("AssertJ", r"org\.assertj"),
    ("Hamcrest", r"org\.hamcrest"),
    ("Spring Test", r"org\.springframework\.(?:test|mock\.web)"),
    ("Spring Boot Test", r"org\.springframework\.boot\.test"),
    ("Testcontainers", r"org\.testcontainers"),
    ("H2", r"org\.h2\.|jdbc:h2:"),
    ("DbUnit", r"org\.dbunit"),
)
_POM_ARTIFACTS = (
    ("JUnit 4", "<artifactId>junit</artifactId>"), ("JUnit 5", "junit-jupiter"), ("TestNG", "<artifactId>testng</artifactId>"),
    ("Mockito", "mockito-core"), ("Mockito", "mockito-inline"), ("Mockito", "mockito-junit-jupiter"),
    ("PowerMock", "powermock"), ("EasyMock", "easymock"), ("AssertJ", "assertj-core"), ("Hamcrest", "hamcrest"),
    ("Spring Test", "spring-test"), ("Spring Boot Test", "spring-boot-starter-test"),
    ("Testcontainers", "testcontainers"), ("H2", "<artifactId>h2</artifactId>"), ("DbUnit", "dbunit"),
)


@dataclass
class Stack:
    frameworks: list[str] = field(default_factory=list)       # what the repository can use, in order of use
    versions: dict[str, str] = field(default_factory=dict)     # Mockito / JUnit versions read from the poms
    test_files: int = 0
    test_methods: int = 0
    sample: str = ""                                           # the existing test to imitate (relative path)
    java_release: int = 8
    modules: list[str] = field(default_factory=list)           # folders with sources
    packages: list[str] = field(default_factory=list)          # top-level package prefixes of the main sources
    build_tool: str = "maven"
    jsp_files: int = 0
    has_jacoco: bool = False

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _pom_properties(text: str) -> dict[str, str]:
    block = re.search(r"<properties>(.*?)</properties>", text, re.S)
    return dict(re.findall(r"<([\w.\-]+)>\s*([^<]+?)\s*</\1>", block.group(1))) if block else {}


def _version_of(text: str, artifact: str, props: dict[str, str]) -> str:
    m = re.search(r"<artifactId>\s*" + re.escape(artifact) + r"\s*</artifactId>\s*(?:<[^>]+>[^<]*</[^>]+>\s*)*?<version>\s*([^<\s]+)\s*</version>", text)
    if not m:
        return ""
    v = m.group(1)
    return props.get(v[2:-1], v) if v.startswith("${") else v


def _normalise_release(value: str) -> int:
    value = (value or "").strip()
    if value.startswith("1."):
        value = value[2:]
    return int(value) if value.isdigit() else 0


def detect_stack(root: Path) -> Stack:
    """What the repository tests with: the frameworks (from its poms and the imports of its existing tests), the
    Java level, the modules and packages of its sources, and one existing test to use as the style sample."""
    s = Stack()
    poms = [p for p in fswalk.files(root, "pom.xml")]
    if not poms:
        s.build_tool = "gradle" if (next(fswalk.files(root, "build.gradle"), None) or
                                    next(fswalk.files(root, "build.gradle.kts"), None)) else "none"
    seen: dict[str, int] = {}
    releases: list[int] = []
    for pom in sorted(poms):
        text = pom.read_text(encoding="utf-8", errors="replace")
        props = _pom_properties(text)
        for key in ("maven.compiler.release", "maven.compiler.source", "maven.compiler.target", "java.version"):
            if props.get(key):
                releases.append(_normalise_release(props[key]))
        releases += [_normalise_release(v) for v in re.findall(r"<(?:source|target|release)>\s*([\d.]+)\s*</", text)]
        for name, marker in _POM_ARTIFACTS:
            if marker in text:
                seen[name] = seen.get(name, 0) + 1
        for art, label in (("mockito-core", "Mockito"), ("junit", "JUnit"), ("junit-jupiter", "JUnit 5"),
                           ("spring-test", "Spring Test")):
            v = _version_of(text, art, props)
            if v and label not in s.versions:
                s.versions[label] = v
        if "jacoco-maven-plugin" in text:
            s.has_jacoco = True
    s.java_release = max([r for r in releases if r] or [8])
    imports: dict[str, int] = {}
    best, best_score = "", -1
    for f in fswalk.files(root, "*.java"):
        rel = f.relative_to(root).as_posix()
        if not TEST_PATH.search("/" + rel) and "/src/test/" not in "/" + rel:
            continue
        s.test_files += 1
        text = f.read_text(encoding="utf-8", errors="replace")
        methods = len(re.findall(r"@(?:Test|ParameterizedTest|RepeatedTest)\b", text))
        s.test_methods += methods
        for name, pattern in _STACK_MARKERS:
            if re.search(pattern, text):
                imports[name] = imports.get(name, 0) + 1
        score = methods + 3 * ("org.mockito" in text) + 2 * bool(re.search(r"@(?:Before|BeforeEach)\b", text))
        if methods and score > best_score and methods <= 25:
            best, best_score = rel, score
    s.sample = best
    s.frameworks = [n for n, _ in sorted(imports.items(), key=lambda kv: -kv[1])]
    s.frameworks += [n for n in seen if n not in s.frameworks]
    modules, packages = set(), set()
    for f in fswalk.files(root, "*.java"):
        rel = f.relative_to(root).as_posix()
        if "/src/main/java/" in "/" + rel:
            modules.add(rel.split("src/main/java/")[0].rstrip("/"))
            head = f.read_text(encoding="utf-8", errors="replace")[:4000]
            m = re.search(r"^\s*package\s+([\w.]+)\s*;", head, re.M)
            if m:
                parts = m.group(1).split(".")
                packages.add(".".join(parts[:2]) if len(parts) > 2 else m.group(1))
    s.modules = sorted(modules)
    s.packages = sorted(packages)
    s.jsp_files = sum(1 for _ in fswalk.files(root, "*.jsp"))
    return s


# ═════════════════════════════════════════════════════════════════════════════
# Measuring
# ═════════════════════════════════════════════════════════════════════════════

def jacoco_version(java_major: int | None) -> str:
    """The JaCoCo release that can read the classes of the JDK the tests run on."""
    if config.JACOCO_VERSION:
        return config.JACOCO_VERSION
    major = java_major or 8
    return "0.8.12" if major <= 23 else ("0.8.13" if major == 24 else "0.8.14")


@dataclass
class TestResults:
    __test__ = False                                       # not a pytest class
    total: int = 0
    failed: list[str] = field(default_factory=list)        # Class#method of every failed or errored test
    skipped: int = 0
    by_class: dict[str, int] = field(default_factory=dict)   # fully qualified test class -> tests run
    reasons: dict[str, str] = field(default_factory=dict)    # Class#method -> first line of the failure

    @property
    def passed(self) -> int:
        return self.total - len(self.failed) - self.skipped


def read_test_results(root: Path) -> TestResults:
    res = TestResults()
    for xml in sorted(root.rglob("TEST-*.xml")):
        if "surefire-reports" not in xml.parts:
            continue
        try:
            suite = ET.parse(xml).getroot()
        except (ET.ParseError, OSError):
            continue
        cls = suite.get("name") or xml.stem[5:]
        n = int(suite.get("tests", 0))
        res.total += n
        res.skipped += int(suite.get("skipped", 0))
        res.by_class[cls] = res.by_class.get(cls, 0) + n
    for name, reason, _ in java_env.surefire_report(root):
        if name not in res.failed:
            res.failed.append(name)
            res.reasons[name] = reason
    return res


@dataclass
class Measurement:
    ok: bool                                   # the build compiled and the tests ran (failing tests do not make it false)
    summary: str                               # build_summary text
    report: Report
    tests: TestResults
    output_tail: str = ""
    problem: str = ""                          # why not ok, in words
    environment: bool = False                  # not ok because dependencies could not be fetched


def _agent_jar(root: Path, version: str, java_home: str | None) -> Path:
    """The JaCoCo agent jar, fetched once through Maven (so the repository settings / mirrors apply)."""
    dest = toolchain.tools_dir() / "jacoco" / version / "jacocoagent.jar"
    if dest.is_file():
        return dest
    progress.stage(f"Coverage: fetching the JaCoCo {version} agent through Maven")
    work = Path(tempfile.mkdtemp(prefix="jacoco-agent-"))
    try:
        code, out = java_env.run_maven(work, ["dependency:copy", f"-Dartifact=org.jacoco:org.jacoco.agent:{version}:jar:runtime",
                                              f"-DoutputDirectory={work}", "-Dmdep.stripVersion=true"],
                                       java_home=java_home, timeout=600)
        jar = next(iter(sorted(work.glob("org.jacoco.agent*.jar"))), None)
        if code != 0 or jar is None:
            raise CoverageError(f"Could not fetch the JaCoCo {version} agent (org.jacoco:org.jacoco.agent) through "
                                "Maven — check the repository / mirror settings (MAVEN_SETTINGS) and network. "
                                + build_summary.redact(build_summary.summarize(out, code).text()))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(jar, dest)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return dest


def _short_dir() -> Path:
    """A short folder without spaces for the agent jar and the data file. The agent's options travel in
    JAVA_TOOL_OPTIONS, and a JDK 8 silently ignores the agent when that value is long (about 1,000 characters,
    proxy settings included) — a repository checked out deep under `C:\\Users\\Some Name\\OneDrive - ...` would
    otherwise measure 0%. Spaces split the options too."""
    candidates = [Path("/tmp") / "mzcov"] if os.name != "nt" else \
        [Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "mzcov", Path(os.environ.get("SystemDrive", "C:") + "\\") / "mzcov"]
    candidates.append(Path(tempfile.gettempdir()) / "mzcov")
    for folder in candidates:
        if " " in str(folder):
            continue
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".w"
            probe.write_text("x")
            probe.unlink()
            return folder
        except OSError:
            continue
    return Path(tempfile.gettempdir()) / "mzcov"


def _clear(root: Path) -> None:
    for d in list(root.rglob("jacoco")):
        if d.is_dir() and d.parent.name == "site" and "target" in d.parts:
            shutil.rmtree(d, ignore_errors=True)
    java_env.clear_reports(root)


def measure(root: Path, java_home: str | None, packages: list[str] | None = None, only_tests: list[str] | None = None,
            label: str = "", with_coverage: bool = True, timeout: int | None = None) -> Measurement:
    """Run the repository's tests (all, or only the named test classes) and read what they covered.
    Failing tests are recorded, never fatal: the pipeline compares them with the baseline's."""
    version = jacoco_version(java_major_of(java_home))
    exec_file = _short_dir() / f"{uuid.uuid4().hex[:8]}.exec"
    env_extra: dict[str, str] = {}
    args = ["-fae", "-Dmaven.test.failure.ignore=true", "-DfailIfNoTests=false", "-Dsurefire.failIfNoSpecifiedTests=false"]
    repo_jacoco = any("jacoco-maven-plugin" in p.read_text(encoding="utf-8", errors="replace") for p in fswalk.files(root, "pom.xml"))
    if only_tests:
        args.append("-Dtest=" + ",".join(only_tests))
    args.append("test")
    if with_coverage:
        cached = _agent_jar(root, version, java_home)
        jar = exec_file.parent / f"jacocoagent-{version}.jar"
        if not jar.is_file() or jar.stat().st_size != cached.stat().st_size:
            shutil.copy2(cached, jar)
        options = f"destfile={exec_file},append=true"
        if packages:
            options += ",includes=" + ":".join(f"{p.rstrip('.*')}.*" for p in packages)
        flag = f"-javaagent:{jar}={options}"
        env_extra["JAVA_TOOL_OPTIONS"] = (os.environ.get("JAVA_TOOL_OPTIONS", "") + " " + flag).strip()
        option_chars = len(env_extra["JAVA_TOOL_OPTIONS"])
        if repo_jacoco:                          # the repository's own jacoco would attach a second agent: leave it out
            args.append("-Djacoco.skip=true")
        _clear(root)
    else:
        java_env.clear_reports(root)
    progress.stage(label or "Coverage: running the tests"
                   + (" under JaCoCo" if with_coverage else "") + " — a first build downloads every dependency")
    code, out = java_env.run_maven(root, args, java_home=java_home, timeout=timeout, env_extra=env_extra)
    tests = read_test_results(root)
    agent_wrote = exec_file.is_file()
    if with_coverage and not agent_wrote and not tests.total and not only_tests:
        exec_file.write_bytes(b"\x01\xc0\xc0\x10\x07")      # no test ran: an empty data file reports every class as uncovered
    if with_coverage and exec_file.is_file():
        progress.stage("Coverage: reading the JaCoCo data (report)")
        java_env.run_maven(root, ["-fae", f"org.jacoco:jacoco-maven-plugin:{version}:report", f"-Djacoco.dataFile={exec_file}"],
                           java_home=java_home, timeout=timeout)
    summary = build_summary.redact(build_summary.summarize(out, code).text())
    s = build_summary.summarize(out, code)
    report = load_reports(root) if with_coverage else Report()
    ok = bool(s.passed) and not s.compile_error_count
    problem = ""
    classified = java_env.classify(out, code, root)
    environment = bool(classified.environment) and not tests.total
    if not ok:
        if environment:
            problem = "dependencies or plugins could not be downloaded: " + classified.environment[0][:300]
        elif s.compile_error_count or classified.compile:
            problem = "the code does not compile: " + "; ".join((classified.compile or [])[:3])[:400]
        elif s.passed is None:
            problem = "the build produced no verdict (cut off or timed out)"
        else:
            problem = "the build failed: " + "; ".join((classified.other or [])[:3])[:400]
    elif with_coverage and tests.total and (not agent_wrote or not report.classes):
        ok, problem = False, (f"{tests.total} test(s) ran but JaCoCo recorded nothing — the agent did not attach to the "
                              "tests' JVM (an unsupported JDK / JaCoCo version, a JAVA_TOOL_OPTIONS of "
                              f"{option_chars} characters that an old JDK truncates, or tests run in a JVM that ignores "
                              "the variable). Set JACOCO_VERSION, or shorten JAVA_TOOL_OPTIONS.")
    if with_coverage:
        exec_file.unlink(missing_ok=True)
    return Measurement(ok, summary, report, tests, out[-1500:], problem, environment)


def java_major_of(java_home: str | None) -> int | None:
    """The major version of a JDK folder, from its `release` file (None when unknown)."""
    if not java_home:
        return None
    f = Path(java_home) / "release"
    try:
        m = re.search(r'JAVA_VERSION="?([\d._]+)', f.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return java_env.java_major(f'version "{m.group(1)}"') if m else None


# ═════════════════════════════════════════════════════════════════════════════
# What a round may touch
# ═════════════════════════════════════════════════════════════════════════════

_MAX_HASH = 2_000_000


def digests(root: Path) -> dict[str, str]:
    """`path -> content hash` of every file the scans see (build output and `.modernizer` excluded)."""
    out: dict[str, str] = {}
    for f in fswalk.files(root):
        try:
            rel = f.relative_to(root).as_posix()
            if rel.startswith(".modernizer/"):
                continue
            size = f.stat().st_size
            out[rel] = hashlib.sha1(f.read_bytes()).hexdigest() if size <= _MAX_HASH else f"size:{size}"
        except OSError:
            continue
    return out


def diff_digests(before: dict[str, str], after: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    """(added, changed, removed) paths between two `digests()`."""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(p for p in before.keys() & after.keys() if before[p] != after[p])
    return added, changed, removed


def is_test_path(rel: str) -> bool:
    return bool(TEST_PATH.search("/" + rel.replace("\\", "/")))


def audit_round(root: Path, baseline_dir: Path, before: dict[str, str]) -> dict[str, list[str]]:
    """What a writer round changed that it was not allowed to, put back as it was: production or build files
    it added, changed or removed, and any existing test it changed or removed (a test the repository had when
    the run started is frozen). Returns {"reverted": [...], "new_tests": [...], "touched_tests": [...]}."""
    after = digests(root)
    added, changed, removed = diff_digests(before, after)
    reverted: list[str] = []
    new_tests: list[str] = []
    touched: list[str] = []

    def frozen(rel: str) -> bool:
        return (baseline_dir / rel).is_file()

    for rel in added:
        if is_test_path(rel) and not frozen(rel):
            if rel.endswith(".java"):
                new_tests.append(rel)
            continue
        target = root / rel
        if is_test_path(rel) and frozen(rel):             # a frozen test was deleted and re-added: restore its bytes
            shutil.copy2(baseline_dir / rel, target)
            reverted.append(rel)
            continue
        target.unlink(missing_ok=True)
        reverted.append(rel)
    for rel in changed + removed:
        if is_test_path(rel) and not frozen(rel):
            if rel in changed and rel.endswith(".java"):
                touched.append(rel)
            continue                                       # a file created in this run may be edited or deleted
        src = baseline_dir / rel
        if src.is_file():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, root / rel)
            reverted.append(rel)
    return {"reverted": sorted(set(reverted)), "new_tests": new_tests, "touched_tests": touched}


# ═════════════════════════════════════════════════════════════════════════════
# Tests that prove nothing
# ═════════════════════════════════════════════════════════════════════════════

_TEST_METHOD = re.compile(
    r"@(?P<ann>Test|ParameterizedTest|RepeatedTest|TestFactory)\b(?P<args>\s*\([^)]*\))?(?P<mods>(?:\s*@\w+(?:\([^)]*\))?)*)"
    r"\s*(?:public\s+|protected\s+|private\s+)?(?:static\s+)?(?:final\s+)?void\s+(?P<name>\w+)\s*\([^)]*\)"
    r"(?:\s*throws\s+[\w.,\s]+)?\s*\{")
_ASSERT = re.compile(r"\b(?:assert[A-Z]\w*|assertThat|assertThrows|assertAll|assertTimeout\w*|fail|verify|verifyNoMoreInteractions|"
                     r"verifyNoInteractions|verifyZeroInteractions|expect\w*|andExpect|then|should\w*|check\w*|Assert\.\w+|"
                     r"Assertions\.\w+|MatcherAssert\.\w+|ArgumentCaptor)\s*[(.<]|\bassertThat\b|\bexpectedException\b|"
                     r"\.isEqualTo\(|\.isTrue\(\)|\.isFalse\(\)|\.isNull\(\)|\.hasSize\(")
_TRIVIAL = re.compile(r"^\s*(?:Assert\.|Assertions\.)?(?:assertNotNull\s*\([^;]*\)|assertTrue\s*\(\s*true\s*\)|assertFalse\s*\(\s*false\s*\)|"
                      r"assertNull\s*\(\s*null\s*\))\s*;\s*$", re.M)
_DISABLED = re.compile(r"@(?:Ignore|Disabled)\b")


def _body(text: str, open_brace: int) -> str:
    depth, i = 0, open_brace
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace + 1:i]
        i += 1
    return text[open_brace + 1:]


def _strip_comments(src: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", lambda m: " " * len(m.group(0)) if m.group(0).startswith("/*") else "", src, flags=re.S)


@dataclass
class TestScan:
    __test__ = False
    file: str
    tests: int = 0
    weak: list[str] = field(default_factory=list)         # "method — why"
    disabled: bool = False


def scan_tests(path: Path, rel: str = "") -> TestScan:
    """The tests of one file, and which of them assert nothing worth the name: no assertion or verification at
    all, or only `assertNotNull` / `assertTrue(true)`. A `@Test(expected=...)` and an `assertThrows` count."""
    text = _strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    scan = TestScan(rel or path.name, disabled=bool(_DISABLED.search(text)))
    for m in _TEST_METHOD.finditer(text):
        scan.tests += 1
        body = _body(text, m.end() - 1)
        args = (m.group("args") or "") + (m.group("mods") or "")
        if "expected" in args and "=" in args:
            continue
        found = _ASSERT.findall(body)
        if not found and "ExpectedException" not in text:
            scan.weak.append(f"{m.group('name')} — no assertion or verification")
        elif found and not _ASSERT.search(_TRIVIAL.sub("", body)):
            scan.weak.append(f"{m.group('name')} — only trivial assertions (assertNotNull / assertTrue(true))")
    return scan


def declared_tests(path: Path) -> list[str]:
    """Names of the test methods in a file."""
    text = _strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    return [m.group("name") for m in _TEST_METHOD.finditer(text)]
