"""
The build environment for the Java 8 -> 11 pipeline: which JDK and Maven
settings builds use, what the machine actually has, and how to read a Maven
build's output.

A migration can only be verified on the JDK it targets, with the repository
access the project's own builds use. Without checking both first, a broken
environment (Maven on JDK 8, no credentials for the internal repository) is
indistinguishable from a broken migration, and the fixer "fixes" environment
problems in the code. The preflight (main._run_java11_preflight) uses this
module before anything is planned; the validator's build tool uses it after.

Settings (agents/config.py):
  MIGRATION_JAVA_HOME — JDK the builds run on (Maven's JAVA_HOME); default:
                        whatever `java`/`mvn` on PATH use.
  BASELINE_JAVA_HOME  — optional JDK 8: the uploaded code's tests are run on it
                        once, so failures that predate the migration are not
                        blamed on it.
  MAVEN_SETTINGS      — optional settings.xml (mirrors, credentials) passed to
                        every Maven call as `-s`.
"""
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .. import config

_IS_WINDOWS = os.name == "nt"


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def build_env(java_home: str | None = None) -> dict[str, str]:
    """The process environment for a build: JAVA_HOME set and its bin first
    on PATH when a JDK is configured, otherwise the server's own."""
    env = dict(os.environ)
    home = java_home if java_home is not None else config.MIGRATION_JAVA_HOME
    if home:
        env["JAVA_HOME"] = home
        env["PATH"] = str(Path(home) / "bin") + os.pathsep + env.get("PATH", "")
    return env


def maven_executable(cwd: Path | None = None) -> str | None:
    """The Maven launcher: the project's wrapper if present, else `mvn` on PATH."""
    if cwd is not None:
        for name in (("mvnw.cmd",) if _IS_WINDOWS else ()) + ("mvnw",):
            wrapper = cwd / name
            if wrapper.is_file() and (_IS_WINDOWS or os.access(wrapper, os.X_OK)):
                return str(wrapper)
    for name in (("mvn.cmd", "mvn.bat") if _IS_WINDOWS else ()) + ("mvn",):
        found = shutil.which(name)
        if found:
            return found
    return None


def maven_settings_args(args: list[str]) -> list[str]:
    """`-s <settings>` when MAVEN_SETTINGS is configured and the call has none."""
    if config.MAVEN_SETTINGS and "-s" not in args and "--settings" not in args:
        return ["-s", config.MAVEN_SETTINGS]
    return []


