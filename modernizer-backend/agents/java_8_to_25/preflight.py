"""
Preflight for the Java 8 -> 25 run, before anything is planned, and the JDK
each build runs on.

A Java 8 -> 25 run builds on more than one JDK: the incremental strategy's
readiness stages still target Java 8, the next ones Java 17, the last ones
Java 25 (agents/java_8_to_25/stages.py). A stage verified on the wrong JDK
proves nothing — Java 25 code cannot compile on JDK 17, and a JDK 25 build of
the readiness stages hides what JDK 8 would report — so:

1. JDKs: every JDK the machine has (MIGRATION_JAVA_HOMES, MIGRATION_JAVA_HOME,
   BASELINE_JAVA_HOME, the `java` on PATH), each probed for its version. Each
   Java release the run's stages target gets one: the exact major when there
   is one, else the nearest newer one (it compiles that release, but tests run
   on a newer runtime — marked approximate). A release no JDK can build stops
   the run here.
2. Maven 3.6.3+ (the current plugins need it), and the settings file if set.
3. Baseline build on the first stage's JDK: `clean package` of the code exactly as uploaded,
   with its tests (VALIDATE_RUN_TESTS; the tests that already fail are recorded so the validations
   hold the migration only to the tests that passed). Dependency / repository /
   credential errors stop the run — a migrated build could not be verified
   either. Compile errors are reported to the planner: they fail before any
   change, and the readiness stages cannot be validated until they are
   addressed.

`stage_env(tool_context)` is the build tool's environment: JAVA_HOME of the
JDK assigned to the current stage's release (`approved_stage`), Java 25 for
a big-bang run.

Settings (agents/config.py): MIGRATION_JAVA_HOMES ("8=/opt/jdk8,17=/opt/jdk17,
25=/opt/jdk25"), MIGRATION_JAVA_HOME, BASELINE_JAVA_HOME, MAVEN_SETTINGS,
PREFLIGHT (on | warn | off: `warn` reports problems without stopping).
"""
import functools
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import config
from ..java_8_to_11.preflight import check_approved, maven_roots
from ..shared import approved_versions, java_env, progress
from .stages import INCREMENTAL_STAGES, incremental_stages

TARGET = 25
_MAX_LISTED = 300


# ---------------------------------------------------------------------------
# JDKs
# ---------------------------------------------------------------------------

def configured_homes() -> list[tuple[str, str]]:
    """(label, JAVA_HOME) of every JDK named in the settings or the environment; "" is the `java` on PATH."""
    homes: list[tuple[str, str]] = []
    for item in re.split(r"[,;\n]", config.MIGRATION_JAVA_HOMES):
        key, sep, home = item.partition("=")
        if sep and home.strip():
            homes.append((f"MIGRATION_JAVA_HOMES[{key.strip()}]", home.strip()))
    if config.MIGRATION_JAVA_HOME:
        homes.append(("MIGRATION_JAVA_HOME", config.MIGRATION_JAVA_HOME))
    if config.BASELINE_JAVA_HOME:
        homes.append(("BASELINE_JAVA_HOME", config.BASELINE_JAVA_HOME))
    if os.environ.get("JAVA_HOME", "").strip():
        homes.append(("JAVA_HOME", os.environ["JAVA_HOME"].strip()))
    homes.append(("PATH", ""))
    return homes


