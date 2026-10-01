"""
Preflight for the Java 8 -> 11 run, before anything is planned.

1. Toolchain: the JDK Maven runs on must be 11, Maven 3.6.3+, the settings
   file (if configured) must exist.
2. Baseline tests (only with BASELINE_JAVA_HOME, a JDK 8): the uploaded code's
   test suite on the JDK it was written for. Tests failing here predate the
   migration; validation reports them but never asks the fixer to change them.
3. Baseline build on JDK 11: `clean package` (tests compiled, not run) of the
   code exactly as uploaded. Two outcomes matter:
   - dependency resolution / repository / credential errors: the environment
     cannot build this project at all. The run stops here, before planning,
     with what to fix — a migration could not be verified, and the fixer would
     try to repair the environment in the code.
   - compile and plugin errors: precisely what Java 11 breaks in this code.
     They go to the planner as the primary work list (compile-first), instead
     of a list predicted from versions.
"""
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import config
from ..shared import java_env
from ..shared.dependency_graph import EXCLUDED_DIRS

TARGET = 11
_MAX_LISTED = 300


@dataclass
class Preflight:
    ok: bool = True
    stop_reason: str = ""
    toolchain: dict = field(default_factory=dict)
    roots: list[str] = field(default_factory=list)
    build_tool: str = "maven"
    baseline_tests_run: bool = False
    baseline_test_jdk: int | None = None
    baseline_failing_tests: list[str] = field(default_factory=list)
    baseline_build_ok: bool | None = None
    compile_errors: list[str] = field(default_factory=list)
    other_errors: list[str] = field(default_factory=list)
    environment_errors: list[str] = field(default_factory=list)
    skipped_modules: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def maven_roots(workspace: Path) -> list[Path]:
    """Directories to build from: every pom.xml with no pom.xml in an ancestor
    directory (the aggregators — usually one, under the upload's top folder)."""
    poms = sorted((p for p in workspace.rglob("pom.xml") if not (EXCLUDED_DIRS & set(p.relative_to(workspace).parts))),
                  key=lambda p: len(p.parts))
    roots: list[Path] = []
    for pom in poms:
        if not any(r in pom.parents for r in roots):
            roots.append(pom.parent)
    return roots


def _merge(pf: Preflight, res: java_env.BuildResult, root: str, coords: list[str]) -> None:
    prefix = "" if root in ("", ".") else f"{root}/"
    pf.compile_errors += [e if e.startswith(prefix) else prefix + e for e in res.compile]
    pf.other_errors += res.other
    pf.environment_errors += res.environment
    pf.skipped_modules += res.skipped
    coords += [c for c in res.coordinates if c not in coords]


def run(workspace_dir: str) -> Preflight:
    workspace = Path(workspace_dir)
    pf = Preflight()
    roots = maven_roots(workspace)
    pf.roots = [r.relative_to(workspace).as_posix() or "." for r in roots]
    gradle = any(workspace.rglob("build.gradle")) or any(workspace.rglob("build.gradle.kts"))
    if not roots:
        pf.build_tool = "gradle" if gradle else "none"

    tc = java_env.probe(roots[0] if roots else workspace, target=TARGET)
    pf.toolchain = asdict(tc)
    if not roots:
        pf.notes.append("No Maven build in the repository — only the toolchain was checked"
                        + (" (Gradle builds are validated by the build loop)." if gradle else "."))
        # Without Maven, only the JDK matters.
        jdk_problems = [p for p in tc.problems if "Maven" not in p and "mvn" not in p]
        if tc.java_major != TARGET and not config.MIGRATION_JAVA_HOME:
            jdk_problems.append(f"`java` is Java {tc.java_major}, not {TARGET}. Set MIGRATION_JAVA_HOME to a JDK {TARGET}.")
        if jdk_problems:
            pf.ok, pf.stop_reason = False, " ".join(jdk_problems)
        return pf
    if tc.problems:
        pf.ok, pf.stop_reason = False, " ".join(tc.problems)
        return pf

    coords: list[str] = []
    if config.BASELINE_JAVA_HOME:
        base_tc = java_env.probe(roots[0], java_home=config.BASELINE_JAVA_HOME, target=8)
        pf.baseline_test_jdk = base_tc.java_major
        if base_tc.java_major is None:
            pf.notes.append(f"BASELINE_JAVA_HOME (`{config.BASELINE_JAVA_HOME}`) could not run Java — "
                            "baseline tests skipped.")
        else:
            for root in roots:
                java_env.clear_reports(root)
                code, out = java_env.run_maven(root, ["-fae", "clean", "test", "-Dmaven.test.failure.ignore=true"],
                                               java_home=config.BASELINE_JAVA_HOME)
                res = java_env.classify(out, code, root)
                if res.environment:
                    pf.environment_errors += [e for e in res.environment if e not in pf.environment_errors]
                    coords += res.coordinates
                pf.baseline_failing_tests += java_env.surefire_failures(root)
            pf.baseline_tests_run = True

    for root in roots:
        code, out = java_env.run_maven(root, ["-fae", "-DskipTests", "clean", "package"])
        res = java_env.classify(out, code, root)
        _merge(pf, res, root.relative_to(workspace).as_posix(), coords)
    pf.baseline_build_ok = not (pf.compile_errors or pf.other_errors or pf.environment_errors)

    if pf.environment_errors:
        pf.ok = False
        pf.stop_reason = (
            "The uploaded code cannot download its own dependencies on this machine, before any change was "
            "made — so a migrated build could not be verified either. Fix the build environment and retry: "
            "repository credentials / mirrors in settings.xml (MAVEN_SETTINGS), network or proxy access, or a "
            "missing internal artifact. "
            + (f"Failing coordinates: {', '.join(coords[:10])}. " if coords else "")
            + "First error: " + pf.environment_errors[0][:300]
        )
    return pf


