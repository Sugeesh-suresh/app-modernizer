"""
Deterministic scope fence for patterns that must leave part of the repository
exactly as it was uploaded.

Most patterns transform whatever the plan names. `java-8-to-11` is different:
it is a JDK upgrade inside an application that keeps running on the same
WildFly deployment with the same JSP views, so the JSP tier and the WildFly
deployment contract are *frozen* -- not "left alone unless the plan says
otherwise", but never modified by any agent under any circumstances. A prompt
cannot guarantee that; this module does, in three places:

  1. **Write time** -- `writable()` and `check_edit()` back the guarded
     `write_file` / `replace_in_file` tools the modifier and fixer are given
     (agents/java_8_to_11/tools.py). A frozen file, a file outside the
     pattern's allow-list, or an edit that breaks a build-file invariant is
     refused with an `ERROR:` the agent can read and act on.
  2. **Validate time** -- `verify_invariants()` backs the validator's
     deterministic check. The build loop only exits green when the build
     passes AND the invariants hold.
  3. **End of run** -- `restore_frozen()` puts every frozen file back to its
     baseline bytes before the diff is computed (main.py). Build plugins run by
     `mvn` are outside the guarded tools, so this is the backstop that makes
     "JSP and WildFly files are unchanged" true by construction rather than by
     trust.

`change_audit.py` also reads `frozen_reason()` so the independent reviewer sees
any frozen-file change as a regression, and so untouched frozen files are never
reported as coverage gaps.

Patterns with no fence registered get `None` from `fence_for()`, and every
public function here is a no-op for them.
"""
import fnmatch
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .dependency_graph import EXCLUDED_DIRS


@dataclass(frozen=True)
class Fence:
    """What one pattern may never touch, and the only things it may touch."""
    pattern: str
    #: File suffixes that are frozen wherever they appear, with the reason.
    frozen_suffixes: dict[str, str]
    #: Case-insensitive basename globs that are frozen wherever they appear.
    frozen_names: dict[str, str]
    #: Directory segments whose whole subtree is frozen (e.g. `WEB-INF`).
    frozen_segments: dict[str, str]
    #: Path prefixes whose whole subtree is frozen (e.g. `src/main/webapp/`).
    frozen_roots: dict[str, str]
    #: Suffixes an agent may write (outside the frozen zone).
    writable_suffixes: frozenset[str]
    #: Exact basenames an agent may write (outside the frozen zone).
    writable_names: frozenset[str]
    #: Workspace-relative path suffixes an agent may write (wrapper configs).
    writable_path_suffixes: tuple[str, ...]
    #: The one Java release the build must target when the run is done.
    java_release: int


_JSP = "JSP view layer — frozen: this migration upgrades Java only and never edits JSP"
_WILDFLY = "WildFly deployment contract — frozen: the deployment architecture must stay exactly as uploaded"
_WEBAPP = "web application root (JSP, static assets, WEB-INF descriptors) — frozen"
_RUNTIME = "runtime / container launch configuration — frozen: JVM and container settings belong to the WildFly deployment, not to this migration"

