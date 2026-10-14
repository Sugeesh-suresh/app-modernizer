"""
"Raise my unit-test coverage" for Gemini CLI.

    environment check (no model): JDK + Maven for the repository's Java level, stack detection, the repository's
        own tests run once under JaCoCo -> the baseline
    HUMAN: coverage target, scope and rounds  (gate `coverage`)
    rounds, until the target is met:
        tester (agent): tests for the classes with the most uncovered code      — writes tests, nothing else
        pipeline (no model): put back anything but new tests, scan the new tests for ones that assert nothing,
            run the whole suite under JaCoCo, run the new tests again for flakiness
        fixer (agent): only when that check finds a problem, up to COVERAGE_FIX_ATTEMPTS times; then the pipeline
            deletes the offending NEW tests itself — an existing test is never touched, a failing test never kept
    HUMAN: when the rounds run out or stop adding coverage (gate `coverage`: accept / more=N / a new target)
    report (no model): before/after per package, what was added, dropped, untestable, remaining gaps

The coverage numbers are the pipeline's: JaCoCo reads them from a build the pipeline runs (agents/shared/
coverage.py), never from what an agent says. Only src/test is writable (agents/test_coverage/tools.py), and the
repository's build files are never edited — the JaCoCo agent travels in JAVA_TOOL_OPTIONS.
"""
from __future__ import annotations

import json
import platform
import re
from pathlib import Path

from agents import config
from agents.java_8_to_11.preflight import maven_roots
from agents.java_8_to_25 import preflight as j25
from agents.shared import coverage, java_env, progress, skill_steps

from . import pipeline as PL
from .runstate import Run, RunError

PATTERN = "test-coverage"
TESTER = "modernizer-tester"
STALL_ROUNDS = 2                        # rounds in a row below COVERAGE_MIN_GAIN that make the run ask


# ═════════════════════════════════════════════════════════════════════════════
# State
# ═════════════════════════════════════════════════════════════════════════════

def init(run: Run) -> None:
    cov = {
        "phase": "preflight", "roots": [], "java_home": "", "packages": [], "stack": {},
        "target": {"line": config.COVERAGE_TARGET_LINE, "branch": config.COVERAGE_TARGET_BRANCH},
        "scope": [], "exclude": [], "max_rounds": config.COVERAGE_MAX_ROUNDS, "target_confirmed": False,
        "round": 0, "fix": 0, "stalled": 0, "verify": False, "pending_fix": "", "batch": [], "round_files": [],
        "baseline": {}, "baseline_failing": [], "current": {}, "history": [], "untestable": {}, "dropped": [],
        "issues": [], "new_tests": [], "reverted": [], "notes": [], "end_reason": "",
    }
    run.state.update({"phase": "preflight", "cov": cov, "pi": 0})


def _cov(run: Run) -> dict:
    return run.state["cov"]


def _results(run: Run, name: str) -> Path:
    return run.result_path(f"{PATTERN}/{name}")


def _save_report(run: Run, name: str, report: coverage.Report) -> None:
    _results(run, name).write_text(json.dumps(report.to_json()), encoding="utf-8")