def _run(cmd: list[str], cwd: Path, env: dict, timeout: int) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT after {timeout}s: {' '.join(cmd)}"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run_maven(cwd: Path, args: list[str], java_home: str | None = None,
              timeout: int | None = None) -> tuple[int, str]:
    """Run Maven in `cwd` with the configured JDK and settings, batch mode."""
    mvn = maven_executable(cwd)
    if not mvn:
        return 127, "mvn: not found on PATH (and no Maven wrapper in the project)"
    cmd = [mvn, "-B", *maven_settings_args(args), *args]
    return _run(cmd, cwd, build_env(java_home), timeout or config.VALIDATE_TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

def java_major(text: str) -> int | None:
    """Major version from `java -version` / `mvn -v` text: "1.8.0_392" -> 8, "11.0.22" -> 11."""
    m = re.search(r'(?:version\s+"?|Java version:\s*)(\d+)(?:\.(\d+))?', text)
    if not m:
        return None
    major = int(m.group(1))
    return int(m.group(2)) if major == 1 and m.group(2) else major


@dataclass
class Toolchain:
    os: str = ""
    java_home: str = ""
    java: str = ""                 # first line of `java -version`
    java_major: int | None = None
    maven: str = ""                # "Apache Maven 3.9.6 (...)"
    maven_version: str = ""
    maven_java_major: int | None = None   # the JDK Maven itself runs on
    settings: str = ""
    problems: list[str] = field(default_factory=list)


def probe(cwd: Path, java_home: str | None = None, target: int = 11) -> Toolchain:
    """What the machine will build with. `problems` lists what makes a
    verified migration impossible."""
    import platform
    tc = Toolchain(os=f"{platform.system()} {platform.release()}",
                   java_home=java_home if java_home is not None else config.MIGRATION_JAVA_HOME,
                   settings=config.MAVEN_SETTINGS)
    env = build_env(java_home)
    java = str(Path(tc.java_home) / "bin" / ("java.exe" if _IS_WINDOWS else "java")) if tc.java_home else "java"
    code, out = _run([java, "-version"], cwd, env, 60)
    lines = [l for l in out.splitlines() if "version" in l and "JAVA_TOOL_OPTIONS" not in l]
    tc.java = lines[0].strip() if lines else out.strip()[:200]
    tc.java_major = java_major(tc.java) if code == 0 else None
    if code != 0:
        tc.problems.append(f"`java` could not be run ({tc.java or 'not found'}). Install JDK {target} and set "
                           "MIGRATION_JAVA_HOME to it.")

    mvn = maven_executable(cwd)
    if not mvn:
        tc.problems.append("Maven is not installed (no `mvn` on PATH and no `mvnw` in the project).")
    else:
        code, out = _run([mvn, "-v"], cwd, env, 120)
        first = next((l for l in out.splitlines() if l.startswith("Apache Maven")), "")
        tc.maven = first.strip()
        m = re.search(r"Apache Maven (\S+)", first)
        tc.maven_version = m.group(1) if m else ""
        jv = next((l for l in out.splitlines() if "Java version" in l), "")
        tc.maven_java_major = java_major(jv)
        if code != 0 or not tc.maven_version:
            tc.problems.append(f"`mvn -v` failed: {out.strip()[:300]}")
        elif tc.maven_java_major != target:
            tc.problems.append(
                f"Maven runs on Java {tc.maven_java_major or 'unknown'}, not Java {target}. A Java {target} "
                f"migration can only be verified on a JDK {target}: install one and set MIGRATION_JAVA_HOME "
                f"(Maven uses JAVA_HOME, which can differ from the `java` on PATH).")
        elif _version_tuple(tc.maven_version) < (3, 6, 3):
            tc.problems.append(f"Maven {tc.maven_version} is older than 3.6.3, the oldest that runs current "
                               "plugins reliably on JDK 11 — upgrade Maven (or the project's wrapper).")
    if tc.settings and not Path(tc.settings).is_file():
        tc.problems.append(f"MAVEN_SETTINGS points at `{tc.settings}`, which does not exist.")
    return tc


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", v)[:3])


# ---------------------------------------------------------------------------
# Reading Maven output
# ---------------------------------------------------------------------------

_ENV_PATTERNS = re.compile(
    r"Could not transfer artifact|Could not resolve dependencies|Failed to read artifact descriptor|"
    r"Could not resolve (?:plugin|parent|artifact)|Non-resolvable (?:parent POM|import POM)|"
    r"Plugin \S+ or one of its dependencies could not be resolved|"
    r"status code: 40[13]|Unauthorized|UnknownHostException|Connection refused|Connect timed out|"
    r"PKIX path building failed|unable to find valid certification path|"
    r"was cached in the local repository, resolution will not be reattempted",
    re.IGNORECASE)
_DETAIL = re.compile(r"^(?:dependency:|\S+:\S+:\S+ (?:was not found|was cached)|Could not (?:find|transfer) artifact)")
_COORD = re.compile(r"\b([a-zA-Z][\w.\-]*):([\w.\-]+):(?:(?:jar|pom|war|ear|maven-plugin|test-jar|bundle):)?(?:[\w\-]+:)?(\d[\w.\-]*[\w])")
_COMPILE = re.compile(r"^\[ERROR\]\s+(?P<path>(?:[A-Za-z]:)?[^\s:\[]+\.java):\[(?P<line>\d+),\d+\]\s+(?P<msg>.+)$",
                      re.MULTILINE)
_GENERIC_ERR = re.compile(r"^\[ERROR\]\s+(?!\s*$)(?P<msg>.+)$", re.MULTILINE)
_NOISE = re.compile(r"^(?:->|Re-run Maven|To see the full|For more information|After correcting|"
                    r"\[Help \d\]|Help \d|COMPILATION ERROR|Failed to execute goal .*Compilation failure|"
                    r"Run \d+:|-+$|The build could not read|Problems were encountered|"
                    r"Failed to execute goal org\.apache\.maven\.plugins:maven-surefire)", re.IGNORECASE)


@dataclass
class BuildResult:
    exit_code: int
    timed_out: bool = False
    environment: list[str] = field(default_factory=list)   # resolution / network / credential errors
    compile: list[str] = field(default_factory=list)       # "path:line — message"
    other: list[str] = field(default_factory=list)         # plugin / packaging / anything else
    failing_tests: list[str] = field(default_factory=list) # "Class#method"
    coordinates: list[str] = field(default_factory=list)   # g:a:v named in environment errors
    skipped: list[str] = field(default_factory=list)       # reactor modules not built (a dependency failed)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not (self.environment or self.compile or self.other or self.timed_out)


def _without_test_console(output: str) -> str:
    """Drop surefire/failsafe's console report of test results: tests are read
    from their XML reports (surefire_report), and the console form — "Failures:",
    "Class.method:12 expected…", "<<< FAILURE!" — would otherwise read as build
    errors."""
    out, in_results = [], False
    for line in output.splitlines():
        body = re.sub(r"^\[(?:ERROR|WARNING|INFO)\]\s?", "", line)
        if re.match(r"\s*Results\s*:\s*$", body):
            in_results = True
            continue
        if in_results:
            if re.match(r"\s*Tests run:", body):
                in_results = False
            continue
        if "<<< FAILURE!" in body or "<<< ERROR!" in body or re.match(r"\s*Tests run:", body):
            continue
        out.append(line)
    return "\n".join(out)


def classify(output: str, exit_code: int, root: Path | None = None) -> BuildResult:
    """Split a Maven run's errors into environment, compile and other.
    Test failures are not read from here (see surefire_report)."""
    output = _without_test_console(output)
    res = BuildResult(exit_code=exit_code, timed_out=exit_code == 124 and output.startswith("TIMEOUT"))
    seen: set[str] = set()

    def add(bucket: list[str], text: str) -> None:
        text = text.strip()
        if text and text not in seen:
            seen.add(text)
            bucket.append(text[:400])

    # One pass for compile diagnostics; javac continues one on "symbol:" /
    # "location:" lines, which are folded into it.
    current: list[str] | None = None
    for line in output.splitlines():
        cm = _COMPILE.match(line)
        if cm:
            path = cm.group("path").replace("\\", "/")
            if root is not None:
                try:
                    path = Path(path).resolve().relative_to(root.resolve()).as_posix()
                except (ValueError, OSError):
                    pass
            current = [f"{path}:{cm.group('line')} — {cm.group('msg').strip()}"]
            res.compile.append(current[0])
            continue
        cont = re.match(r"^\[ERROR\]\s+(symbol|location)\s*:\s*(.+)$", line)
        if cont and current is not None:
            current[0] = f"{current[0]} ({cont.group(1)}: {' '.join(cont.group(2).split())})"[:400]
            res.compile[-1] = current[0]
            continue
        current = None
    # Maven prints every compile error twice (the COMPILATION ERROR block and the
    # goal failure); keep one per location and message, the most detailed.
    best: dict[str, str] = {}
    for e in res.compile:
        k = e.split(" (symbol:")[0].split(" (location:")[0]
        if len(e) > len(best.get(k, "")):
            best[k] = e
    res.compile = list(best.values())
    seen.update(res.compile)
    for m in _GENERIC_ERR.finditer(output):
        msg = re.sub(r"^(?:\[ERROR\]\s*)+", "", m.group("msg").strip())
        if (_COMPILE.match(m.group(0)) or _NOISE.match(msg) or msg.startswith("Tests run:")
                or re.match(r"(?:symbol|location)\s*:", msg) or msg.startswith("mvn <args>")
                or msg.startswith("To see the full stack trace") or msg.startswith("After correcting")):
            continue
        if _ENV_PATTERNS.search(msg) or (res.environment and _DETAIL.match(msg)):
            # Detail lines ("dependency: g:a:jar:v", "g:a:jar:v was not found in …")
            # belong to the resolution error above them and name the real artifact.
            if res.environment and _DETAIL.match(msg):
                res.environment[-1] = f"{res.environment[-1]} | {msg}"[:600]
            else:
                add(res.environment, msg)
            for c in _COORD.finditer(re.sub(r"for project \S+", "", msg)):
                coord = f"{c.group(1)}:{c.group(2)}:{c.group(3)}"
                if coord not in res.coordinates:
                    res.coordinates.append(coord)
        elif "There are test failures" in msg or "There were test failures" in msg:
            continue
        else:
            add(res.other, msg)
    if res.compile:
        # "Failed to execute goal ...compiler...: Compilation failure" lines say nothing new.
        res.other = [o for o in res.other if "Compilation failure" not in o and "compiler" not in o.lower()]
    res.skipped = re.findall(r"^\[INFO\]\s+(.+?)\s+\.{2,}\s*SKIPPED", output, flags=re.MULTILINE)
    if res.timed_out:
        res.other.append(output.splitlines()[0])
    return res


def surefire_failures(root: Path) -> list[str]:
    """`Class#method` for every failed or errored test in the surefire and
    failsafe XML reports under `root`."""
    return [name for name, _, _ in surefire_report(root)]


def surefire_report(root: Path) -> list[tuple[str, str, str]]:
    """(`Class#method`, first line of the failure, report path) per failed test."""
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for report in sorted(root.rglob("TEST-*.xml")):
        if not ({"surefire-reports", "failsafe-reports"} & set(report.parts)):
            continue
        try:
            tree = ET.parse(report)
        except (ET.ParseError, OSError):
            continue
        for case in tree.getroot().iter("testcase"):
            problem = case.find("failure") if case.find("failure") is not None else case.find("error")
            if problem is None:
                continue
            name = f"{case.get('classname', '?')}#{case.get('name', '?')}"
            if name in seen:
                continue
            seen.add(name)
            first = (problem.get("message") or problem.get("type") or (problem.text or "").strip()).splitlines()
            detail = f"{problem.get('type', '')}: {first[0] if first else ''}".strip(": ")[:300]
            out.append((name, detail, report.as_posix()))
    return out


def clear_reports(root: Path) -> None:
    for d in list(root.rglob("surefire-reports")) + list(root.rglob("failsafe-reports")):
        if d.is_dir() and "target" in d.parts:
            shutil.rmtree(d, ignore_errors=True)