JAVA_8_TO_11 = Fence(
    pattern="java-8-to-11",
    frozen_suffixes={
        ".jsp": _JSP, ".jspf": _JSP, ".jspx": _JSP, ".tag": _JSP, ".tagx": _JSP, ".tld": _JSP,
        ".cli": _WILDFLY,
    },
    frozen_names={
        # WildFly / JBoss descriptors and server configuration.
        "jboss-*.xml": _WILDFLY,
        "standalone*.xml": _WILDFLY,
        "domain.xml": _WILDFLY,
        "host.xml": _WILDFLY,
        "host-*.xml": _WILDFLY,
        "*-ds.xml": _WILDFLY,
        "module.xml": _WILDFLY,
        # Jakarta/Java EE deployment descriptors the container reads.
        "web.xml": _WILDFLY,
        "application.xml": _WILDFLY,
        "ejb-jar.xml": _WILDFLY,
        "persistence.xml": _WILDFLY,
        "beans.xml": _WILDFLY,
        "ra.xml": _WILDFLY,
        "manifest.mf": _WILDFLY,
        # How the container is launched.
        "standalone.conf*": _RUNTIME,
        "domain.conf*": _RUNTIME,
        "dockerfile*": _RUNTIME,
        "docker-compose*.yml": _RUNTIME,
        "docker-compose*.yaml": _RUNTIME,
    },
    frozen_segments={
        "WEB-INF": _WEBAPP,
        "META-INF": _WILDFLY,
    },
    frozen_roots={
        "src/main/webapp/": _WEBAPP,
        "WebContent/": _WEBAPP,
        "WebRoot/": _WEBAPP,
    },
    writable_suffixes=frozenset({".java"}),
    writable_names=frozenset({
        "pom.xml",
        "build.gradle", "build.gradle.kts",
        "settings.gradle", "settings.gradle.kts",
        "gradle.properties", "libs.versions.toml",
    }),
    # A Gradle wrapper older than 5.0 cannot run on JDK 11, and a Maven wrapper
    # pins the Maven the build runs on -- both are build-toolchain, not deployment.
    writable_path_suffixes=(
        "gradle/wrapper/gradle-wrapper.properties",
        ".mvn/wrapper/maven-wrapper.properties",
        ".mvn/jvm.config",
    ),
    java_release=11,
)

FENCES: dict[str, Fence] = {JAVA_8_TO_11.pattern: JAVA_8_TO_11}


def fence_for(pattern: str) -> Fence | None:
    return FENCES.get(pattern)


def _norm(rel_path: str) -> str:
    rel = str(PurePosixPath(rel_path.replace("\\", "/")))
    while rel.startswith("./"):
        rel = rel[2:]
    return "" if rel == "." else rel.lstrip("/")


def frozen_reason(pattern: str, rel_path: str) -> str | None:
    """Why `rel_path` is frozen for `pattern`, or None when it is not (or the
    pattern has no fence)."""
    fence = fence_for(pattern)
    if not fence:
        return None
    rel = _norm(rel_path)
    path = PurePosixPath(rel)
    name = path.name.lower()
    suffix = path.suffix.lower()

    for root, reason in fence.frozen_roots.items():
        if rel.startswith(root) or f"/{root}" in f"/{rel}":
            return reason
    if suffix in fence.frozen_suffixes:
        return fence.frozen_suffixes[suffix]
    # A Java package can legitimately be called `domain` or `standalone`, so the
    # name and segment rules below are for non-source files only.
    if suffix == ".java":
        return None
    for glob, reason in fence.frozen_names.items():
        if fnmatch.fnmatch(name, glob):
            return reason
    for segment, reason in fence.frozen_segments.items():
        if segment in path.parts[:-1]:
            return reason
    return None


def writable(pattern: str, rel_path: str) -> tuple[bool, str]:
    """(may an agent write this path?, the reason when it may not)."""
    fence = fence_for(pattern)
    if not fence:
        return True, ""
    reason = frozen_reason(pattern, rel_path)
    if reason:
        return False, reason
    rel = _norm(rel_path)
    path = PurePosixPath(rel)
    if path.suffix.lower() in fence.writable_suffixes or path.name in fence.writable_names:
        return True, ""
    if any(rel == s or rel.endswith("/" + s) for s in fence.writable_path_suffixes):
        return True, ""
    return False, (
        "outside this migration's scope — only `.java` sources and build files (pom.xml, "
        "build.gradle[.kts], settings.gradle, gradle.properties, wrapper properties) may change. "
        "If the Java upgrade genuinely cannot succeed without changing this file, stop and report it "
        "for a human instead of working around the fence."
    )


# ---------------------------------------------------------------------------
# Content invariants
# ---------------------------------------------------------------------------