def _load_report(run: Run, name: str) -> coverage.Report:
    path = _results(run, name)
    return coverage.Report.from_json(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else coverage.Report()


def _set_phase(run: Run, cov: dict, phase: str) -> None:
    cov["phase"] = phase
    run.state["phase"] = phase
    run.save()


def _scope(cov: dict) -> tuple[list[str], list[str]]:
    return cov["scope"], cov["exclude"]


def _totals(run: Run, cov: dict, name: str) -> coverage.Totals:
    return _load_report(run, name).totals(*_scope(cov))


def _pct(t: coverage.Totals) -> str:
    return f"{t.line_pct:.1f}% lines, {t.branch_pct:.1f}% branches"


def status_lines(run: Run) -> list[str]:
    cov = run.state.get("cov")
    if not cov:
        return []
    out = [f"- **Coverage target:** {cov['target']['line']}% lines"
           + (f", {cov['target']['branch']}% branches" if cov["target"]["branch"] else "")
           + (" (not confirmed yet)" if not cov["target_confirmed"] else "")]
    if cov["baseline"]:
        out.append(f"- **Baseline:** {cov['baseline']['line']}% lines, {cov['baseline']['branch']}% branches")
    if cov["history"]:
        h = cov["history"][-1]
        out.append(f"- **Now (round {h['round']}):** {h['line']}% lines, {h['branch']}% branches "
                   f"({len(cov['new_tests'])} new test file(s))")
    return out


# ═════════════════════════════════════════════════════════════════════════════
# next_step / complete_step / confirm
# ═════════════════════════════════════════════════════════════════════════════

def next_step(run: Run) -> tuple[dict, list[str]]:
    log: list[str] = []
    current = run.state.get("current_step")
    if current and current["kind"] == "subagent":
        return current, log
    for _ in range(50):
        step = _PHASES[_cov(run)["phase"]](run, _cov(run), log)
        if step is not None:
            return step, log
    raise RunError("The coverage run did not reach a step — report this as a bug with .modernizer/run.json.")


def complete_step(run: Run, step_id: str) -> str:
    current = run.state.get("current_step") or {}
    if current.get("id") != step_id:
        raise RunError(f"The run is waiting on `{current.get('id', 'nothing')}`, not `{step_id}`. "
                       "Call next_step to see the current step.")
    if current["kind"] != "subagent":
        raise RunError(f"`{step_id}` is a {current['kind']} step — answer it with the command it names.")
    output = run.read_out(step_id)
    if not output.strip():
        raise RunError(f"Nothing was saved for `{step_id}`. The subagent must call save_output with that "
                       "step_id before the step can complete — run it again.")
    cov = _cov(run)
    for name, reason in re.findall(r"^\s*UNTESTABLE:\s*([\w.$]+)\s*[—–-]+\s*(.+?)\s*$", output, re.M):
        cov["untestable"][name] = reason[:300]
    for line in re.findall(r"^\s*PRODUCTION-ISSUE:\s*(.+?)\s*$", output, re.M):
        if line not in cov["issues"]:
            cov["issues"].append(line[:400])
    cov["verify"] = True
    run.state["current_step"] = None
    run.save()
    return ("Tests saved — the pipeline now checks them itself (only test files changed, no test without an "
            "assertion, the whole suite under JaCoCo, the new tests run again).")


def refine(run: Run, gate: str, feedback: str) -> str:
    raise RunError("A coverage run has no document to refine — answer the gate with `confirm`.")


_TOKEN = re.compile(r"^(line|branch|rounds|more|scope|exclude)=(.+)$", re.I)


def _apply(cov: dict, tokens: list[str]) -> list[str]:
    said: list[str] = []
    for raw in tokens:
        token = raw.strip()
        if not token or token.lower() in ("go", "default", "defaults", "ok"):
            continue
        m = _TOKEN.match(token)
        if not m:
            raise RunError(f"`{raw}` is not understood. Use line=NN, branch=NN, rounds=N, scope=<package>, "
                           "exclude=<pattern>, more=N or accept.")
        key, value = m.group(1).lower(), m.group(2).strip()
        if key in ("line", "branch"):
            if not value.isdigit() or not (0 if key == "branch" else 1) <= int(value) <= 100:
                raise RunError(f"{key}= takes a percentage ({'0' if key == 'branch' else '1'}–100).")
            cov["target"][key] = int(value)
            said.append(f"{key} target {value}%")
        elif key in ("rounds", "more"):
            if not value.isdigit() or int(value) < 1:
                raise RunError(f"{key}= takes a whole number of rounds, at least 1.")
            cov["max_rounds"] = int(value) if key == "rounds" else cov["max_rounds"] + int(value)
            said.append(f"up to {cov['max_rounds']} rounds")
        elif key == "scope":
            cov["scope"] = list(dict.fromkeys(cov["scope"] + [value]))
            said.append(f"scope {value}")
        else:
            cov["exclude"] = list(dict.fromkeys(cov["exclude"] + [value]))
            said.append(f"excluding {value}")
    return said


def confirm(run: Run, gate: str, selection: list[str] | None = None, documents: list[str] | None = None) -> str:
    if gate != "coverage":
        raise RunError(f"Unknown gate '{gate}'. This run's gate is: coverage.")
    cov = _cov(run)
    tokens = list(selection or [])
    if cov["phase"] == "target":
        said = _apply(cov, [t for t in tokens if t.strip().lower() != "accept"])
        cov["target_confirmed"] = True
        run.state["plan_approved"] = True          # the tester's workspace tools are open from here on
        run.state["current_step"] = None
        _set_phase(run, cov, "uplift")
        return "Target confirmed" + (": " + ", ".join(said) if said else " (the defaults)") + ". The writer rounds start."
    if cov["phase"] == "hold":
        if any(t.strip().lower() == "accept" for t in tokens):
            cov["end_reason"] = cov["end_reason"] or "accepted by the user"
            run.state["current_step"] = None
            _set_phase(run, cov, "report")
            return "Accepted — the report is written next."
        before = dict(cov["target"])
        said = _apply(cov, tokens)
        if not said:
            raise RunError("Say `accept`, `more=<n>` (more rounds), or a new target such as `line=90`.")
        if cov["target"] != before and cov["round"] >= cov["max_rounds"] and not any(t.lower().startswith(("more=", "rounds=")) for t in tokens):
            cov["max_rounds"] = cov["round"] + config.COVERAGE_MAX_ROUNDS
        cov["stalled"] = 0
        run.state["current_step"] = None
        _set_phase(run, cov, "uplift")
        return "Continuing: " + ", ".join(said) + "."
    raise RunError("No coverage decision is waiting right now.")


# ═════════════════════════════════════════════════════════════════════════════
# Phase: environment check and baseline
# ═════════════════════════════════════════════════════════════════════════════

def _blocked(run: Run, step_id: str, title: str, text: str) -> dict:
    return PL._step(run, step_id, "blocked", title=title, text=text)


def _measure(run: Run, cov: dict, only_tests: list[str] | None = None, with_coverage: bool = True,
             label: str = "") -> coverage.Measurement:
    """The tests of every Maven root of the repository, merged into one measurement."""
    results = []
    for rel in cov["roots"]:
        root = run.workspace / rel if rel not in ("", ".") else run.workspace
        m = coverage.measure(root, cov["java_home"] or None, packages=cov["packages"], only_tests=only_tests,
                             label=label, with_coverage=with_coverage)
        if rel not in ("", "."):
            for c in m.report.classes:
                c.module = f"{rel}/{c.module}".rstrip("/")
        results.append(m)
    if len(results) == 1:
        return results[0]
    merged = coverage.Measurement(ok=all(m.ok for m in results), summary="\n".join(m.summary for m in results),
                                  report=coverage.Report([c for m in results for c in m.report.classes]),
                                  tests=coverage.TestResults(), problem=next((m.problem for m in results if m.problem), ""),
                                  environment=any(m.environment for m in results))
    for m in results:
        merged.tests.total += m.tests.total
        merged.tests.skipped += m.tests.skipped
        merged.tests.failed += [t for t in m.tests.failed if t not in merged.tests.failed]
        merged.tests.reasons.update(m.tests.reasons)
        for k, v in m.tests.by_class.items():
            merged.tests.by_class[k] = merged.tests.by_class.get(k, 0) + v
    return merged


def _phase_preflight(run: Run, cov: dict, log: list[str]) -> dict | None:
    ws = run.workspace
    progress.stage("Coverage: reading the repository's build files and tests")
    stack = coverage.detect_stack(ws)
    cov["stack"] = stack.to_dict()
    cov["packages"] = stack.packages
    if stack.build_tool != "maven":
        return _blocked(run, "coverage-unsupported", "Maven build needed", (
            f"This pipeline measures coverage with Maven and JaCoCo; the repository has "
            f"{'a Gradle build' if stack.build_tool == 'gradle' else 'no Maven build (no pom.xml)'}. Nothing was "
            "changed. Gradle projects are not supported yet."))
    if not stack.frameworks:
        return _blocked(run, "coverage-no-framework", "No test framework in the repository", (
            "No test framework (JUnit, TestNG, Mockito, ...) is declared in the poms or used by an existing test. "
            "This pipeline writes tests with the frameworks the repository already has and never edits a pom — add a "
            "test dependency (for example JUnit and Mockito) to the build yourself, then call next_step again."))
    roots = maven_roots(ws)
    cov["roots"] = [r.relative_to(ws).as_posix() or "." for r in roots]
    release = stack.java_release
    progress.stage(f"Coverage: finding a JDK for Java {release} and Maven")
    pf = j25.Preflight(os=f"{platform.system()} {platform.release()}", settings=config.MAVEN_SETTINGS)
    j25.provision_jdks([release], pf)
    chosen = j25.assign([release], j25.available_jdks()).get(release)
    if not chosen:
        return _blocked(run, "coverage-no-jdk", "No JDK available", (
            f"The repository builds for Java {release}, and no JDK {release} or newer was found"
            + (f" ({'; '.join(pf.notes)})" if pf.notes else "") + f". Install one and name it in MIGRATION_JAVA_HOMES "
            f"(e.g. `{release}=/opt/jdk-{release}`), then call next_step again."))
    cov["java_home"] = chosen["home"]
    run.state["java_home"] = chosen["home"]
    cov["notes"] = list(pf.notes)
    if not chosen["exact"]:
        cov["notes"].append(f"No JDK {release}: the tests run on JDK {chosen['major']} ({chosen['source']}).")
    mvn = java_env.maven_executable(roots[0])
    mvn = j25.provision_maven(mvn, roots[0], pf) or mvn
    cov["notes"] = list(dict.fromkeys(cov["notes"] + pf.notes))
    if not mvn:
        return _blocked(run, "coverage-no-maven", "Maven not found", (
            "Maven is not installed (no `mvn` on PATH, no `mvnw` in the project)"
            + ("" if config.AUTO_INSTALL_TOOLS else " and AUTO_INSTALL_TOOLS is off") + ". Install it and call next_step again."))

    m = _measure(run, cov, label=f"Coverage: baseline — the repository's own tests under JaCoCo on JDK {chosen['major']} "
                                  "(a first build downloads every dependency)")
    if not m.ok:
        return _blocked(run, "coverage-baseline-failed", "The baseline run failed", (
            f"The repository's own tests could not be run under JaCoCo before any change: {m.problem}\n\n{m.summary}\n\n"
            + ("Fix the build environment (repository credentials / mirrors in settings.xml — MAVEN_SETTINGS —, network "
               "or proxy) " if m.environment else "Fix the build (it must compile, tests included) ")
            + "and call next_step again; nothing was changed."))
    cov["baseline_failing"] = list(m.tests.failed)
    _save_report(run, "baseline.json", m.report)
    _save_report(run, "current.json", m.report)
    t = m.report.totals(*_scope(cov))
    cov["baseline"] = {"line": t.line_pct, "branch": t.branch_pct, "tests": m.tests.total, "failing": len(m.tests.failed)}
    cov["current"] = dict(cov["baseline"])
    log.append(f"Baseline: {_pct(t)} over {t.classes} source file(s); {m.tests.total} existing test(s), "
               f"{len(m.tests.failed)} failing.")
    _set_phase(run, cov, "target")
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Phase: the target gate
# ═════════════════════════════════════════════════════════════════════════════

def _package_table(report: coverage.Report, scope, exclude, limit: int = 12) -> str:
    rows = sorted(report.by_package(scope, exclude).items(), key=lambda kv: -kv[1].lines_missed)[:limit]
    lines = ["| Package | Lines | Branches | Uncovered lines |", "|---|---|---|---|"]
    lines += [f"| `{p}` | {t.line_pct:.1f}% | {t.branch_pct:.1f}% | {t.lines_missed} |" for p, t in rows]
    return "\n".join(lines)


def _phase_target(run: Run, cov: dict, log: list[str]) -> dict | None:
    if cov["target_confirmed"]:
        _set_phase(run, cov, "uplift")
        return None
    report = _load_report(run, "baseline.json")
    t = report.totals(*_scope(cov))
    stack = cov["stack"]
    gaps = coverage.rank_gaps(report)[:8]
    notes = list(cov["notes"])
    if stack["jsp_files"]:
        notes.append(f"{stack['jsp_files']} JSP file(s) are not unit-testable and JaCoCo does not measure them; the "
                     "servlets, beans and tag classes behind them are what this run covers.")
    if cov["baseline_failing"]:
        notes.append(f"{len(cov['baseline_failing'])} existing test(s) already fail before any change "
                     f"({', '.join(cov['baseline_failing'][:3])}{' …' if len(cov['baseline_failing']) > 3 else ''}); "
                     "they are left as they are and never count against the new tests.")
    versions = ", ".join(f"{k} {v}" for k, v in stack["versions"].items())
    text = (
        f"Baseline coverage of this repository: **{_pct(t)}** ({t.classes} source files, "
        f"{cov['baseline']['tests']} existing tests).\n\n"
        f"Tests are written with what the repository already has: {', '.join(stack['frameworks']) or 'n/a'}"
        f"{' (' + versions + ')' if versions else ''}; Java {stack['java_release']}.\n\n"
        f"{_package_table(report, *_scope(cov))}\n\n"
        "Biggest gaps: " + (", ".join(f"`{c.name}` ({c.lines_missed} uncovered lines)" for c in gaps) or "none") + ".\n\n"
        + ("\n".join(f"- {n}" for n in notes) + "\n\n" if notes else "")
        + f"Defaults: **line coverage {cov['target']['line']}%**"
        + (f", branch {cov['target']['branch']}%" if cov["target"]["branch"] else "")
        + f", at most {cov['max_rounds']} writer rounds of {config.COVERAGE_BATCH_CLASSES} classes each. Each round "
        "writes tests, runs the whole suite under JaCoCo and keeps only tests that pass, are stable and assert "
        "something; only `src/test` is ever written.\n\n"
        "Ask the user for the target they want (and optionally a scope, exclusions or a round limit), show them these "
        "numbers, then call `confirm` with gate=`coverage` and `selection` = a list such as "
        "[\"line=85\", \"branch=70\", \"rounds=8\", \"scope=com.acme.service\", \"exclude=*Dto\"] — an empty list takes "
        "the defaults. Never confirm for the user.")
    return PL._step(run, "coverage-target", "ask_user", title="Choose the coverage target", text=text)


# ═════════════════════════════════════════════════════════════════════════════
# Phase: the rounds
# ═════════════════════════════════════════════════════════════════════════════

def _source_path(c: coverage.ClassCov) -> str:
    return "/".join(p for p in (c.module, "src/main/java", c.package.replace(".", "/"), c.source) if p)


def _test_dir(c: coverage.ClassCov) -> str:
    return "/".join(p for p in (c.module, "src/test/java", c.package.replace(".", "/")) if p)


def _existing_tests_for(run: Run, c: coverage.ClassCov) -> list[str]:
    stem = c.source[:-5]
    folder = run.workspace / _test_dir(c)
    if not folder.is_dir():
        return []
    return sorted(f.relative_to(run.workspace).as_posix() for f in folder.glob("*.java")
                  if f.name.startswith(stem) or f.name.startswith("Test" + stem))


def _new_test_name(run: Run, c: coverage.ClassCov) -> str:
    stem = c.source[:-5]
    taken = {f.name for f in (run.workspace / _test_dir(c)).glob("*.java")} if (run.workspace / _test_dir(c)).is_dir() else set()
    for suffix in ("Test", "BranchTest", "BehaviourTest", "MoreTest"):
        if f"{stem}{suffix}.java" not in taken:
            return f"{stem}{suffix}"
    return f"{stem}Extra{len(taken)}Test"


def _round_query(run: Run, cov: dict, batch: list[coverage.ClassCov], n: int) -> str:
    stack = cov["stack"]
    cur = cov["history"][-1] if cov["history"] else {"line": cov["baseline"]["line"], "branch": cov["baseline"]["branch"]}
    module_hint = " Pass `subdir` = the module folder when the class is not in the repository root." \
        if any(stack["modules"]) else ""
    lines = [skill_steps.cli_instruction("test-coverage:write-tests"), "",
             "## This run",
             f"- Round {n} of at most {cov['max_rounds']}. Line coverage is {cur['line']}% now, the target is "
             f"{cov['target']['line']}%" + (f", branches {cov['target']['branch']}%" if cov["target"]["branch"] else "") + ".",
             f"- The repository tests with: {', '.join(stack['frameworks'])}"
             + (f" ({', '.join(f'{k} {v}' for k, v in stack['versions'].items())})" if stack["versions"] else "")
             + f"; Java {stack['java_release']}. Use only these — never add a dependency or edit a build file.",
             f"- Style sample (an existing test): `{stack['sample'] or 'none — the repository has no test to imitate'}`. "
             "Read it first and match its naming, structure and assertions.",
             "- Check your tests with `mcp_modernizer_ws_run_command`: `mvn -q -B test -Dtest=<NewTestClass>`."
             + module_hint + " The pipeline measures coverage itself; do not report numbers.",
             "- Write only new files under `src/test/java` (or `src/test/resources`). Existing tests are frozen: a "
             "write to one is refused.", "", f"## Classes to cover ({len(batch)})"]
    for c in batch:
        lines += ["", f"### `{c.name}` — `{_source_path(c)}`",
                  f"- Lines covered {c.lines_covered}/{c.lines}; branches {c.branches_covered}/{c.branches}; "
                  f"methods {c.methods_covered}/{c.methods_covered + c.methods_missed}.",
                  f"- Uncovered lines: {coverage.ranges(c.missed) or 'none'}"
                  + (f"; lines with an untaken branch: {coverage.ranges(c.partial)}" if c.partial else "") + ".",
                  f"- New test class: `{_test_dir(c)}/{_new_test_name(run, c)}.java`"
                  + (f"; existing tests for it (read, do not edit): {', '.join(f'`{t}`' for t in _existing_tests_for(run, c))}"
                     if _existing_tests_for(run, c) else "") + "."]
    if cov["untestable"]:
        lines += ["", "## Reported untestable earlier (skip these)"] + [f"- `{k}` — {v}" for k, v in list(cov["untestable"].items())[:20]]
    if run.state.get("requirements"):
        lines += ["", "## What the person asked for", run.state["requirements"],
                  "", "Treat it as a priority for which behaviour to test; the rules above still hold."]
    return "\n".join(lines) + PL._output_rule(f"tests-round-{n}", "report (the `write-tests` step's format)")


def _phase_uplift(run: Run, cov: dict, log: list[str]) -> dict | None:
    if cov["verify"]:
        cov["verify"] = False
        run.save()
        return _verify(run, cov, log)
    if cov["pending_fix"]:
        return _fix_step(run, cov)
    n = cov["round"] + 1
    report = _load_report(run, "current.json")
    gaps = coverage.rank_gaps(report, *_scope(cov), skip=set(cov["untestable"]))
    if _met(cov, report):
        cov["end_reason"] = "the target was reached"
        _set_phase(run, cov, "report")
        return None
    if not gaps:
        cov["end_reason"] = "no class with enough uncovered code is left that a writer has not reported untestable"
        _set_phase(run, cov, "report")
        return None
    batch = coverage.pick_batch(gaps)
    cov.update({"round": n, "fix": 0, "batch": [c.name for c in batch], "round_files": []})
    _results(run, f"round-{n}-before.json").write_text(json.dumps(coverage.digests(run.workspace)), encoding="utf-8")
    run.save()
    return PL._sub(run, f"tests-round-{n}", TESTER, _round_query(run, cov, batch, n),
                   f"Write tests — round {n} ({len(batch)} class(es))", "tests", pattern=PATTERN)


def _met(cov: dict, report: coverage.Report) -> bool:
    t = report.totals(*_scope(cov))
    return t.line_pct >= cov["target"]["line"] and (not cov["target"]["branch"] or t.branch_pct >= cov["target"]["branch"])


def _fqcn(rel: str) -> str:
    m = re.search(r"src/test/java/(.+)\.java$", rel)
    return m.group(1).replace("/", ".") if m else ""


def _round_problems(run: Run, cov: dict, m: coverage.Measurement, files: list[str]) -> list[dict]:
    """What is wrong with this round's tests, as [{kind, files, text}] (files [] = cannot tell which)."""
    problems: list[dict] = []
    ws = run.workspace
    by_fqcn = {_fqcn(f): f for f in files}
    for rel in files:
        scan = coverage.scan_tests(ws / rel, rel)
        if scan.disabled:
            problems.append({"kind": "disabled", "files": [rel], "text": f"`{rel}` contains @Ignore/@Disabled — a test that does not run is not a test; remove it."})
        if scan.weak:
            problems.append({"kind": "weak", "files": [rel], "text": f"`{rel}`: " + "; ".join(scan.weak[:6])})
    if not m.ok:
        problems.append({"kind": "build", "files": [], "text": f"The build/tests did not compile or run: {m.problem}\n{m.summary}"})
        return problems
    failing = [t for t in m.tests.failed if t not in cov["baseline_failing"]]
    for name in failing:
        cls = name.split("#")[0]
        mine = by_fqcn.get(cls) or next((f for k, f in by_fqcn.items() if k.endswith("." + cls) or cls.endswith("." + k)), "")
        reason = m.tests.reasons.get(name, "")
        problems.append({"kind": "failing" if mine else "regression", "files": [mine] if mine else [],
                         "text": f"`{name}` failed: {reason}" + ("" if mine else " (an EXISTING test failed after this round's tests were added — "
                                                                  "look for shared static state, a mock of a shared class or test-order dependence in the new tests)")})
    return problems


def _verify(run: Run, cov: dict, log: list[str]) -> dict | None:
    ws, base = run.workspace, Path(run.state["baseline_dir"])
    n = cov["round"]
    progress.stage(f"Round {n}: checking the tests the writer produced")
    before = json.loads(_results(run, f"round-{n}-before.json").read_text(encoding="utf-8"))
    audit = coverage.audit_round(ws, base, before)
    if audit["reverted"]:
        cov["reverted"] += audit["reverted"]
        log.append(f"Round {n}: put back {len(audit['reverted'])} file(s) that are not new tests: "
                   + ", ".join(audit["reverted"][:5]))
    cov["new_tests"] = sorted({f for f in cov["new_tests"] + audit["new_tests"] if (ws / f).is_file()})
    files = sorted({f for f in audit["new_tests"] + audit["touched_tests"] if (ws / f).is_file()} | set(cov["round_files"]))
    cov["round_files"] = [f for f in files if (ws / f).is_file()]
    for attempt in range(3):
        m = _measure(run, cov, label=f"Round {n}: the whole suite under JaCoCo with the new tests"
                                     + (f" (after removing flawed tests, pass {attempt + 1})" if attempt else ""))
        problems = _round_problems(run, cov, m, cov["round_files"])
        if not problems and config.COVERAGE_FLAKE_CHECK and cov["round_files"]:
            names = sorted({Path(f).stem for f in cov["round_files"]})
            again = _measure(run, cov, only_tests=names, with_coverage=False,
                             label=f"Round {n}: running the {len(names)} new test class(es) again to catch flaky tests")
            flaky = [t for t in again.tests.failed if t not in cov["baseline_failing"]]
            if not again.ok or flaky:
                by_fqcn = {_fqcn(f): f for f in cov["round_files"]}
                for name in flaky or ["(the second run)"]:
                    mine = by_fqcn.get(name.split("#")[0], "")
                    problems.append({"kind": "flaky", "files": [mine] if mine else [], "text":
                                     f"`{name}` passed once and failed on a second run — flaky (order, time, shared state): "
                                     + (again.tests.reasons.get(name, again.problem or ""))})
        if not problems:
            return _finish_round(run, cov, m, log)
        if attempt == 0 and cov["fix"] < config.COVERAGE_FIX_ATTEMPTS:
            cov["fix"] += 1
            cov["pending_fix"] = _fix_report(run, cov, problems)
            run.save()
            return _fix_step(run, cov)
        _rollback(run, cov, problems)         # the fixer had its chances (or this is the second look): remove what is flawed
    return _blocked(run, "coverage-broken", "The tests could not be made clean", (
        "After removing the flawed new tests the suite still does not run cleanly: "
        + "; ".join(p["text"] for p in problems[:3]) + ". Look at the workspace (the baseline is untouched in "
        f"`{run.state['baseline_dir']}`), fix it, and call next_step again."))


def _fix_report(run: Run, cov: dict, problems: list[dict]) -> str:
    return "\n".join(f"- **{p['kind']}** — {p['text']}" for p in problems)


def _fix_step(run: Run, cov: dict) -> dict:
    n, k = cov["round"], cov["fix"]
    report, cov["pending_fix"] = cov["pending_fix"], ""
    run.save()
    files = "\n".join(f"- `{f}`" for f in cov["round_files"]) or "- (none)"
    q = (skill_steps.cli_instruction("test-coverage:fix-tests") + "\n\n## What the pipeline found\n" + report +
         f"\n\n## This round's new test files (the only files you may edit or delete)\n{files}\n\n"
         "Existing tests and production code are frozen. Re-run the tests you fix with `mcp_modernizer_ws_run_command` "
         "(`mvn -q -B test -Dtest=<Class>`). A test you cannot make pass, stable and meaningful is deleted, not skipped. "
         f"This is repair pass {k} of at most {config.COVERAGE_FIX_ATTEMPTS}; after the last one the pipeline deletes "
         "what is still flawed itself." + PL._output_rule(f"fix-tests-{n}-{k}", "report (the `fix-tests` step's format)"))
    return PL._sub(run, f"fix-tests-{n}-{k}", TESTER, q, f"Repair the new tests — round {n}, pass {k}", "fix", pattern=PATTERN)


def _rollback(run: Run, cov: dict, problems: list[dict]) -> None:
    """Delete this round's flawed new tests: the files named by the problems, or — when a problem cannot be tied to
    a file (a build that does not compile, an existing test that failed) — all the round's new files."""
    ws = run.workspace
    named = {f for p in problems for f in p["files"]}
    everything = any(not p["files"] for p in problems)
    gone = list(cov["round_files"]) if everything or not named else sorted(named)
    base = Path(run.state["baseline_dir"])
    for rel in gone:
        if (base / rel).is_file():                       # never delete an existing test
            continue
        (ws / rel).unlink(missing_ok=True)
        why = next((p["text"] for p in problems if rel in p["files"] or not p["files"]), "flawed")
        cov["dropped"].append({"file": rel, "round": cov["round"], "reason": why[:300]})
    cov["new_tests"] = [f for f in cov["new_tests"] if (ws / f).is_file()]
    cov["round_files"] = [f for f in cov["round_files"] if (ws / f).is_file()]


def _finish_round(run: Run, cov: dict, m: coverage.Measurement, log: list[str]) -> dict | None:
    n = cov["round"]
    _save_report(run, "current.json", m.report)
    t = m.report.totals(*_scope(cov))
    prev = cov["history"][-1]["line"] if cov["history"] else cov["baseline"]["line"]
    added = sum(m.tests.by_class.get(_fqcn(f), 0) for f in cov["round_files"])
    row = {"round": n, "line": t.line_pct, "branch": t.branch_pct, "gain": round(t.line_pct - prev, 1), "tests": added,
           "files": list(cov["round_files"]), "batch": list(cov["batch"])}
    cov["history"].append(row)
    cov["current"] = {"line": t.line_pct, "branch": t.branch_pct, "tests": m.tests.total}
    cov["stalled"] = cov["stalled"] + 1 if (row["gain"] < config.COVERAGE_MIN_GAIN or not added) else 0
    log.append(f"Round {n}: {added} new test(s) in {len(cov['round_files'])} file(s); coverage {prev}% -> {t.line_pct}% lines "
               f"({t.branch_pct}% branches).")
    cov["pending_fix"], cov["round_files"], cov["fix"] = "", [], 0
    if _met(cov, m.report):
        cov["end_reason"] = "the target was reached"
        _set_phase(run, cov, "report")
    elif cov["round"] >= cov["max_rounds"] or cov["stalled"] >= STALL_ROUNDS:
        _set_phase(run, cov, "hold")
    else:
        run.save()
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Phase: the stalled gate, the report, done
# ═════════════════════════════════════════════════════════════════════════════

def _history_table(cov: dict) -> str:
    lines = ["| Round | Lines | Branches | Gain | New tests |", "|---|---|---|---|---|",
             f"| baseline | {cov['baseline']['line']}% | {cov['baseline']['branch']}% | | |"]
    lines += [f"| {h['round']} | {h['line']}% | {h['branch']}% | {h['gain']:+.1f} | {h['tests']} |" for h in cov["history"]]
    return "\n".join(lines)


def _phase_hold(run: Run, cov: dict, log: list[str]) -> dict | None:
    report = _load_report(run, "current.json")
    t = report.totals(*_scope(cov))
    why = (f"all {cov['max_rounds']} rounds were used" if cov["round"] >= cov["max_rounds"]
           else f"the last {cov['stalled']} rounds each added less than {config.COVERAGE_MIN_GAIN} point(s)")
    gaps = coverage.rank_gaps(report, *_scope(cov), skip=set(cov["untestable"]))[:6]
    text = (f"The target ({cov['target']['line']}% lines"
            + (f", {cov['target']['branch']}% branches" if cov["target"]["branch"] else "")
            + f") is not reached and {why}. Coverage is now **{_pct(t)}**.\n\n{_history_table(cov)}\n\n"
            + ("Reported untestable without changing production code:\n"
               + "\n".join(f"- `{k}` — {v}" for k, v in list(cov["untestable"].items())[:8]) + "\n\n" if cov["untestable"] else "")
            + ("Largest gaps left: " + ", ".join(f"`{c.name}` ({c.lines_missed})" for c in gaps) + ".\n\n" if gaps else "")
            + "Ask the user what to do, then call `confirm` with gate=`coverage` and `selection` = one of: "
              "[\"accept\"] (finish with the report), [\"more=3\"] (three more rounds), or a new target such as "
              "[\"line=70\"]. Never choose for the user.")
    return PL._step(run, "coverage-stalled", "ask_user", title="Coverage stopped short of the target", text=text)


def _report(run: Run, cov: dict) -> str:
    base, now = _load_report(run, "baseline.json"), _load_report(run, "current.json")
    scope = _scope(cov)
    tb, tn = base.totals(*scope), now.totals(*scope)
    out = [f"# Test coverage report", "",
           f"**Result:** {cov['end_reason'] or 'finished'}. Line coverage {tb.line_pct}% → **{tn.line_pct}%**, "
           f"branch coverage {tb.branch_pct}% → **{tn.branch_pct}%** "
           f"(target {cov['target']['line']}% lines"
           + (f", {cov['target']['branch']}% branches" if cov["target"]["branch"] else "") + ").", "",
           f"- Rounds run: {cov['round']}; new test files kept: {len(cov['new_tests'])}; "
           f"new tests: {sum(h['tests'] for h in cov['history'])}; dropped: {len(cov['dropped'])}.",
           f"- Measured with JaCoCo on the repository's own build, tests: {', '.join(cov['stack'].get('frameworks', []))}.",
           f"- Scope: {', '.join(cov['scope']) or 'all production code'}"
           + (f"; excluded: {', '.join(cov['exclude'])}" if cov["exclude"] else "") + ".", "",
           "## Coverage by round", "", _history_table(cov), "", "## Coverage by package", "",
           "| Package | Lines before | Lines after | Branches before | Branches after |", "|---|---|---|---|---|"]
    before, after = base.by_package(*scope), now.by_package(*scope)
    for pkg in sorted(set(before) | set(after)):
        b, a = before.get(pkg, coverage.Totals()), after.get(pkg, coverage.Totals())
        out.append(f"| `{pkg}` | {b.line_pct}% | {a.line_pct}% | {b.branch_pct}% | {a.branch_pct}% |")
    out += ["", "## Tests added", ""]
    out += [f"- `{f}`" for f in cov["new_tests"]] or ["- none"]
    if cov["dropped"]:
        out += ["", "## New tests dropped (never kept: failing, flaky or asserting nothing)", ""]
        out += [f"- `{d['file']}` (round {d['round']}) — {d['reason']}" for d in cov["dropped"]]
    if cov["untestable"]:
        out += ["", "## Reported untestable without changing production code", ""]
        out += [f"- `{k}` — {v}" for k, v in cov["untestable"].items()]
    if cov["issues"]:
        out += ["", "## Possible production issues found while writing tests", ""] + [f"- {i}" for i in cov["issues"]]
    if cov["reverted"]:
        out += ["", "## Files a writer changed that were put back", ""] + [f"- `{f}`" for f in sorted(set(cov["reverted"]))]
    if cov["baseline_failing"]:
        out += ["", "## Tests that already failed before the run (left as they were)", ""] + [f"- `{t}`" for t in cov["baseline_failing"]]
    gaps = coverage.rank_gaps(now, *scope, include_trivial=True)[:15]
    out += ["", "## Largest gaps left", "", "| Class | Uncovered lines | Uncovered branches |", "|---|---|---|"]
    out += [f"| `{c.name}` | {c.lines_missed} | {c.branches_missed} |" for c in gaps] or ["| none | | |"]
    if cov["stack"].get("jsp_files"):
        out += ["", f"_{cov['stack']['jsp_files']} JSP file(s) are not measured: JaCoCo instruments Java classes only._"]
    out += ["", "## Measure it yourself", "",
            "`mvn -B test` with the JaCoCo agent, for example "
            f"`mvn -B org.jacoco:jacoco-maven-plugin:{coverage.jacoco_version(None)}:prepare-agent test "
            f"org.jacoco:jacoco-maven-plugin:{coverage.jacoco_version(None)}:report` "
            "(add `@{argLine}` to a Surefire `<argLine>` that is written out in the pom, or the agent is not attached)."]
    return "\n".join(out) + "\n"


def _phase_report(run: Run, cov: dict, log: list[str]) -> dict | None:
    progress.stage("Finishing: the coverage report and the list of changed files")
    text = _report(run, cov)
    path = _results(run, "coverage_report.md")
    path.write_text(text, encoding="utf-8")
    run.write_doc("coverage_report", text, PATTERN)
    PL._phase_finish(run, log)                 # changes.md / changes.patch against the baseline
    cov["phase"] = "done"
    run.state["phase"] = "done"
    run.save()
    return None


def _phase_done(run: Run, cov: dict, log: list[str]) -> dict:
    b, c = cov["baseline"], cov["current"]
    return PL._step(run, "done", "done", title="Coverage run complete", text=(
        f"The run is complete: line coverage {b['line']}% → {c['line']}%, branch coverage {b['branch']}% → "
        f"{c['branch']}% ({cov['end_reason'] or 'finished'}). {len(cov['new_tests'])} new test file(s) were added "
        f"under src/test — no production code was changed.\n\n- Report: `{run.rel(_results(run, 'coverage_report.md'))}`\n"
        f"- Changed files: `.modernizer/results/changes.md` (diff: `.modernizer/results/changes.patch`)\n\n"
        "Review the new tests with git before committing."))


_PHASES = {
    "preflight": _phase_preflight, "target": _phase_target, "uplift": _phase_uplift, "hold": _phase_hold,
    "report": _phase_report, "done": _phase_done,
}
