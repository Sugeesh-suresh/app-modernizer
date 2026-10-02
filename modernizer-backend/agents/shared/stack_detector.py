"""
Stack discovery, pass 1: which technology stacks a repository is built on,
derived from the repository itself rather than chosen by the user.

Facts come from repo_fingerprint (parsed build manifests, import declarations —
Python through its AST — script includes, vendored libraries and per-language
file counts) plus a content scan for signatures that live in configuration
rather than in any manifest (JDBC URLs, WildFly descriptors, JSP directives).

`CATALOG` maps those facts to named stacks and to the checklist the discovery
agent documents each one with. It is a dictionary of names, not the limit of
what can be found:

- any programming language with source files that no detected stack accounts
  for becomes a stack of its own ("Python code", "Go code", …), documented with
  the general checklist;
- the dependency mapper agent (pass 2) reviews the result against the files and
  may add any stack under any id — see main._merge_mapper_result.

Every stack carries the `path: finding` evidence that produced it. No versions
and no confidence scores: a version is a fact for the documenting agent to read
and cite, and the evidence list is the confidence signal.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import repo_fingerprint
from .companion_detector import (
    ORACLE_PATTERNS,
    SOLR_PATTERNS,
    TIBCO_EMS_PATTERNS,
    scannable_files,
)

#: Files whose content is scanned for configuration-level signatures.
_SCAN_SUFFIXES = {
    ".xml", ".properties", ".yml", ".yaml", ".java", ".gradle", ".kts", ".py", ".js", ".ts",
    ".jsp", ".jspx", ".jspf", ".tag", ".tagx", ".tld", ".mf", ".conf", ".json", ".env",
}

_MAX_EVIDENCE_PER_STACK = 5

#: Section order in the document: what the application runs on, then what it is.
KIND_ORDER = ("server", "database", "search", "messaging", "web-tier", "frontend", "service",
              "application", "language")


@dataclass(frozen=True)
class StackSpec:
    pattern: str                     # the stack id (kept as `pattern`: the API and UI key on it)
    label: str
    kind: str                        # one of KIND_ORDER
    reference: str = "general.md"    # stack-discovery-re checklist ("" = documented by its own runner)
    filenames: tuple[str, ...] = ()  # lowercased basenames that are evidence on their own
    suffixes: tuple[str, ...] = ()   # extensions that are evidence on their own
    content: tuple[re.Pattern, ...] = field(default_factory=tuple)
    deps: tuple[str, ...] = ()       # regexes over declared dependency names (any manifest kind)
    imports: tuple[str, ...] = ()    # regexes over imported modules/packages (any language)
    scripts: tuple[str, ...] = ()    # library names loaded by <script src> or committed as files
    claims: tuple[str, ...] = ()     # languages this stack accounts for (no generic stack for them)
    unless: tuple[str, ...] = ()     # not reported when one of these stacks is


_JAVA_PATTERNS = (
    re.compile(r"maven\.compiler\.(?:source|target|release)"),
    re.compile(r"<source>\s*1\.[45678]\s*</source>"),
    re.compile(r"sourceCompatibility\s*=?\s*['\"]?1\.[45678]"),
    re.compile(r"\borg\.springframework\b"),
)

_JSP_PATTERNS = (
    re.compile(r"<%@\s*(?:page|taglib|include)\b"),
    re.compile(r"\b(?:javax|jakarta)\.servlet\.jsp\b"),
    re.compile(r"<jsp:(?:include|forward|useBean)\b"),
    re.compile(r"InternalResourceViewResolver"),
)

# `urn:jboss:domain` and `java:jboss/` are the load-bearing ones: they appear in
# WildFly/JBoss server config and JNDI names and essentially nowhere else. The
# plugin coordinates are equally specific. Deliberately NOT matching a bare
# "jboss" or "org.jboss.logging", which turn up as transitive dependencies of
# libraries in applications that never run on WildFly at all.
_WILDFLY_PATTERNS = (
    re.compile(r"urn:jboss:domain"),
    re.compile(r"urn:jboss:deployment-structure"),
    re.compile(r"java:(?:jboss|global)/"),
    re.compile(r"\b(?:wildfly|jboss-as)-maven-plugin\b"),
    re.compile(r"\borg\.jboss\.as\b"),
    re.compile(r"\bjboss-eap\b|\bwildfly-dist\b"),
)


def _rx(*patterns: str) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


_SPA = ("JavaScript", "JavaScript (JSX)", "TypeScript", "TypeScript (TSX)", "Handlebars", "Mustache", "EJS")

CATALOG: tuple[StackSpec, ...] = (
    # ── servers ──
    StackSpec("wildfly", "WildFly / JBoss (app server)", "server", reference="",
              filenames=("jboss-deployment-structure.xml", "jboss-web.xml", "jboss-ejb3.xml",
                         "standalone.xml", "standalone-full.xml", "domain.xml", "jboss-app.xml"),
              content=_WILDFLY_PATTERNS),
    StackSpec("tomcat", "Apache Tomcat (servlet container)", "server",
              filenames=("catalina.properties",), content=_rx(r"<Context\b[^>]*docBase", r"\bCatalina\b",
                                                                 r"\btomcat7-maven-plugin\b|\btomcat-maven-plugin\b")),
    StackSpec("weblogic", "Oracle WebLogic (app server)", "server",
              filenames=("weblogic.xml", "weblogic-application.xml", "weblogic-ejb-jar.xml")),
    StackSpec("websphere", "IBM WebSphere (app server)", "server",
              filenames=("ibm-web-bnd.xml", "ibm-web-ext.xml", "ibm-web-bnd.xmi", "ibm-application-bnd.xml")),
    # ── data stores ──
    StackSpec("oracle", "Oracle Database", "database", reference="oracle.md",
              suffixes=(".pks", ".pkb", ".pls"), content=tuple(ORACLE_PATTERNS),
              deps=(r"ojdbc", r"^oracledb$", r"^cx[-_]oracle$"), imports=(r"^oracle\.jdbc", r"^cx_oracle$", r"^oracledb$"),
              claims=("PL/SQL", "SQL")),
    StackSpec("postgresql", "PostgreSQL", "database", reference="datastore.md",
              content=_rx(r"jdbc:postgresql:", r"postgres(?:ql)?://"),
              deps=(r"^org\.postgresql:postgresql$", r"^psycopg", r"^pg$", r"^npgsql$"), claims=("SQL",)),
    StackSpec("mysql", "MySQL / MariaDB", "database", reference="datastore.md",
              content=_rx(r"jdbc:(?:mysql|mariadb):", r"mysql://"),
              deps=(r"mysql-connector", r"mariadb-java-client", r"^mysql2?$", r"^pymysql$", r"^mysqlclient$"),
              claims=("SQL",)),
    StackSpec("sqlserver", "Microsoft SQL Server", "database", reference="datastore.md",
              content=_rx(r"jdbc:sqlserver:", r"jdbc:jtds:"), deps=(r"mssql-jdbc", r"^jtds", r"^mssql$", r"^pyodbc$"),
              claims=("SQL",)),
    StackSpec("db2", "IBM Db2", "database", reference="datastore.md",
              content=_rx(r"jdbc:db2:"), deps=(r"db2jcc",), claims=("SQL",)),
    StackSpec("mongodb", "MongoDB", "database", reference="datastore.md",
              content=_rx(r"mongodb(?:\+srv)?://"), deps=(r"mongo", r"^mongoose$"), imports=(r"^com\.mongodb", r"^pymongo$")),
    StackSpec("redis", "Redis", "database", reference="datastore.md",
              content=_rx(r"redis://"), deps=(r"jedis", r"lettuce-core", r"^redis$", r"^ioredis$"),
              imports=(r"^redis\.clients",)),
    # ── search ──
    StackSpec("solr", "Apache Solr", "search", reference="solr.md",
              filenames=("solrconfig.xml", "managed-schema"), content=tuple(SOLR_PATTERNS),
              deps=(r"solr",), imports=(r"^org\.apache\.solr",)),
    StackSpec("elasticsearch", "Elasticsearch / OpenSearch", "search", reference="datastore.md",
              deps=(r"elasticsearch", r"opensearch"), imports=(r"^org\.elasticsearch", r"^co\.elastic", r"^org\.opensearch")),
    # ── messaging ──
    StackSpec("tibco-ems", "TIBCO EMS messaging", "messaging", reference="tibco-ems.md",
              content=tuple(TIBCO_EMS_PATTERNS), deps=(r"tibjms",), imports=(r"^com\.tibco\.tibjms",)),
    StackSpec("kafka", "Apache Kafka", "messaging", reference="messaging.md",
              deps=(r"kafka",), imports=(r"^org\.apache\.kafka", r"^kafka$", r"^kafkajs$")),
    StackSpec("activemq", "ActiveMQ / Artemis", "messaging", reference="messaging.md",
              content=_rx(r"\btcp://[^\s\"']+:61616"), deps=(r"activemq", r"artemis-jms"),
              imports=(r"^org\.apache\.activemq",)),
    StackSpec("rabbitmq", "RabbitMQ", "messaging", reference="messaging.md",
              content=_rx(r"amqps?://"), deps=(r"amqp-client", r"spring-rabbit", r"^pika$", r"^amqplib$"),
              imports=(r"^com\.rabbitmq",)),
    StackSpec("ibm-mq", "IBM MQ", "messaging", reference="messaging.md",
              deps=(r"com\.ibm\.mq",), imports=(r"^com\.ibm\.mq",)),
    # ── web tier ──
    StackSpec("jsp", "JSP / Servlet web tier", "web-tier", reference="jsp.md",
              suffixes=(".jsp", ".jspx", ".jspf", ".tag", ".tagx"), content=_JSP_PATTERNS, claims=("JSP",)),
    # ── front ends ──
    StackSpec("backbone", "Backbone.js front end", "frontend", reference="spa-frontend.md",
              deps=(r"^backbone", r"marionette"), imports=(r"^backbone", r"marionette"),
              scripts=("backbone", "backbone.marionette", "marionette"), claims=_SPA),
    StackSpec("react", "React front end", "frontend", reference="spa-frontend.md",
              deps=(r"^react$", r"^react-dom$", r"^next$"), imports=(r"^react$", r"^react-dom$"),
              scripts=("react", "react-dom", "react.production"), claims=_SPA),
    StackSpec("angular", "Angular front end", "frontend", reference="spa-frontend.md",
              deps=(r"^@angular/core$",), imports=(r"^@angular/core$",), claims=_SPA),
    StackSpec("angularjs", "AngularJS front end", "frontend", reference="spa-frontend.md",
              deps=(r"^angular$",), imports=(r"^angular$",), scripts=("angular",), claims=_SPA),
    StackSpec("vue", "Vue.js front end", "frontend", reference="spa-frontend.md",
              suffixes=(".vue",), deps=(r"^vue$", r"^nuxt$"), imports=(r"^vue$",), scripts=("vue",),
              claims=_SPA + ("Vue",)),
    StackSpec("ember", "Ember.js front end", "frontend", reference="spa-frontend.md",
              deps=(r"^ember-source$", r"^ember-cli$"), scripts=("ember",), claims=_SPA),
    StackSpec("extjs", "Ext JS front end", "frontend", reference="spa-frontend.md",
              scripts=("ext-all", "ext-all-debug", "ext"), claims=_SPA),
    StackSpec("jquery", "jQuery front end", "frontend", reference="spa-frontend.md",
              deps=(r"^jquery$",), imports=(r"^jquery$",), scripts=("jquery",), claims=_SPA,
              unless=("backbone", "react", "angular", "angularjs", "vue", "ember", "extjs", "jsp")),
    # ── services ──
    StackSpec("nodejs", "Node.js service", "service", reference="general.md",
              deps=(r"^express$", r"^koa$", r"^fastify$", r"^@nestjs/core$", r"^@hapi/hapi$", r"^hapi$"),
              imports=(r"^express$", r"^koa$", r"^fastify$", r"^@nestjs/core$"),
              claims=("JavaScript", "TypeScript")),
    # ── applications ──
    StackSpec("java", "Java application", "application", reference="java.md",
              suffixes=(".java",), content=_JAVA_PATTERNS, claims=("Java",)),
)

STACK_ORDER: list[str] = [s.pattern for s in CATALOG]
STACK_LABELS: dict[str, str] = {s.pattern: s.label for s in CATALOG}
_BY_ID = {s.pattern: s for s in CATALOG}

#: Stacks documented by a dedicated runner instead of the stack-discovery agent.
#: id -> (PATTERN_RUNNERS key, step key)
DEDICATED_RUNNERS: dict[str, tuple[str, str]] = {"wildfly": ("wildfly", "re")}

#: Languages that are programs (a generic stack is created for them when no
#: detected stack accounts for them). Markup, config and data formats are not.
PROGRAMMING_LANGUAGES = {
    "Java", "Kotlin", "Scala", "Groovy", "JavaScript", "JavaScript (JSX)", "TypeScript", "TypeScript (TSX)",
    "Vue", "Svelte", "Python", "Ruby", "PHP", "Go", "C#", "VB.NET", "C", "C++", "Rust", "Swift", "SQL",
    "PL/SQL", "Shell", "PowerShell", "COBOL", "Perl", "R", "JSP",
}
_LANGUAGE_FAMILY = {"JavaScript (JSX)": "JavaScript", "TypeScript (TSX)": "TypeScript"}
_GENERIC_MIN_FILES = 2


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower().replace("#", "sharp").replace("+", "p")).strip("-")
    return s or "stack"


def kind_rank(kind: str) -> int:
    return KIND_ORDER.index(kind) if kind in KIND_ORDER else len(KIND_ORDER)


def order(stacks: list[dict]) -> list[dict]:
    """Document order: by kind, catalog order within a kind, then first seen."""
    pos = {p: i for i, p in enumerate(STACK_ORDER)}
    return sorted(stacks, key=lambda s: (kind_rank(s.get("kind", "")), pos.get(s["pattern"], len(pos))))


def reference_for(stack_id: str, kind: str = "") -> str:
    spec = _BY_ID.get(stack_id)
    if spec:
        return spec.reference
    return {"database": "datastore.md", "search": "datastore.md", "messaging": "messaging.md",
            "frontend": "spa-frontend.md", "web-tier": "jsp.md"}.get(kind, "general.md")


def detect(workspace_dir: str) -> tuple[list[dict], dict]:
    """(stacks, fingerprint). Each stack:
    {"pattern", "label", "kind", "reference", "evidence": [str, ...]} — at least one evidence line."""
    root = Path(workspace_dir).resolve()
    if not root.exists():
        return [], repo_fingerprint.fingerprint(workspace_dir)
    fp = repo_fingerprint.fingerprint(str(root))
    evidence: dict[str, list[str]] = {s.pattern: [] for s in CATALOG}

    def add(stack: str, line: str):
        hits = evidence[stack]
        if len(hits) < _MAX_EVIDENCE_PER_STACK and line not in hits:
            hits.append(line)

    # Declared dependencies.
    for m in fp["manifests"]:
        for d in m["dependencies"]:
            for spec in CATALOG:
                if any(re.search(rx, d["name"], re.IGNORECASE) for rx in spec.deps):
                    version = f" {d['version']}" if d["version"] else ""
                    scope = f" ({d['scope']} scope)" if d["scope"] else ""
                    add(spec.pattern, f"{m['path']}: declares `{d['name']}`{version}{scope}")
    # Imports in the code.
    for eco, mods in fp["imports"].items():
        for mod, info in mods.items():
            for spec in CATALOG:
                if any(re.search(rx, mod, re.IGNORECASE) for rx in spec.imports):
                    add(spec.pattern, f"{info['samples'][0]}: imports `{mod}` ({info['files']} file"
                                      f"{'s' if info['files'] != 1 else ''})")
    # Script includes and committed library files.
    for source, verb in ((fp["scripts"], "loads"), (fp["vendored"], "commits")):
        for lib, paths in source.items():
            for spec in CATALOG:
                if lib in spec.scripts:
                    add(spec.pattern, f"{paths[0]}: {verb} `{lib}`" + (" library" if verb == "commits" else " script"))

    # File names, extensions and configuration-level signatures.
    for path in scannable_files(root, _SCAN_SUFFIXES | {s for spec in CATALOG for s in spec.suffixes}):
        rel = path.relative_to(root).as_posix()
        name, suffix = path.name.lower(), path.suffix.lower()
        text: str | None = None
        for spec in CATALOG:
            if len(evidence[spec.pattern]) >= _MAX_EVIDENCE_PER_STACK:
                continue
            if name in spec.filenames or (suffix and suffix in spec.suffixes):
                add(spec.pattern, f"{rel}: present")
                continue
            if not spec.content:
                continue
            if text is None:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace") if path.stat().st_size < 2_000_000 else ""
                except OSError:
                    text = ""
            if not text:
                continue
            for rx in spec.content:
                match = rx.search(text)
                if match:
                    add(spec.pattern, f"{rel}: matched `{match.group(0).strip()[:80]}`")
                    break

    found = {p for p, hits in evidence.items() if hits}
    stacks = [
        {"pattern": s.pattern, "label": s.label, "kind": s.kind, "reference": s.reference,
         "evidence": evidence[s.pattern]}
        for s in CATALOG if s.pattern in found and not (set(s.unless) & found)
    ]

    # Languages nothing above accounts for become stacks of their own.
    claimed = {lang for s in CATALOG if s.pattern in {x["pattern"] for x in stacks} for lang in s.claims}
    families: dict[str, list] = {}
    for lang, info in fp["languages"].items():
        if lang not in PROGRAMMING_LANGUAGES or lang in claimed:
            continue
        families.setdefault(_LANGUAGE_FAMILY.get(lang, lang), []).append(info)
    for lang, infos in families.items():
        files = sum(i["files"] for i in infos)
        if files < _GENERIC_MIN_FILES or lang in claimed:
            continue
        samples = [s for i in infos for s in i["samples"]][:3]
        stacks.append({
            "pattern": slug(lang), "label": f"{lang} code", "kind": "language", "reference": "general.md",
            "evidence": [f"{s}: {lang} source ({files} {lang} files in the repository)" for s in samples],
        })
    return order(stacks), fp


def detect_stacks(workspace_dir: str) -> list[dict]:
    return detect(workspace_dir)[0]


def to_markdown(stacks: list[dict], source: str = "deterministic scan") -> str:
    """The stack inventory table that opens the combined document. The evidence
    travels with each finding so a reviewer can check it rather than trust it."""
    if not stacks:
        return (
            "## Detected Technology Stacks\n\n"
            "No stack was detected. Nothing below should be read as a statement that the "
            "repository is empty."
        )
    lines = ["## Detected Technology Stacks", "",
             f"Detected by {source}. Every row carries the evidence that produced it.", "",
             "| Stack | Id | Kind | Evidence |", "|---|---|---|---|"]
    for stack in stacks:
        cited = "<br>".join(_format_evidence(e) for e in stack["evidence"][:_MAX_EVIDENCE_PER_STACK])
        lines.append(f"| {stack['label']} | `{stack['pattern']}` | {stack.get('kind') or '—'} | {cited or '—'} |")
    return "\n".join(lines)


def _format_evidence(line: str) -> str:
    """One `path: finding` evidence line, as a table cell.

    Only the path is wrapped in backticks. The finding half already carries its
    own backticks around the matched text (`matched \\`ojdbc8\\``), and wrapping
    the whole line would nest them and break the code span in both the rendered
    document and the UI.
    """
    path, _, rest = line.partition(": ")
    cell = f"`{path}` — {rest}" if rest else f"`{line}`"
    # A pipe anywhere in a cell ends the column early, so escape it.
    return cell.replace("|", "\\|")