_PACKAGING = re.compile(r"<packaging>\s*([^<\s]+)\s*</packaging>")
_FINAL_NAME = re.compile(r"<finalName>\s*([^<]*?)\s*</finalName>")
_PLUGIN_BLOCK = re.compile(r"<plugin>.*?</plugin>", re.DOTALL)
_ARTIFACT_ID = re.compile(r"<artifactId>\s*([^<\s]+)\s*</artifactId>")
_VERSION_TAG = re.compile(r"<version>[^<]*</version>")
_WS = re.compile(r"\s+")

# Every way a Maven or Gradle build names the Java level it compiles for.
_MAVEN_LEVEL = re.compile(
    r"<(release|source|target|maven\.compiler\.(?:release|source|target)|java\.version|"
    r"jdk\.version|java\.release)>\s*([0-9][0-9.]*)\s*</"
)
_GRADLE_LEVEL = re.compile(
    r"\b(sourceCompatibility|targetCompatibility|release|languageVersion)\b[^\n]*?"
    r"(?:JavaVersion\.VERSION_|\(\s*|['\"]|=\s*)(1[._]\d+|\d+)"
)
_GRADLE_WAR = re.compile(r"""apply\s+plugin\s*:\s*['"]war['"]|\bid\s*\(?\s*['"]war['"]|^\s*war\s*$""", re.MULTILINE)
_BOOT = re.compile(r"spring-boot|org\.springframework\.boot")
_JAKARTA_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?(jakarta\.[\w.*]+)", re.MULTILINE)


def _level(raw: str) -> int | None:
    raw = raw.replace("_", ".")
    try:
        parts = [int(p) for p in raw.split(".") if p]
    except ValueError:
        return None
    if not parts:
        return None
    return parts[1] if parts[0] == 1 and len(parts) > 1 else parts[0]


def declared_java_levels(rel_path: str, text: str) -> list[tuple[str, int]]:
    """`[(setting, level), ...]` for every literal Java level a build file
    declares. Property references (`${java.version}`) are not literals and are
    resolved where the property itself is declared."""
    name = PurePosixPath(_norm(rel_path)).name
    found: list[tuple[str, int]] = []
    if name == "pom.xml":
        for tag, raw in _MAVEN_LEVEL.findall(text):
            level = _level(raw)
            if level is not None:
                found.append((tag, level))
    elif name.startswith("build.gradle") or name == "gradle.properties":
        for key, raw in _GRADLE_LEVEL.findall(text):
            level = _level(raw)
            if level is not None:
                found.append((key, level))
    return found


def _plugin_blocks(text: str, match) -> list[str]:
    blocks = []
    for block in _PLUGIN_BLOCK.findall(text):
        ids = _ARTIFACT_ID.findall(block)
        if ids and match(ids[0]):
            blocks.append(block)
    return blocks


def _normalise_block(block: str, drop_version: bool) -> str:
    if drop_version:
        block = _VERSION_TAG.sub("", block, count=1)
    return _WS.sub(" ", block).strip()


def _check_pom(fence: Fence, before: str, after: str) -> list[str]:
    problems: list[str] = []
    if _PACKAGING.findall(before) != _PACKAGING.findall(after):
        problems.append(
            f"`<packaging>` changed from {_PACKAGING.findall(before) or ['(default jar)']} to "
            f"{_PACKAGING.findall(after) or ['(default jar)']} — the deployable must stay exactly what "
            "WildFly deploys today"
        )
    if _FINAL_NAME.findall(before) != _FINAL_NAME.findall(after):
        problems.append(
            "`<finalName>` changed — on WildFly the archive name is the deployment name and, without "
            "a jboss-web.xml context-root, the URL; it must not change"
        )

    def is_container_plugin(aid: str) -> bool:
        return "wildfly" in aid or "jboss" in aid or aid.startswith("cargo")

    if [_normalise_block(b, False) for b in _plugin_blocks(before, is_container_plugin)] != \
       [_normalise_block(b, False) for b in _plugin_blocks(after, is_container_plugin)]:
        problems.append(
            "a WildFly/JBoss deployment plugin block changed — deployment tooling is part of the frozen "
            "WildFly architecture"
        )
    # The WAR plugin may need a newer *version* to run on JDK 11 (2.x cannot), but
    # its configuration shapes the deployed archive and must stay byte-for-byte.
    if [_normalise_block(b, True) for b in _plugin_blocks(before, lambda a: a == "maven-war-plugin")] != \
       [_normalise_block(b, True) for b in _plugin_blocks(after, lambda a: a == "maven-war-plugin")]:
        problems.append(
            "maven-war-plugin changed beyond its `<version>` — only the version may move (2.x cannot "
            "run on JDK 11); its configuration shapes the WAR WildFly deploys"
        )
    return problems