@functools.lru_cache(maxsize=8)
def _probe_homes(homes: tuple[tuple[str, str], ...], path: str) -> tuple[tuple[int, str, str], ...]:
    """(major, home, label) per JDK that runs, first one per major (settings order wins).
    `home` is the JDK's own java.home, so a build sets JAVA_HOME to it explicitly: Maven
    runs on JAVA_HOME, which can differ from the `java` on PATH."""
    found: dict[int, tuple[int, str, str]] = {}
    for label, home in homes:
        java = str(Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java")) if home else "java"
        env = java_env.build_env(home) if home else {k: v for k, v in os.environ.items() if k != "JAVA_HOME"}
        code, out = java_env._run([java, "-XshowSettings:properties", "-version"], Path.cwd(), env, 60)
        major = java_env.java_major(out) if code == 0 else None
        m = re.search(r"^\s*java\.home = (.+)$", out, re.MULTILINE)
        real = m.group(1).strip() if m else home
        if real.endswith(("/jre", "\\jre")) and (Path(real).parent / "bin").is_dir():
            real = str(Path(real).parent)      # a JDK 8 reports its bundled JRE
        if major is not None and major not in found and real:
            found[major] = (major, real, label)
    return tuple(sorted(found.values()))


def available_jdks() -> list[dict]:
    """Every JDK this machine can run, by major version."""
    return [{"major": m, "home": h, "source": s}
            for m, h, s in _probe_homes(tuple(configured_homes()), os.environ.get("PATH", ""))]


def assign(releases: list[int], jdks: list[dict]) -> dict[int, dict]:
    """The JDK each release builds on: its own major, else the nearest newer one
    (`exact` False). A release with no JDK at or above it is left out."""
    out: dict[int, dict] = {}
    for release in releases:
        candidates = sorted((j for j in jdks if j["major"] >= release), key=lambda j: j["major"])
        if candidates:
            out[release] = {**candidates[0], "exact": candidates[0]["major"] == release}
    return out


def releases_for(strategy: str, springboot_upgrade: bool) -> list[int]:
    """The Java releases the run builds: the uploaded code's (8), each stage's, the target."""
    if strategy == "incremental":
        return sorted({int(s.java_release) for s in incremental_stages(springboot_upgrade)} | {8})
    return [8, TARGET]


def release_for(state: dict) -> int:
    """The release the current build targets: the running incremental stage's, else Java 25."""
    stage = str(state.get("approved_stage") or "")
    match = next((s for s in INCREMENTAL_STAGES if str(s.idx) == stage), None)
    return int(match.java_release) if match else TARGET


def stage_env(tool_context) -> dict[str, str] | None:
    """The build tool's environment: the JDK assigned to the current stage's release."""
    state = getattr(tool_context, "state", None) or {}
    chosen = assign([release_for(state)], available_jdks())
    jdk = next(iter(chosen.values()), None)
    return java_env.build_env(jdk["home"]) if jdk else None


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

@dataclass
class Preflight:
    ok: bool = True
    stop_reason: str = ""
    problems: list[str] = field(default_factory=list)       # what makes a verified migration impossible
    jdks: list[dict] = field(default_factory=list)          # available
    assignment: dict = field(default_factory=dict)         # "release" -> {major, home, source, exact}
    maven: str = ""
    maven_version: str = ""
    os: str = ""
    settings: str = ""
    roots: list[str] = field(default_factory=list)
    build_tool: str = "maven"
    baseline_jdk: int | None = None
    baseline_build_ok: bool | None = None
    baseline_tests_run: bool = False                       # the baseline build also ran the test suite
    baseline_failing_tests: list[str] = field(default_factory=list)   # Class#method failing on the code as uploaded
    compile_errors: list[str] = field(default_factory=list)
    other_errors: list[str] = field(default_factory=list)
    environment_errors: list[str] = field(default_factory=list)
    skipped_modules: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    approved_checked: int = 0
    approved_unavailable: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def _stop(pf: Preflight, *reasons: str) -> Preflight:
    """Record what makes a verified migration impossible; it stops the run unless PREFLIGHT=warn."""
    pf.problems += [r for r in reasons if r not in pf.problems]
    if pf.problems and config.PREFLIGHT != "warn":
        pf.ok = False
        pf.stop_reason = " ".join(pf.problems)
    return pf


def run(workspace_dir: str, strategy: str = "bigbang", springboot_upgrade: bool = False) -> Preflight:
    import platform
    workspace = Path(workspace_dir)
    pf = Preflight(os=f"{platform.system()} {platform.release()}", settings=config.MAVEN_SETTINGS)
    progress.stage("Environment check: finding the JDKs (MIGRATION_JAVA_HOMES, MIGRATION_JAVA_HOME, "
                   "BASELINE_JAVA_HOME, JAVA_HOME, PATH)")
    pf.jdks = available_jdks()
    releases = releases_for(strategy, springboot_upgrade)
    chosen = assign(releases, pf.jdks)
    pf.assignment = {str(r): j for r, j in chosen.items()}
    have = ", ".join(f"{j['major']} ({j['source']})" for j in pf.jdks) or "none"
    problems: list[str] = []
    for r in releases:
        if r not in chosen:
            problems.append(f"No JDK {r} or newer is available, so the Java {r} builds cannot run (JDKs found: "
                               f"{have}). Install one and name it in MIGRATION_JAVA_HOMES (e.g. `{r}=/opt/jdk-{r}`).")
        elif not chosen[r]["exact"]:
            pf.notes.append(f"No JDK {r}: Java {r} builds run on JDK {chosen[r]['major']} ({chosen[r]['source']}) "
                            f"— they compile for {r}, but tests run on a Java {chosen[r]['major']} runtime. Name a "
                            f"JDK {r} in MIGRATION_JAVA_HOMES for an exact check.")

    progress.stage("Environment check: finding the Maven builds in the repository")
    roots = maven_roots(workspace)
    pf.roots = [r.relative_to(workspace).as_posix() or "." for r in roots]
    if not roots:
        gradle = any(workspace.rglob("build.gradle")) or any(workspace.rglob("build.gradle.kts"))
        pf.build_tool = "gradle" if gradle else "none"
        pf.notes.append("No Maven build in the repository — only the JDKs were checked"
                        + (" (Gradle builds are validated by the build loop)." if gradle else "."))
        return _stop(pf, *problems)

    mvn = java_env.maven_executable(roots[0])
    if not mvn:
        problems.append("Maven is not installed (no `mvn` on PATH and no `mvnw` in the project).")
    else:
        progress.stage(f"Environment check: `{Path(mvn).name} -v`")
        code, out = java_env._run([mvn, "-v"], roots[0], java_env.build_env(None), 120)
        first = next((l for l in out.splitlines() if l.startswith("Apache Maven")), "")
        pf.maven = first.strip()
        m = re.search(r"Apache Maven (\S+)", first)
        pf.maven_version = m.group(1) if m else ""
        if code != 0 or not pf.maven_version:
            problems.append(f"`mvn -v` failed: {out.strip()[:300]}")
        elif java_env._version_tuple(pf.maven_version) < (3, 6, 3):
            problems.append(f"Maven {pf.maven_version} is older than 3.6.3, the oldest the Java 17+ / Spring Boot 3 "
                               "plugins support — upgrade Maven (or the project's wrapper).")
    if pf.settings and not Path(pf.settings).is_file():
        problems.append(f"MAVEN_SETTINGS points at `{pf.settings}`, which does not exist.")
    _stop(pf, *problems)
    if not pf.ok or 8 not in chosen or not mvn:
        return pf

    entries, list_problems = approved_versions.load()
    if list_problems:
        return _stop(pf, f"The approved-versions list (`{config.APPROVED_VERSIONS_FILE}`) has errors — fix them so "
                         "the migration uses the versions you intended: " + "; ".join(list_problems[:5]))
    baseline = chosen[8]
    pf.baseline_jdk = baseline["major"]
    if entries:
        pf.approved_checked = sum(1 for e in entries if e.artifact != "*")
        progress.stage(f"Environment check: can each of the {pf.approved_checked} approved versions be downloaded")
        pf.approved_unavailable = check_approved(entries, java_home=baseline["home"] or None)

    coords: list[str] = []
    run_tests = config.VALIDATE_RUN_TESTS
    for n, root in enumerate(roots, 1):
        progress.stage(f"Environment check: baseline build of `{root.relative_to(workspace).as_posix() or '.'}` "
                       f"({n} of {len(roots)}) on JDK {baseline['major']} — "
                       f"`mvn -fae clean package{'' if run_tests else ' -DskipTests'}` of the code as uploaded"
                       f"{', tests included' if run_tests else ''} (a first build downloads every dependency)")
        if run_tests:
            java_env.clear_reports(root)
        args = ["-fae", "clean", "package", "-Dmaven.test.failure.ignore=true"] if run_tests \
            else ["-fae", "-DskipTests", "clean", "package"]
        code, out = java_env.run_maven(root, args, java_home=baseline["home"] or None)
        if run_tests:
            pf.baseline_failing_tests += [t for t in java_env.surefire_failures(root) if t not in pf.baseline_failing_tests]
        res = java_env.classify(out, code, root)
        rel = root.relative_to(workspace).as_posix()
        prefix = "" if rel in ("", ".") else f"{rel}/"
        pf.compile_errors += [e if e.startswith(prefix) else prefix + e for e in res.compile]
        pf.other_errors += res.other
        pf.environment_errors += [e for e in res.environment if e not in pf.environment_errors]
        pf.skipped_modules += res.skipped
        coords += [c for c in res.coordinates if c not in coords]
    pf.baseline_build_ok = not (pf.compile_errors or pf.other_errors or pf.environment_errors)
    pf.baseline_tests_run = run_tests and pf.baseline_build_ok is not None
    if pf.environment_errors:
        _stop(pf, "The uploaded code cannot download its own dependencies on this machine, before any change was "
                  "made — so a migrated build could not be verified either. Fix the build environment and retry: "
                  "repository credentials / mirrors in settings.xml (MAVEN_SETTINGS), network or proxy access, or a "
                  "missing internal artifact. "
                  + (f"Failing coordinates: {', '.join(coords[:10])}. " if coords else "")
                  + "First error: " + pf.environment_errors[0][:300])
    return pf


def to_markdown(pf: Preflight) -> str:
    """The planner's evidence: which JDK builds each release, and what the uploaded code reports on the first."""
    out = ["## Build Environment and Baseline Build (before migration)", "",
           "_Checked by the preflight before planning. Every stage is built on the JDK listed for its release. "
           "Errors in the baseline build fail before any change: plan their fix in the first stage that "
           "touches the file, since no stage can be validated while they remain._", "",
           f"- Machine: {pf.os or '?'}; {pf.maven or 'Maven —'}"
           + (f"; settings `{pf.settings}`" if pf.settings else ""),
           f"- Build roots: {', '.join(f'`{r}`' for r in pf.roots) or '— (no Maven build)'}",
           "", "| Java release | Built on | Source | Exact |", "|---|---|---|---|"]
    for release, jdk in sorted(pf.assignment.items(), key=lambda kv: int(kv[0])):
        out.append(f"| {release} | JDK {jdk['major']} | {jdk['source']} | {'yes' if jdk['exact'] else 'no — newer JDK'} |")
    out.append("")
    if pf.baseline_build_ok:
        out.append(f"- **Baseline: the uploaded code builds on JDK {pf.baseline_jdk}** (compile and package, tests "
                   "compiled).")
    elif pf.baseline_build_ok is False:
        out.append(f"- **Baseline on JDK {pf.baseline_jdk}: {len(pf.compile_errors)} compile error(s), "
                   f"{len(pf.other_errors)} other build error(s), {len(pf.environment_errors)} environment error(s).**")
    if pf.baseline_tests_run:
        out.append(f"- Baseline tests on JDK {pf.baseline_jdk}: {len(pf.baseline_failing_tests)} failing before any change"
                   + (" — the validations tolerate exactly these and no others:" if pf.baseline_failing_tests else "."))
        out += [f"  - `{t}`" for t in pf.baseline_failing_tests[:50]]
    if pf.skipped_modules:
        out.append(f"- Not built because a module they depend on failed: {', '.join(pf.skipped_modules[:20])}")
    if pf.approved_checked:
        out.append(f"- Approved versions: {pf.approved_checked} checked, {len(pf.approved_unavailable)} not "
                   "downloadable" + (" — **do not use these**:" if pf.approved_unavailable else "."))
        out += [f"  - `{u.split(' ')[0]}`" for u in pf.approved_unavailable[:20]]
    out += [f"- ⚠ {p}" for p in pf.problems]
    out += [f"- {n}" for n in pf.notes]
    if pf.compile_errors:
        out += ["", "### Baseline compile errors", "", "| File:line | Error |", "|---|---|"]
        for e in pf.compile_errors[:_MAX_LISTED]:
            loc, _, msg = e.partition(" — ")
            out.append(f"| `{loc}` | {msg.replace('|', '/')} |")
        if len(pf.compile_errors) > _MAX_LISTED:
            out.append(f"| … | {len(pf.compile_errors) - _MAX_LISTED} more |")
    if pf.other_errors:
        out += ["", "### Other baseline build errors", ""] + [f"- {e}" for e in pf.other_errors[:50]]
    return "\n".join(out)


def summary(pf: Preflight) -> str:
    parts = ["JDKs: " + (", ".join(f"Java {r} on JDK {j['major']}{'' if j['exact'] else ' (approx.)'}"
                                   for r, j in sorted(pf.assignment.items(), key=lambda kv: int(kv[0])))
                         or "none usable")]
    if pf.maven_version:
        parts.append(f"Maven {pf.maven_version}")
    if pf.baseline_build_ok:
        parts.append(f"uploaded code builds on JDK {pf.baseline_jdk}")
    elif pf.baseline_build_ok is False:
        parts.append(f"uploaded code on JDK {pf.baseline_jdk}: {len(pf.compile_errors)} compile / "
                     f"{len(pf.other_errors)} other / {len(pf.environment_errors)} environment error(s)")
    if pf.baseline_tests_run:
        parts.append(f"{len(pf.baseline_failing_tests)} test(s) already failing on JDK {pf.baseline_jdk}")
    if pf.approved_unavailable:
        parts.append("approved versions NOT downloadable: " + ", ".join(u.split(" ")[0] for u in pf.approved_unavailable[:5]))
    if not pf.ok:
        parts.append("STOPPED: " + pf.stop_reason)
    elif pf.problems:
        parts.append("WARNINGS (PREFLIGHT=warn): " + " ".join(pf.problems))
    return "; ".join(parts)
