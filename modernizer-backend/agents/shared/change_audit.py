"""
Deterministic (non-LLM) audit of what a migration run actually changed, run
as the first step of the independent code review.

The build loop proves the code compiles and the reviewer reads the files, but
neither answers the two questions a human reviewer asks first:

  1. Did anything really change, and is every change explained by the
     migration? A file that was rewritten without any legacy marker
     disappearing or any modern one appearing is scope creep (or a
     gratuitous reformat) until someone justifies it — and a *legacy*
     marker that appears in an added line is an outright regression
     (re-adding Jackson 2 on a Boot 4 target, silencing a JDK 17
     `InaccessibleObjectException` with `--add-opens`).

  2. Are the untouched files really irrelevant? An unchanged file that
     still matches a legacy marker is a coverage gap candidate: either the
     modifier missed it, or it belongs to a stage/toggle that was out of
     scope. Only the plan can say which, so this module reports the
     evidence and the reviewer adjudicates.

Philosophy is `companion_detector.py`'s: cheap regex static analysis over
real files, with the matched line quoted as evidence so the finding is
auditable rather than an opaque AI guess. The markers are deliberately
recall-biased — a false positive costs the reviewer one sentence of
adjudication, a false negative hides a missed file.

`audit_migration_changes` is the ADK tool wrapper; every pattern's code
reviewer gets it automatically via `make_code_reviewer_agent`.
"""
import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from google.adk.tools import ToolContext

from .dependency_graph import EXCLUDED_DIRS

# File types worth grepping for library/API signatures — sources, build files
# and config, across every pattern this app supports.
_SCAN_SUFFIXES = {
    ".java", ".xml", ".properties", ".yml", ".yaml", ".gradle", ".kts",
    ".jsp", ".jspf", ".tag", ".tld", ".sql", ".pks", ".pkb", ".plsql",
    ".js", ".jsx", ".ts", ".tsx", ".json", ".conf", ".cfg",
}

# Evidence caps — a review prompt has a budget, and 200 residual-legacy files
# all saying the same thing helps nobody.
_MAX_FILES_PER_BUCKET = 40
_MAX_HITS_PER_FILE = 4
_MAX_LINE_CHARS = 200


@dataclass(frozen=True)
class Marker:
    """One regex signature, with the note the reviewer needs to adjudicate it."""
    name: str
    pattern: re.Pattern
    note: str = ""


def _m(name: str, regex: str, note: str = "", flags: int = 0) -> Marker:
    return Marker(name, re.compile(regex, flags), note)


# ---------------------------------------------------------------------------
# Marker sets, per pattern.
#
#   legacy    — must NOT survive the migration. Removed in a diff = the change
#               is migration work; still present in an untouched file = a
#               coverage-gap candidate; ADDED in a diff = a regression.
#   modern    — the migration's target APIs. Added in a diff = migration work.
#   forbidden — never a legitimate fix, whatever the plan says (see the
#               java-8-to-25-fix skill's "never by adding --add-opens" rule).
# ---------------------------------------------------------------------------

