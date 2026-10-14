"""
A few lines on how a build went, for whoever is watching it.

A Maven build prints thousands of lines; the person (and the next agent) needs the verdict: did it pass, which
modules, how many compile errors and where, which tests failed, whether it was the network. `summarize()` reads a
finished build's output and returns a `Summary`; `Summary.text()` is the block shown in the terminal — in the
`next_step` answer for the preflight's builds, and after every `run_command` build a subagent runs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_RESULT = re.compile(r"^\[INFO\] BUILD (SUCCESS|FAILURE)", re.M)
_GRADLE = re.compile(r"^BUILD (SUCCESSFUL|FAILED)", re.M)
_TIME = re.compile(r"^\[INFO\] Total time:\s+(.+?)\s*$", re.M)
_MODULE = re.compile(r"^\[(?:INFO|ERROR|WARNING)\] (.+?) \.{2,} (SUCCESS|FAILURE|SKIPPED)(?: \[\s*(.+?)\s*\])?\s*$", re.M)
_COMPILE_ERROR = re.compile(r"^\[ERROR\] (?:COMPILATION ERROR :)?.*?(/?[^\s\[]+\.java):\[(\d+),(\d+)\]\s*(.*)$", re.M)
_TESTS = re.compile(r"^\[(?:INFO|WARNING|ERROR)\] Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)\s*$", re.M)
_FAILED_TEST = re.compile(r"^\[ERROR\]\s{1,4}([\w.$]+(?:[#.][\w$]+)?(?:\([^)]*\))?)(?::\d+)?\s", re.M)
_GOAL = re.compile(r"Failed to execute goal ([\w.:-]+)")
_OFFLINE = re.compile(r"Could not (?:resolve dependencies|transfer artifact|find artifact)|Non-resolvable (?:parent|import)|"
                      r"Connection (?:timed out|refused|reset)|Unknown host|PKIX path|401 Unauthorized|status: 40[137]")
_CRED = re.compile(r"(://)[^/@\s:]+:[^/@\s]+@")


@dataclass
class Summary:
    tool: str = "maven"
    passed: bool | None = None            # None: the output does not say (no BUILD line: killed, timed out)
    exit_code: int | None = None
    duration: str = ""
    modules: list[tuple[str, str, str]] = field(default_factory=list)      # (name, status, time)
    compile_errors: list[tuple[str, int, str]] = field(default_factory=list)   # (file, line, message)
    compile_error_count: int = 0
    tests: tuple[int, int, int, int] | None = None                         # run, failures, errors, skipped
    failed_tests: list[str] = field(default_factory=list)
    failed_goal: str = ""
    network: bool = False

    @property
    def headline(self) -> str:
        state = {True: "PASSED", False: "FAILED", None: "NO VERDICT"}[self.passed]
        bits = [f"{self.tool} build {state}"]
        if self.duration:
            bits.append(self.duration)
        if self.modules:
            ok = sum(1 for _, s, _ in self.modules if s == "SUCCESS")
            bits.append(f"{ok}/{len(self.modules)} modules OK")
        if self.compile_error_count:
            bits.append(f"{self.compile_error_count} compile error(s)")
        if self.tests:
            r, f, e, s = self.tests
            bits.append(f"tests {r} run, {f} failed, {e} errors, {s} skipped")
        return " — ".join(bits[:1]) + (" (" + ", ".join(bits[1:]) + ")" if bits[1:] else "")

    def text(self, limit: int = 5) -> str:
        lines = [f"Build summary: {self.headline}"]
        bad = [(n, s) for n, s, _ in self.modules if s != "SUCCESS"]
        if bad:
            lines.append("  Modules: " + "; ".join(f"{n} {s}" for n, s in bad[:limit]) + (" …" if len(bad) > limit else ""))
        for path, line, msg in self.compile_errors[:limit]:
            lines.append(f"  Compile: {path.rsplit('/', 1)[-1]}:{line} {msg}".rstrip())
        if self.compile_error_count > limit:
            lines.append(f"  … {self.compile_error_count - limit} more compile error(s)")
        if self.failed_tests:
            lines.append("  Failing tests: " + ", ".join(self.failed_tests[:limit]) + (" …" if len(self.failed_tests) > limit else ""))
        if self.passed is False and self.network and not self.compile_error_count:
            lines.append("  Cause: dependencies could not be downloaded (repository credentials, mirror, network or proxy)"
                         " — not a code problem.")
        elif self.passed is False and self.failed_goal and not self.compile_error_count and not self.failed_tests:
            lines.append(f"  Failed goal: {self.failed_goal}")
        if self.passed is None:
            lines.append("  The output has no BUILD result — the build was cut off or timed out, so nothing can be inferred.")
        return "\n".join(lines)


def summarize(output: str, exit_code: int | None = None, tool: str = "") -> Summary:
    out = output or ""
    gradle = tool.startswith("gradle") or (not _RESULT.search(out) and _GRADLE.search(out) is not None)
    s = Summary(tool="gradle" if gradle else "maven", exit_code=exit_code)
    if gradle:
        m = _GRADLE.search(out)
        s.passed = None if not m else m.group(1) == "SUCCESSFUL"
        if m and (t := re.search(r"BUILD (?:SUCCESSFUL|FAILED) in (.+)", out)):
            s.duration = t.group(1).strip()
    else:
        results = _RESULT.findall(out)
        s.passed = None if not results else results[-1] == "SUCCESS"
        if (t := _TIME.findall(out)):
            s.duration = t[-1]
    if s.passed is None and exit_code is not None and not out.startswith("TIMEOUT") and exit_code != 124:
        s.passed = exit_code == 0        # a quiet build (`mvn -q`) prints no BUILD line: its exit code is the verdict
    seen = set()
    for name, status, took in _MODULE.findall(out):
        if name not in seen and not name.startswith("Reactor"):
            seen.add(name)
            s.modules.append((name.strip(), status, took))
    errors = []
    for path, line, _col, msg in _COMPILE_ERROR.findall(out):
        if (path, line) not in {(e[0], e[1]) for e in errors}:
            errors.append((path, int(line), msg.strip()[:140]))
    s.compile_errors, s.compile_error_count = errors[:20], len(errors)
    totals = _TESTS.findall(out)
    if totals:
        s.tests = tuple(int(x) for x in totals[-1])                     # type: ignore[assignment]
        if s.tests[1] or s.tests[2]:
            s.failed_tests = list(dict.fromkeys(_FAILED_TEST.findall(out.split("Failures:", 1)[-1] if "Failures:" in out else out)))[:20]
    if (g := _GOAL.search(out)):
        s.failed_goal = g.group(1)
    s.network = bool(_OFFLINE.search(out))
    return s


def redact(text: str) -> str:
    return _CRED.sub(r"\1***@", text)