def to_markdown(pf: Preflight) -> str:
    """The planner's primary evidence: what the target JDK actually reports."""
    tc = pf.toolchain or {}
    out = ["## Baseline Build on JDK 11 (before migration)", "",
           "_The uploaded code, unchanged, built on the target JDK by the preflight. These errors are what "
           "Java 11 actually breaks — the compile-first work list. Plan a change for each; plan a library or "
           "plugin move only when one of these errors (or a test failure in validation) names it._", "",
           f"- Machine: {tc.get('os', '?')}; Maven {tc.get('maven_version') or '—'} on Java "
           f"{tc.get('maven_java_major') or '—'}" + (f"; settings `{tc.get('settings')}`" if tc.get("settings") else ""),
           f"- Build roots: {', '.join(f'`{r}`' for r in pf.roots) or '— (no Maven build)'}"]
    if pf.baseline_build_ok:
        out.append("- **Result: the uploaded code already builds on JDK 11** (compile and package, tests "
                   "compiled). Only the compiler level and the inventory's required changes remain.")
    elif pf.baseline_build_ok is False:
        out.append(f"- **Result: {len(pf.compile_errors)} compile error(s), {len(pf.other_errors)} other build "
                   "error(s).**")
    if pf.skipped_modules:
        out.append(f"- Not built because a module they depend on failed (their own errors appear only after "
                   f"those are fixed): {', '.join(pf.skipped_modules[:20])}")
    if pf.baseline_tests_run:
        out.append(f"- Baseline tests on JDK {pf.baseline_test_jdk}: {len(pf.baseline_failing_tests)} failing "
                   "before the migration (excluded from validation):")
        out += [f"  - `{t}`" for t in pf.baseline_failing_tests[:50]]
    out += pf.notes and [""] + [f"- {n}" for n in pf.notes] or []
    if pf.compile_errors:
        out += ["", "### Compile errors", "", "| File:line | Error |", "|---|---|"]
        for e in pf.compile_errors[:_MAX_LISTED]:
            loc, _, msg = e.partition(" — ")
            out.append(f"| `{loc}` | {msg.replace('|', '/')} |")
        if len(pf.compile_errors) > _MAX_LISTED:
            out.append(f"| … | {len(pf.compile_errors) - _MAX_LISTED} more |")
    if pf.other_errors:
        out += ["", "### Other build errors (plugins, packaging)", ""] + [f"- {e}" for e in pf.other_errors[:50]]
    return "\n".join(out)


def summary(pf: Preflight) -> str:
    """Short form for the report and the screen."""
    tc = pf.toolchain or {}
    parts = [f"Maven {tc.get('maven_version') or '—'} on Java {tc.get('maven_java_major') or '—'} ({tc.get('os', '?')})"]
    if pf.baseline_build_ok:
        parts.append("uploaded code already builds on JDK 11")
    elif pf.baseline_build_ok is False:
        parts.append(f"uploaded code on JDK 11: {len(pf.compile_errors)} compile / {len(pf.other_errors)} other error(s)")
    if pf.baseline_tests_run:
        parts.append(f"{len(pf.baseline_failing_tests)} test(s) already failing on JDK {pf.baseline_test_jdk}")
    if not pf.ok:
        parts.append("STOPPED: " + pf.stop_reason)
    return "; ".join(parts)