_JAVA_LEGACY = [
    # Jakarta EE namespaces only — Java SE javax.sql / javax.naming / javax.crypto /
    # JAXP and JSR-107 javax.cache legitimately keep their javax names forever.
    _m("javax EE namespace",
       r"\bjavax\.(?:servlet|persistence|validation|annotation|transaction|ws\.rs|ejb|jms|mail|xml\.bind|xml\.ws|enterprise|inject|faces|batch)\b",
       "Jakarta EE package — becomes jakarta.* in the Spring Boot 3 / Spring 6 stage. Java SE javax.sql/naming/crypto/JAXP and javax.cache (JSR-107) are NOT part of that rename."),
    _m("Spring 3/4 hibernate3 support", r"org\.springframework\.orm\.hibernate[34]\b",
       "Removed in Spring 5 — rewrite onto org.springframework.orm.hibernate5 (Java 17 stage)."),
    _m("Jackson 1", r"org\.codehaus\.jackson",
       "Jackson 1 is EOL — an API rewrite to com.fasterxml.jackson, not a version bump (Java 17 stage)."),
    _m("Jackson afterburner", r"jackson-module-afterburner|jackson\.module\.afterburner",
       "Breaks under JDK 17 strong encapsulation — replace with jackson-module-blackbird."),
    _m("Jackson unsafe default typing", r"\benableDefaultTyping\s*\(",
       "Removed/unsafe — activateDefaultTyping(PolymorphicTypeValidator) with an allow-list."),
    _m("Ehcache 2", r"\bnet\.sf\.ehcache\b",
       "Ehcache 2 → Ehcache 3 (org.ehcache) — an API rewrite; getKeys()/getQuiet() have no equivalent."),
    _m("Spring Ehcache 2 support", r"org\.springframework\.cache\.ehcache|EhCacheCacheManager|EhCacheManagerFactoryBean",
       "Removed in Spring 6 — JCacheCacheManager over Ehcache 3's JSR-107 provider."),
    _m("Hibernate Ehcache 2 support", r"\bhibernate-ehcache\b|org\.hibernate\.cache\.ehcache",
       "Removed in Hibernate 6 — hibernate-jcache with the jcache region factory."),
    _m("ehcache-web", r"\behcache-web\b",
       "No modern equivalent — the filters are removed and flagged."),
    _m("log4j 1.2", r"\borg\.apache\.log4j\b|<artifactId>log4j</artifactId>",
       "log4j 1.2 is EOL — SLF4J + Logback."),
    _m("cglib / javassist", r"\bcglib(?:-nodep)?\b|\bjavassist\b",
       "Bundles an ASM that cannot read modern class files — remove it; Spring 5+ repackages cglib and Hibernate 5.3+ uses ByteBuddy."),
    _m("Oracle versioned dialect", r"Oracle(?:8i|9i|10g|12c)Dialect",
       "Versioned dialects were removed in Hibernate 6 — drop hibernate.dialect and let it auto-detect."),
    _m("C3P0 / DBCP pool", r"C3P0ConnectionProvider|\bcom\.mchange\.v2\b|\bcommons-dbcp\b",
       "Superseded by HikariCP once Spring Boot manages the datasource."),
    _m("legacy Oracle JDBC driver", r"\bojdbc(?:6|14)\b",
       "ojdbc6/ojdbc14 do not run on a modern JDK — ojdbc11."),
    _m("google-collections", r"\bgoogle-collections\b|com\.google\.collections",
       "Same packages as Guava — remove it and keep the newest Guava."),
    _m("removed Guava API", r"Objects\.toStringHelper|\bnew\s+Stopwatch\s*\(|\.elapsedMillis\s*\(|makeComputingMap|sameThreadExecutor",
       "Removed from modern Guava — MoreObjects, Stopwatch.createStarted(), CacheBuilder, directExecutor()."),
    _m("spring-mock", r"\bspring-mock\b",
       "A test library used at runtime scope — replace with real HttpServletRequestWrapper / ServletOutputStream."),
    _m("Mockito 1.x", r"\bmockito-all\b",
       "Mocks via cglib and breaks on JDK 9+ — mockito-core (4.11.0 in readiness, 5.x from the Java 17 stage)."),
    _m("JUnit 3", r"\bjunit\.framework\.TestCase\b|\bjunit\.framework\.Assert\b",
       "JUnit 3 is deprecated — report it even when the JUnit toggle is off."),
    _m("JUnit 4", r"\borg\.junit\.Test\b|\borg\.junit\.runner\b|SpringJUnit4ClassRunner|\bSpringRunner\b",
       "JUnit 4 is maintenance-only and deprecated by Spring Framework 7 — report it even when the JUnit toggle is off."),
    _m("Java 8 compiler level", r"<(?:source|target)>1\.8</(?:source|target)>|<maven\.compiler\.(?:source|target)>1\.8<|(?:source|target)Compatibility\s*=\s*['\"]?1\.8",
       "The compiler level never left Java 8 — expected only if the run stopped before the Java 17 stage."),
    _m("dead build plugin", r"maven-svn-revision-number-plugin|cargo-maven2-plugin",
       "Dead build cruft removed in the readiness stage."),
]