def _check_gradle(before: str, after: str) -> list[str]:
    if bool(_GRADLE_WAR.search(before)) != bool(_GRADLE_WAR.search(after)):
        return ["the Gradle `war` plugin was added or removed — the deployable must stay what WildFly deploys today"]
    return []


def check_edit(pattern: str, rel_path: str, before: str, after: str) -> list[str]:
    """Every invariant the edit `before` → `after` of `rel_path` would break.
    Empty when the edit is within the fence (or the pattern has none)."""
    fence = fence_for(pattern)
    if not fence:
        return []
    rel = _norm(rel_path)
    name = PurePosixPath(rel).name
    problems: list[str] = []

    if name == "pom.xml" or name.startswith("build.gradle") or name == "gradle.properties":
        overshoot = sorted({
            f"{setting}={level}" for setting, level in declared_java_levels(rel, after)
            if level > fence.java_release
        } - {
            f"{setting}={level}" for setting, level in declared_java_levels(rel, before)
            if level > fence.java_release
        })
        if overshoot:
            problems.append(
                f"Java level set past {fence.java_release} ({', '.join(overshoot)}) — the target is "
                f"exactly Java {fence.java_release}, and WildFly will run this on a Java "
                f"{fence.java_release} JVM"
            )
        if not _BOOT.search(before) and _BOOT.search(after):
            problems.append(
                "Spring Boot introduced — out of scope: this migration upgrades the JDK and nothing about "
                "the application framework or deployment model"
            )
        if name == "pom.xml":
            problems += _check_pom(fence, before, after)
        else:
            problems += _check_gradle(before, after)

    if rel.endswith(".java"):
        added = sorted(set(_JAKARTA_IMPORT.findall(after)) - set(_JAKARTA_IMPORT.findall(before)))
        if added:
            problems.append(
                f"`jakarta.*` import added ({', '.join(added[:3])}{' …' if len(added) > 3 else ''}) — Java "
                "11 keeps the Java EE `javax.*` namespace, which is what the WildFly container provides; "
                "the Jakarta rename is a different migration"
            )
    return problems


# ---------------------------------------------------------------------------
# Whole-workspace checks
# ---------------------------------------------------------------------------