_JAVA_MODERN = [
    _m("jakarta namespace", r"\bjakarta\.(?:servlet|persistence|validation|annotation|transaction|ws\.rs|ejb|jms|mail|xml\.bind)\b"),
    _m("modern compiler release", r"<release>(?:1[1-9]|2[0-9])</release>|<maven\.compiler\.release>|(?:source|target)Compatibility\s*=\s*['\"]?(?:1[1-9]|2[0-9])"),
    _m("Spring Boot starter", r"spring-boot-starter|spring-boot-maven-plugin|org\.springframework\.boot"),
    _m("Spring 5+ hibernate5 support", r"org\.springframework\.orm\.hibernate5"),
    _m("Jackson 2", r"\bcom\.fasterxml\.jackson\b|\bjackson-bom\b"),
    _m("Jackson 3", r"\btools\.jackson\b|JsonMapper\.builder"),
    _m("jackson blackbird", r"jackson-module-blackbird"),
    _m("Ehcache 3", r"\borg\.ehcache\b|JCacheCacheManager|\bhibernate-jcache\b"),
    _m("SLF4J", r"\borg\.slf4j\b|\blogback\b"),
    _m("JUnit Jupiter", r"org\.junit\.jupiter|\bjunit-jupiter\b|\bjunit-bom\b"),
    _m("mockito-core", r"\bmockito-core\b"),
    _m("modern surefire/failsafe", r"maven-(?:surefire|failsafe)-plugin"),
    _m("modern Guava", r"\bguava-bom\b|MoreObjects|Stopwatch\.create|directExecutor\s*\("),
    _m("ojdbc11", r"\bojdbc11\b"),
    _m("Spring Data JPA", r"spring-boot-starter-data-jpa|org\.springframework\.data\.jpa"),
]

_JAVA_FORBIDDEN = [
    _m("--add-opens / --add-exports escape hatch", r"--add-(?:opens|exports)\b",
       "The java-8-to-25-fix skill is explicit: this silences InaccessibleObjectException instead of removing the stale library. Never the fix."),
    _m("dependency pinned backwards", r"<!--\s*(?:downgrade|pin back|revert)\b",
       "A deliberate downgrade to make a build pass is a migration failure, not a fix."),
]

_SOLR_LEGACY = [
    _m("SolrJ 4 server classes", r"\b(?:Http|Cloud|Concurrent|LBHttp)Solr(?:Server)\b",
       "Renamed to *SolrClient with builder construction in SolrJ 5+."),
    _m("Trie field types", r"solr\.Trie\w*Field",
       "Removed in Solr 9 — Point field types with docValues."),
    _m("legacy solrconfig", r"<luceneMatchVersion>\s*4\.|\bsolr\.clustering\b",
       "luceneMatchVersion still on 4.x, or a contrib removed in Solr 9."),
]

_SOLR_MODERN = [
    _m("SolrJ client classes", r"\b(?:Http2?|Cloud|LBHttp2?)Solr(?:Client)\b"),
    _m("Point field types", r"solr\.\w*PointField"),
    _m("modern luceneMatchVersion", r"<luceneMatchVersion>\s*9\."),
]

_ORACLE_LEGACY = [
    _m("LONG / LONG RAW column", r"\bLONG\s+RAW\b|\bLONG\b(?=\s*(?:,|\)|$))",
       "Deprecated since Oracle 8 — CLOB / BLOB.", re.IGNORECASE),
    _m("optimizer feature pin", r"optimizer_features_enable", "Pins the optimizer to an old release."),
    _m("legacy Oracle JDBC driver", r"\bojdbc(?:6|8|14)\b", "→ ojdbc11 for 23ai."),
]

_ORACLE_MODERN = [
    _m("LOB column", r"\bCLOB\b|\bBLOB\b"),
    _m("ojdbc11", r"\bojdbc11\b"),
    _m("23ai feature", r"\bJSON\s+DUALITY\b|\bVECTOR\b|IF\s+NOT\s+EXISTS", "", re.IGNORECASE),
]

_TIBCO_LEGACY = [
    _m("TIBCO EMS client", r"\bcom\.tibco\.tibjms\b|\btibjms\b|\btibjmsnaming\b",
       "The EMS transport is what this migration removes."),
    _m("JMS API", r"\bjavax\.jms\b|\bjakarta\.jms\b|\bQueueConnectionFactory\b|\bTopicConnectionFactory\b",
       "JMS client code becomes Pub/Sub Publisher/Subscriber."),
]

_TIBCO_MODERN = [
    _m("Pub/Sub client", r"com\.google\.cloud\.pubsub|\bPubsubMessage\b|\bPublisher\b|\bSubscriber\b"),
    _m("Pub/Sub dependency", r"google-cloud-pubsub|spring-cloud-gcp-pubsub"),
]

_JSP_LEGACY = [
    _m("JSP view", r"<%@|<%=|\bjsp:useBean\b|\bstruts\b", "Server-rendered JSP is what this migration replaces."),
    _m("JSTL / scriptlet tags", r"http://java\.sun\.com/jsp/jstl"),
]