def _files(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    if not root.exists():
        return out
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if EXCLUDED_DIRS & set(rel.parts):
            continue
        out[rel.as_posix()] = path
    return out


def _bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _text(path: Path) -> str:
    return _bytes(path).decode("utf-8", errors="replace")


def frozen_changes(pattern: str, baseline_dir: str, workspace_dir: str) -> list[tuple[str, str]]:
    """`[(path, "modified" | "deleted" | "added"), ...]` for every frozen file
    that differs from the baseline."""
    if not fence_for(pattern) or not baseline_dir or not workspace_dir:
        return []
    before = _files(Path(baseline_dir))
    after = _files(Path(workspace_dir))
    changes: list[tuple[str, str]] = []
    for rel in sorted(set(before) | set(after)):
        if not frozen_reason(pattern, rel):
            continue
        if rel not in after:
            changes.append((rel, "deleted"))
        elif rel not in before:
            changes.append((rel, "added"))
        elif _bytes(before[rel]) != _bytes(after[rel]):
            changes.append((rel, "modified"))
    return changes


def restore_frozen(pattern: str, baseline_dir: str, workspace_dir: str) -> list[tuple[str, str]]:
    """Put every frozen file back exactly as uploaded. Returns what was undone:
    `[(path, "restored" | "removed"), ...]` — empty when the fence held."""
    undone: list[tuple[str, str]] = []
    base, work = Path(baseline_dir), Path(workspace_dir)
    for rel, status in frozen_changes(pattern, baseline_dir, workspace_dir):
        target = work / rel
        if status == "added":
            target.unlink(missing_ok=True)
            undone.append((rel, "removed"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(base / rel, target)
            undone.append((rel, "restored"))
    return undone


def verify_invariants(pattern: str, baseline_dir: str, workspace_dir: str) -> tuple[list[str], list[str]]:
    """(problems, notes) for the migrated workspace as a whole.

    Problems fail validation: a frozen file changed, a build file broke an
    invariant relative to its baseline, a `jakarta.*` import appeared, or a
    build file still declares a Java level other than the target. Notes are
    context the validator should report but that do not fail the run.
    """
    fence = fence_for(pattern)
    if not fence:
        return [], []
    problems: list[str] = []
    notes: list[str] = []

    for rel, status in frozen_changes(pattern, baseline_dir, workspace_dir):
        problems.append(f"`{rel}` — frozen file {status} ({frozen_reason(pattern, rel)})")

    before = _files(Path(baseline_dir)) if baseline_dir else {}
    after = _files(Path(workspace_dir)) if workspace_dir else {}

    build_files = sorted(
        rel for rel in after
        if PurePosixPath(rel).name in ("pom.xml", "build.gradle", "build.gradle.kts", "gradle.properties")
    )
    any_target = False
    for rel in build_files:
        levels = declared_java_levels(rel, _text(after[rel]))
        wrong = [f"{s}={lvl}" for s, lvl in levels if lvl != fence.java_release]
        if wrong:
            problems.append(
                f"`{rel}` still declares a Java level other than {fence.java_release}: {', '.join(wrong)}"
            )
        if any(lvl == fence.java_release for _, lvl in levels):
            any_target = True
        if not levels:
            notes.append(f"`{rel}` declares no literal Java level (inherits it, or uses a property defined elsewhere)")
    if build_files and not any_target:
        problems.append(f"no build file declares Java {fence.java_release} — the compiler level was never set")

    for rel in sorted(set(before) & set(after)):
        if not (rel.endswith(".java") or PurePosixPath(rel).name in (
            "pom.xml", "build.gradle", "build.gradle.kts", "gradle.properties",
        )):
            continue
        old, new = _bytes(before[rel]), _bytes(after[rel])
        if old == new:
            continue
        for problem in check_edit(pattern, rel, old.decode("utf-8", "replace"), new.decode("utf-8", "replace")):
            problems.append(f"`{rel}` — {problem}")
    for rel in sorted(set(after) - set(before)):
        if rel.endswith(".java"):
            for problem in check_edit(pattern, rel, "", _text(after[rel])):
                problems.append(f"`{rel}` (new file) — {problem}")
    return problems, notes


def to_markdown(pattern: str, problems: list[str], notes: list[str]) -> str:
    fence = fence_for(pattern)
    target = fence.java_release if fence else "?"
    lines = [f"# Java {target} scope-fence check (deterministic)", ""]
    if problems:
        lines.append("PROBLEMS (each one fails validation):")
        lines += [f"- {p}" for p in problems]
    else:
        lines.append(
            f"No problems: every frozen JSP/WildFly file is byte-identical to the upload, every build "
            f"invariant held, and the build targets Java {target}."
        )
    if notes:
        lines += ["", "Notes:"] + [f"- {n}" for n in notes]
    lines += ["", "OVERALL: FAIL" if problems else "OVERALL: PASS"]
    return "\n".join(lines)