_JSP_MODERN = [
    _m("React component", r"\bfrom\s+['\"]react['\"]|useState|useEffect|export\s+default\s+function"),
    _m("BFF REST controller", r"@RestController|@GetMapping|@PostMapping"),
]

LEGACY_MARKERS: dict[str, list[Marker]] = {
    "java-8-to-25": _JAVA_LEGACY,
    "solr-4-to-9": _SOLR_LEGACY,
    "oracle-19c-to-23ai": _ORACLE_LEGACY,
    "tibco-ems-to-pubsub": _TIBCO_LEGACY,
    "jsp-to-react-bff": _JSP_LEGACY,
}

MODERN_MARKERS: dict[str, list[Marker]] = {
    "java-8-to-25": _JAVA_MODERN,
    "solr-4-to-9": _SOLR_MODERN,
    "oracle-19c-to-23ai": _ORACLE_MODERN,
    "tibco-ems-to-pubsub": _TIBCO_MODERN,
    "jsp-to-react-bff": _JSP_MODERN,
}

FORBIDDEN_MARKERS: dict[str, list[Marker]] = {
    "java-8-to-25": _JAVA_FORBIDDEN,
}


class MarkerHit(TypedDict):
    marker: str
    line: str
    note: str


class ChangedFileAudit(TypedDict):
    path: str
    status: str
    legacy_removed: list[MarkerHit]
    modern_added: list[MarkerHit]
    legacy_added: list[MarkerHit]
    forbidden_added: list[MarkerHit]


class UnchangedFileAudit(TypedDict):
    path: str
    legacy_present: list[MarkerHit]


@dataclass
class ChangeAudit:
    pattern: str
    markers_configured: bool
    changed_total: int = 0
    unchanged_total: int = 0
    unchanged_scanned: int = 0
    explained: list[ChangedFileAudit] = field(default_factory=list)
    unexplained: list[ChangedFileAudit] = field(default_factory=list)
    regressions: list[ChangedFileAudit] = field(default_factory=list)
    residual_legacy: list[UnchangedFileAudit] = field(default_factory=list)
    error: str = ""


def _clip(line: str) -> str:
    line = line.strip()
    return line if len(line) <= _MAX_LINE_CHARS else line[:_MAX_LINE_CHARS] + " …"


def _scan(lines: list[str], markers: list[Marker]) -> list[MarkerHit]:
    """First `_MAX_HITS_PER_FILE` distinct markers matched anywhere in *lines*."""
    hits: list[MarkerHit] = []
    seen: set[str] = set()
    for line in lines:
        for marker in markers:
            if marker.name in seen:
                continue
            if marker.pattern.search(line):
                seen.add(marker.name)
                hits.append({"marker": marker.name, "line": _clip(line), "note": marker.note})
                if len(hits) >= _MAX_HITS_PER_FILE:
                    return hits
    return hits


def relevant_files(root: Path) -> dict[str, Path]:
    """`{relative path: absolute path}` for every file that is really part of the
    repository — build output, VCS metadata and IDE folders excluded."""
    out: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if EXCLUDED_DIRS & set(rel.parts):
            continue
        out[str(rel)] = path
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def changed_file_statuses(baseline_dir: str, workspace_dir: str) -> dict[str, str]:
    """`{relative path: "added" | "modified" | "deleted"}` for every file that
    differs between the pristine baseline and the migrated workspace.

    Shared with plan_coverage.py, so the marker audit and the plan-conformance
    check can never disagree about which files this run actually touched.
    """
    baseline_root = Path(baseline_dir).resolve() if baseline_dir else None
    workspace_root = Path(workspace_dir).resolve() if workspace_dir else None
    if not baseline_root or not baseline_root.exists() or not workspace_root or not workspace_root.exists():
        return {}

    before = relevant_files(baseline_root)
    after = relevant_files(workspace_root)
    statuses: dict[str, str] = {}
    for rel in sorted(set(before) | set(after)):
        if rel not in after:
            statuses[rel] = "deleted"
        elif rel not in before:
            statuses[rel] = "added"
        elif _read(before[rel]) != _read(after[rel]):
            statuses[rel] = "modified"
    return statuses


def audit_changes(baseline_dir: str, workspace_dir: str, pattern: str) -> ChangeAudit:
    """Compare the pristine baseline against the migrated workspace and classify
    every file as explained / unexplained / regressed / residually legacy."""
    legacy = LEGACY_MARKERS.get(pattern, [])
    modern = MODERN_MARKERS.get(pattern, [])
    forbidden = FORBIDDEN_MARKERS.get(pattern, [])
    audit = ChangeAudit(pattern=pattern, markers_configured=bool(legacy or modern))

    baseline_root = Path(baseline_dir).resolve() if baseline_dir else None
    workspace_root = Path(workspace_dir).resolve() if workspace_dir else None
    if not baseline_root or not baseline_root.exists() or not workspace_root or not workspace_root.exists():
        audit.error = "baseline or workspace directory is unavailable — change audit could not run"
        return audit

    before = relevant_files(baseline_root)
    after = relevant_files(workspace_root)

    for rel in sorted(set(before) | set(after)):
        before_text = _read(before[rel]) if rel in before else ""
        after_text = _read(after[rel]) if rel in after else ""

        if rel in before and rel in after and before_text == after_text:
            audit.unchanged_total += 1
            if Path(rel).suffix.lower() in _SCAN_SUFFIXES and legacy:
                audit.unchanged_scanned += 1
                present = _scan(after_text.splitlines(), legacy)
                if present:
                    audit.residual_legacy.append({"path": rel, "legacy_present": present})
            continue

        audit.changed_total += 1
        if rel not in after:
            status = "deleted"
        elif rel not in before:
            status = "added"
        else:
            status = "modified"

        removed_lines: list[str] = []
        added_lines: list[str] = []
        for line in difflib.unified_diff(
            before_text.splitlines(), after_text.splitlines(), lineterm="", n=0
        ):
            if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
                continue
            if line.startswith("-"):
                removed_lines.append(line[1:])
            elif line.startswith("+"):
                added_lines.append(line[1:])

        entry: ChangedFileAudit = {
            "path": rel,
            "status": status,
            "legacy_removed": _scan(removed_lines, legacy),
            "modern_added": _scan(added_lines, modern),
            "legacy_added": _scan(added_lines, legacy),
            "forbidden_added": _scan(added_lines, forbidden),
        }

        if entry["forbidden_added"] or entry["legacy_added"]:
            audit.regressions.append(entry)
        if entry["legacy_removed"] or entry["modern_added"]:
            audit.explained.append(entry)
        elif not entry["forbidden_added"] and not entry["legacy_added"]:
            audit.unexplained.append(entry)

    return audit


# ---------------------------------------------------------------------------
# Rendering — the tool returns markdown, since its only consumer is an LLM
# reviewer that has to quote this evidence back in its report.
# ---------------------------------------------------------------------------

def _render_hits(hits: list[MarkerHit], label: str) -> list[str]:
    out: list[str] = []
    for hit in hits:
        note = f" — {hit['note']}" if hit["note"] else ""
        out.append(f"    - {label} `{hit['marker']}`: `{_clip(hit['line'])}`{note}")
    return out


def _truncate_note(shown: int, total: int) -> list[str]:
    if total > shown:
        return [f"  _(… and {total - shown} more — the same adjudication applies)_"]
    return []


def to_markdown(audit: ChangeAudit) -> str:
    if audit.error:
        return f"# Change Audit\n\nERROR: {audit.error}"

    lines = [
        "# Change Audit (deterministic — baseline vs. migrated workspace)",
        "",
        f"- Pattern: `{audit.pattern}`",
        f"- Files changed: **{audit.changed_total}**",
        f"- Files unchanged: **{audit.unchanged_total}** ({audit.unchanged_scanned} of them scannable source/config)",
    ]
    if not audit.markers_configured:
        lines += [
            "",
            f"No relevance markers are configured for `{audit.pattern}`, so the two relevance "
            "questions below are yours to answer from the plan and the files alone — this audit "
            "only supplies the changed/unchanged split.",
        ]

    if audit.changed_total == 0:
        lines += [
            "",
            "## ⚠ Nothing changed",
            "",
            "The migrated workspace is byte-identical to the uploaded baseline. No migration work "
            "landed at all. This is a CRITICAL finding regardless of what the modify results or the "
            "build result claim — report it as the headline finding and do not describe the run as "
            "successful.",
        ]
        return "\n".join(lines)

    # 1 — changes that carry no migration signal.
    lines += ["", "## 1. Changed files with no migration signal", ""]
    if not audit.unexplained:
        lines.append("None — every changed file removed a legacy marker or added a modern one.")
    else:
        lines.append(
            "These files were rewritten, but the diff neither removed a known legacy marker nor "
            "added a known target-stack one. Read each one and decide: legitimate collateral work "
            "the plan called for (a call site updated because its dependency moved, a rename that "
            "propagated), or unrequested scope creep / a gratuitous reformat? Report the second kind."
        )
        lines.append("")
        for entry in audit.unexplained[:_MAX_FILES_PER_BUCKET]:
            lines.append(f"- `{entry['path']}` ({entry['status']})")
        lines += _truncate_note(_MAX_FILES_PER_BUCKET, len(audit.unexplained))

    # 2 — regressions.
    lines += ["", "## 2. Regressions introduced by the migration", ""]
    if not audit.regressions:
        lines.append("None — no legacy or forbidden marker appears in any added line.")
    else:
        lines.append(
            "An added line re-introduces a legacy marker, or uses a fix the skills forbid. Each of "
            "these is a HIGH or CRITICAL finding unless the plan explicitly authorised it."
        )
        lines.append("")
        for entry in audit.regressions[:_MAX_FILES_PER_BUCKET]:
            lines.append(f"- `{entry['path']}` ({entry['status']})")
            lines += _render_hits(entry["forbidden_added"], "FORBIDDEN")
            lines += _render_hits(entry["legacy_added"], "legacy re-added")
        lines += _truncate_note(_MAX_FILES_PER_BUCKET, len(audit.regressions))

    # 3 — untouched files that still look legacy.
    lines += ["", "## 3. Unchanged files that still match a legacy marker", ""]
    if not audit.residual_legacy:
        lines.append(
            "None — no untouched source or config file still matches a legacy marker for this "
            "pattern. The unchanged files are, on this evidence, genuinely out of scope."
        )
    else:
        lines.append(
            "These files were never touched, yet still contain legacy markers. Each is either a **file "
            "the migration missed** (a real coverage gap — report it, naming the plan task that should "
            "have covered it) or **legitimately out of scope** (owned by a later stage, or excluded by "
            "a toggle the user left off, e.g. JUnit 3/4 when the JUnit upgrade was declined, or "
            "`javax.*` when no Spring Boot upgrade was requested). Check each against the confirmed "
            "plan and say which — do not report them as a list without adjudicating."
        )
        lines.append("")
        for entry in audit.residual_legacy[:_MAX_FILES_PER_BUCKET]:
            lines.append(f"- `{entry['path']}`")
            lines += _render_hits(entry["legacy_present"], "still present")
        lines += _truncate_note(_MAX_FILES_PER_BUCKET, len(audit.residual_legacy))

    # 4 — the explained majority, as a count only.
    lines += [
        "",
        "## 4. Changed files carrying a clear migration signal",
        "",
        f"{len(audit.explained)} file(s) removed a legacy marker and/or added a target-stack one. "
        "These need no relevance justification — review them for correctness as usual.",
    ]
    for entry in audit.explained[:_MAX_FILES_PER_BUCKET]:
        signals = [h["marker"] for h in entry["legacy_removed"]] + [h["marker"] for h in entry["modern_added"]]
        lines.append(f"- `{entry['path']}` ({entry['status']}): {', '.join(signals)}")
    lines += _truncate_note(_MAX_FILES_PER_BUCKET, len(audit.explained))

    lines += [
        "",
        "---",
        "",
        "Markers are regex heuristics, biased towards recall: they flag candidates, they do not "
        "return verdicts. Adjudicate every entry against the confirmed plan before writing a finding, "
        "and never report a marker hit you could not confirm by reading the file. In a companion-"
        "bundle run all patterns share one workspace, so a change another pattern's migration made "
        "will appear here as unexplained — check before calling it scope creep.",
    ]
    return "\n".join(lines)


def audit_migration_changes(tool_context: ToolContext) -> str:
    """Audit what this migration run actually changed, before reviewing any file.

    Compares the pristine uploaded repository against the migrated workspace and
    reports, with the matched line as evidence: files changed with no migration
    signal (possible scope creep), legacy APIs re-introduced or forbidden fixes
    applied (regressions), and untouched files that still match a legacy marker
    (possible coverage gaps). Call this FIRST — it tells you which files are
    worth reading and is the only way to see what was left untouched.

    Returns:
        A markdown change-audit report, or a report whose body says the audit
        could not run if the baseline snapshot is unavailable.
    """
    state = tool_context.state or {}
    return to_markdown(audit_changes(
        state.get("baseline_dir", ""),
        state.get("workspace_dir", ""),
        state.get("pattern", ""),
    ))
