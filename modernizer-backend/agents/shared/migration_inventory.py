"""
Deterministic migration inventories: the analysis step of the Java 8 -> 25,
Solr 4 -> 9, Oracle 19c -> 23ai and TIBCO EMS -> Pub/Sub pipelines, without a
language model.

The reverse-engineering agents read code through an agent loop that resends
everything read so far on every call (measured at 5.7x-21x the size of the
source), which exhausts tokens-per-minute quotas (429) on large repositories.
The planners of these pipelines need facts — versions, the files that use each
legacy construct, the objects and destinations involved — and those facts are
mechanical. This module derives them by reading every relevant file once, and
renders them in the four-section format the agents produced, so the review
screen, the planners and the code steps are unchanged.

The per-file legacy checks for each pattern are the same markers the code
reviewer's change audit uses (agents/shared/change_audit.py LEGACY_MARKERS),
so what the plan is built from and what the result is audited against cannot
drift apart. JSP -> React and stack discovery still use their agents: their
output is a description of the application, not a checklist.

What an inventory does not do: infer business intent, or decide whether a
match is live code or a comment. The document says so; the planner and the
modifier (which reads every file before changing it) make those calls.
"""
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from .change_audit import LEGACY_MARKERS, Marker
from .dependency_graph import EXCLUDED_DIRS
from .evidence import redact, sample
from .pom_facts import parse_pom, resolver
from ..java_8_to_11.inventory import CATEGORIES as JAVA11_CATEGORIES, ENDPOINTS, TEST_FRAMEWORKS, _URL_PATTERN

_MAX_FILE_BYTES = 5_000_000
_JAVA_BUILD = {".java", ".xml", ".properties", ".gradle", ".kts", ".yml", ".yaml"}


def _m(name: str, regex: str, note: str, flags: int = 0) -> Marker:
    return Marker(name, re.compile(regex, flags), note)


@dataclass
class Scan:
    """Everything read from the repository, once."""
    root: Path
    files: list[str]
    texts: dict[str, str]
    skipped_large: list[str]
    poms: dict
    resolve: Callable
    managed_version: Callable


@dataclass(frozen=True)
class Spec:
    pattern: str
    title: str
    objective: str
    out_of_scope: str
    suffixes: frozenset
    checks: tuple            # Marker, one row per file per check
    dependency_filter: str   # regex on "group:artifact" for the Repo Facts dependency table
    tables: tuple = ()       # (heading, extractor(scan) -> list[str] of markdown rows incl. header)
    behaviour: Callable | None = None   # scan -> list of (kind, value, where) to preserve


# ---------------------------------------------------------------------------
# Pattern-specific extractors
# ---------------------------------------------------------------------------

def _rows(header: str, rows: list[str], empty: str) -> list[str]:
    cols = header.count("|") - 1
    return [header, "|" + "---|" * cols] + (rows or [empty])


def _java_endpoints(scan: Scan) -> list[tuple]:
    out = []
    for rel, text in scan.texts.items():
        if rel.endswith(".java") and "/src/test/" not in f"/{rel}":
            for kind, rx in ENDPOINTS:
                for m in rx.finditer(text):
                    value = (m.group(1) if m.groups() and m.group(1) else "").strip()[:120]
                    out.append((kind, value, f"{rel}:{text.count(chr(10), 0, m.start()) + 1}"))
        elif PurePosixPath(rel).name == "web.xml":
            out += [("web.xml url-pattern", m.group(1), rel) for m in _URL_PATTERN.finditer(text)]
    return out


def _packaging(scan: Scan) -> list[str]:
    rows = []
    for rel, pom in sorted(scan.poms.items()):
        rows.append(f"| `{rel}` | {pom.packaging} | {pom.final_name or '—'} |")
    extra = []
    for rel, text in sorted(scan.texts.items()):
        name = PurePosixPath(rel).name
        if name == "web.xml":
            count = lambda tag: len(re.findall(rf"<{tag}>", text))
            extra.append(f"- `{rel}`: {count('servlet')} servlet(s), {count('filter')} filter(s), "
                         f"{count('listener')} listener(s), {count('security-constraint')} security constraint(s)")
        elif name.startswith("jboss-") and name.endswith(".xml") or name.endswith("-ds.xml"):
            extra.append(f"- `{rel}`: container descriptor")
        elif rel.endswith(".java") and "SpringBootServletInitializer" in text:
            extra.append(f"- `{rel}`: extends SpringBootServletInitializer")
    dockerfiles = [f for f in scan.files if PurePosixPath(f).name.lower().startswith("dockerfile")]
    extra += [f"- `{f}`: Dockerfile" for f in dockerfiles]
    return _rows("| POM | Packaging | finalName |", rows, "| — | — | — |") + ([""] + extra if extra else [])


def _persistence_view(scan: Scan) -> list[str]:
    rows = []
    for rel, text in sorted(scan.texts.items()):
        kinds = []
        if rel.endswith(".java"):
            if re.search(r"@(?:[\w$]+\.)*Entity\b", text):
                kinds.append("JPA/Hibernate entity")
            if re.search(r"\bJdbcTemplate\b|\bNamedParameterJdbcTemplate\b", text):
                kinds.append("JdbcTemplate")
            if re.search(r"\bHibernateTemplate\b|\bSessionFactory\b|\bEntityManager\b", text):
                kinds.append("Hibernate/JPA session")
            if re.search(r"\bPreparedStatement\b|\bDriverManager\b", text):
                kinds.append("raw JDBC")
        elif rel.endswith(".hbm.xml"):
            kinds.append("Hibernate mapping file")
        elif rel.endswith(".xml") and re.search(r"<beans[\s>]", text):
            kinds.append("Spring XML context")
        if kinds:
            rows.append(f"| `{rel}` | {', '.join(kinds)} |")
    jsp = defaultdict(int)
    for f in scan.files:
        if PurePosixPath(f).suffix.lower() in (".jsp", ".jspf", ".jspx", ".tag", ".tagx"):
            jsp[str(PurePosixPath(f).parent)] += 1
    views = [f"| `{d}/` | {n} JSP/tag file(s) |" for d, n in sorted(jsp.items())]
    return _rows("| File | Persistence / configuration role |", rows, "| — | none found |") + \
        ["", "Views:", ""] + _rows("| Directory | Views |", views, "| — | no JSP views |")


def _solr_schema(scan: Scan) -> list[str]:
    rows, versions, libs = [], [], []
    for rel, text in sorted(scan.texts.items()):
        name = PurePosixPath(rel).name.lower()
        if not rel.endswith(".xml") and name != "managed-schema":
            continue
        for m in re.finditer(r"<fieldType\b[^>]*\bname=\"([^\"]+)\"[^>]*\bclass=\"([^\"]+)\"", text):
            used = len(re.findall(rf"\btype=\"{re.escape(m.group(1))}\"", text))
            rows.append(f"| `{rel}` | {m.group(1)} | `{m.group(2)}` | {used} |")
        versions += [f"| `{rel}` | `{m.group(1)}` |" for m in re.finditer(r"<luceneMatchVersion>\s*([^<\s]+)", text)]
        libs += [f"| `{rel}` | `{m.group(0)[:150]}` |" for m in re.finditer(r"<lib\b[^>]*/?>|<requestHandler\b[^>]*class=\"[^\"]+\"", text)]
    return _rows("| Schema file | fieldType | Class | Fields using it |", rows, "| — | — | — | none found |") + \
        ["", "luceneMatchVersion:", ""] + _rows("| File | Value |", versions, "| — | not found |") + \
        ["", "Libraries and request handlers:", ""] + _rows("| File | Declaration |", libs, "| — | none |")


_SQL_SUFFIXES = (".sql", ".pks", ".pkb", ".plsql", ".ddl", ".pls", ".prc", ".fnc", ".trg")
_SQL_OBJECT = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:EDITIONABLE\s+|NONEDITIONABLE\s+)?"
    r"(TABLE|VIEW|MATERIALIZED\s+VIEW|PROCEDURE|FUNCTION|PACKAGE\s+BODY|PACKAGE|TRIGGER|SEQUENCE|INDEX|TYPE|SYNONYM)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([\w$.\"]+)", re.IGNORECASE)


def _solr_behaviour(scan: Scan) -> list[tuple]:
    out = []
    for rel, text in sorted(scan.texts.items()):
        line = lambda m: f"{rel}:{text.count(chr(10), 0, m.start()) + 1}"
        if rel.endswith(".xml"):
            out += [("request handler", m.group(1), line(m))
                    for m in re.finditer(r"<requestHandler\b[^>]*\bname=\"([^\"]+)\"", text)]
            out += [("search component", m.group(1), line(m))
                    for m in re.finditer(r"<searchComponent\b[^>]*\bname=\"([^\"]+)\"", text)]
            out += [("update processor chain", m.group(1), line(m))
                    for m in re.finditer(r"<updateRequestProcessorChain\b[^>]*\bname=\"([^\"]+)\"", text)]
        elif rel.endswith(".java") and "/src/test/" not in f"/{rel}":
            out += [("SolrJ call", m.group(0), line(m))
                    for m in re.finditer(r"\.(?:query|add|addBean|addBeans|commit|deleteById|deleteByQuery|optimize)\s*\(", text)
                    if re.search(r"Solr(?:Server|Client)\b", text)]
    return out


def _oracle_behaviour(scan: Scan) -> list[tuple]:
    out = []
    for rel, text in sorted(scan.texts.items()):
        if PurePosixPath(rel).suffix.lower() in _SQL_SUFFIXES:
            out += [(re.sub(r"\s+", " ", m.group(1).upper()).lower(), m.group(2).strip('"'),
                     f"{rel}:{text.count(chr(10), 0, m.start()) + 1}")
                    for m in _SQL_OBJECT.finditer(text)
                    if not re.match(r"INDEX|SEQUENCE|SYNONYM", m.group(1), re.IGNORECASE)]
        elif rel.endswith(".java"):
            out += [("PL/SQL call from Java", m.group(1), f"{rel}:{text.count(chr(10), 0, m.start()) + 1}")
                    for m in re.finditer(r"prepareCall\s*\(\s*\"\{?\s*(?:\?\s*=\s*)?call\s+([\w$.]+)", text, re.IGNORECASE)]
    return out


def _sql_objects(scan: Scan) -> list[str]:
    rows = []
    totals: dict[str, int] = defaultdict(int)
    for rel, text in sorted(scan.texts.items()):
        if PurePosixPath(rel).suffix.lower() not in _SQL_SUFFIXES:
            continue
        found = defaultdict(list)
        for m in _SQL_OBJECT.finditer(text):
            kind = re.sub(r"\s+", " ", m.group(1).upper())
            found[kind].append(m.group(2).strip('"'))
            totals[kind] += 1
        if found:
            rows.append(f"| `{rel}` | " + "; ".join(f"{k}: {', '.join(v[:6])}{' …' if len(v) > 6 else ''}"
                                                   for k, v in sorted(found.items())) + " |")
    summary = [f"| {k} | {n} |" for k, n in sorted(totals.items())]
    return _rows("| Object type | Count |", summary, "| — | no CREATE statements found |") + [""] + \
        _rows("| File | Objects defined |", rows, "| — | none |")


def _jdbc_config(scan: Scan) -> list[str]:
    rows = []
    for rel, text in sorted(scan.texts.items()):
        for m in re.finditer(r"jdbc:oracle:[\w:@/.\-()=\s]+", text):
            url = redact(m.group(0).strip())[:120]
            rows.append(f"| `{rel}` | `{url}` |")
    return _rows("| File | JDBC URL (credentials redacted) |", rows[:200], "| — | none found |")


_DESTINATION = re.compile(
    r"\bcreate(Queue|Topic)\s*\(\s*\"([^\"]+)\"|@(?:[\w$]+\.)*JmsListener\s*\([^)]*destination\s*=\s*\"([^\"]+)\"|"
    r"\b(queue|topic)\.([\w.\-]+)\s*[=:]\s*([\w.\-]+)", re.IGNORECASE)
_SELECTOR = re.compile(
    r"\bcreate(?:Consumer|DurableSubscriber|Receiver)\s*\([^;]*?\"([^\"]*(?:=|<>|\bLIKE\b|\bIN\b|\bIS\b)[^\"]*)\"|"
    r"\bmessageSelector\s*[=:]\s*\"?([^\"\n]+)", re.IGNORECASE)
_ACK = re.compile(r"\bcreate(?:Queue|Topic)?Session\s*\(\s*(true|false)\s*,\s*(?:\w+\.)*(\w+)\s*\)|\bsetSessionTransacted\s*\(\s*true")


def _destinations(scan: Scan) -> list[str]:
    rows, sel, ack, urls, roles = [], [], [], [], []
    for rel, text in sorted(scan.texts.items()):
        for m in _DESTINATION.finditer(text):
            if m.group(2):
                kind, name = m.group(1).lower(), m.group(2)
            elif m.group(3):
                kind, name = "listener", m.group(3)
            else:
                kind, name = m.group(4).lower(), f"{m.group(5)} = {m.group(6)}"
            rows.append(f"| {kind} | `{name}` | `{rel}:{text.count(chr(10), 0, m.start()) + 1}` |")
        for m in _SELECTOR.finditer(text):
            value = (m.group(1) or m.group(2) or "").strip()[:150]
            sel.append(f"| `{value}` | `{rel}:{text.count(chr(10), 0, m.start()) + 1}` |")
        for m in _ACK.finditer(text):
            mode = f"transacted={m.group(1)}, {m.group(2)}" if m.group(1) else "transacted session (Spring)"
            ack.append(f"| {mode} | `{rel}:{text.count(chr(10), 0, m.start()) + 1}` |")
        for m in re.finditer(r"\b(?:tcp|ssl)://[\w.\-]+(?::\d+)?", text):
            urls.append(f"| `{m.group(0)}` | `{rel}` |")
        if rel.endswith(".java"):
            r = [n for n, rx in (("producer", r"\bMessageProducer\b|\bJmsTemplate\b|\.send\s*\("),
                                 ("consumer", r"\bMessageConsumer\b|\bMessageListener\b|\bonMessage\s*\(|@(?:[\w$]+\.)*JmsListener\b"))
                 if re.search(rx, text)]
            if r and re.search(r"\bjavax\.jms\b|\bjakarta\.jms\b|\bcom\.tibco\b|\bJmsTemplate\b", text):
                roles.append(f"| `{rel}` | {', '.join(r)} |")
    return _rows("| Kind | Destination | Where |", rows, "| — | none found | — |") + \
        ["", "Producers and consumers:", ""] + _rows("| File | Role |", roles, "| — | none found |") + \
        ["", "Message selectors:", ""] + _rows("| Selector | Where |", sel, "| none found | — |") + \
        ["", "Session acknowledgement / transactions:", ""] + _rows("| Mode | Where |", ack, "| none found | — |") + \
        ["", "EMS server URLs:", ""] + _rows("| URL | Where |", sorted(set(urls)), "| none found | — |")


def _tibco_behaviour(scan: Scan) -> list[tuple]:
    out = []
    for rel, text in scan.texts.items():
        for m in _DESTINATION.finditer(text):
            name = m.group(2) or m.group(3) or m.group(6)
            out.append(("destination", name, f"{rel}:{text.count(chr(10), 0, m.start()) + 1}"))
    return out


# ---------------------------------------------------------------------------
# The four pipelines
# ---------------------------------------------------------------------------

# The JDK-removal checks of the Java 11 inventory, with the WildFly-specific
# advice ("provided") replaced: on the way to 25 the artifact choice depends on
# whether the Jakarta stage is in the run, which the planner decides.
_JAVA11_AS_MARKERS = tuple(
    Marker(c.name, c.regex, "removed from the JDK by Java 11 — explicit dependency or rewrite")
    for c in JAVA11_CATEGORIES if c.change
)
_JAVA25_EXTRA = (
    _m("Nashorn", r"\bjdk\.nashorn\b|getEngineByName\s*\(\s*\"(?:nashorn|javascript|js)\"", "removed in Java 15 — GraalJS or a rewrite"),
    _m("Security Manager", r"\bSystem\.(?:set|get)SecurityManager\s*\(|\bAccessController\.doPrivileged\b",
       "permanently disabled in Java 24 — remove or replace"),
    _m("Thread stop/suspend/resume", r"\.(?:stop|suspend|resume)\s*\(\s*\)\s*;", "Thread.stop/suspend/resume throw on Java 20+ — check the receiver is a Thread"),
    _m("finalize()", r"\bprotected\s+void\s+finalize\s*\(", "finalization is deprecated for removal — Cleaner / try-with-resources"),
    _m("Hibernate Interceptor", r"\bextends\s+EmptyInterceptor\b|\bimplements\s+(?:[\w.]+\.)?Interceptor\b", "the Hibernate Interceptor SPI changed in 6"),
    _m("Hibernate C3P0 settings", r"hibernate\.c3p0\.", "superseded by the Spring Boot datasource pool"),
    _m("Jackson 1 Spring converter", r"MappingJacksonHttpMessageConverter\b|jackson-module-jaxb-annotations", "Jackson 1 / JAXB-annotation integration"),
    _m("Lombok", r"\blombok\.|<artifactId>lombok</artifactId>", "needs a Lombok release that supports the target JDK"),
    _m("tomcat7-maven-plugin", r"tomcat7-maven-plugin", "dead build plugin"),
)

SPECS: dict[str, Spec] = {
    "java-8-to-25": Spec(
        pattern="java-8-to-25", title="Java 8 → Java 25",
        objective="Compile and run the application on Java 25; with the Spring Boot option, on the newest "
                  "Spring Boot 4.x as an executable JAR. Business behaviour does not change.",
        out_of_scope="Business logic, API contracts, database schema and message contracts.",
        suffixes=frozenset(_JAVA_BUILD | {".jsp", ".jspf", ".tag"}),
        checks=tuple(LEGACY_MARKERS["java-8-to-25"]) + _JAVA11_AS_MARKERS + _JAVA25_EXTRA,
        dependency_filter=r".",
        tables=(("Packaging & Deployment Model", _packaging), ("Persistence & View Layer", _persistence_view)),
        behaviour=_java_endpoints,
    ),
    "solr-4-to-9": Spec(
        pattern="solr-4-to-9", title="Solr 4.x → Solr 9.x",
        objective="Solr configuration and SolrJ client code compatible with Solr 9.x; the same queries return "
                  "the same results after reindexing.",
        out_of_scope="Search relevance tuning, the indexing data model beyond required field-type changes, "
                     "and SolrCloud infrastructure.",
        suffixes=frozenset({".xml", ".java", ".json", ".properties", ".gradle", ".kts", ".txt"}),
        checks=tuple(LEGACY_MARKERS["solr-4-to-9"]) + (
            _m("LatLonType", r"solr\.LatLonType\b", "removed — solr.LatLonPointSpatialField"),
            _m("old schema version", r"<schema\b[^>]*\bversion=\"1\.[0-5]\"", "raise the schema version attribute (1.6+)"),
            _m("_version_ field", r"name=\"_version_\"", "must be indexed or docValues for optimistic concurrency / real-time get"),
            _m("Solr Cell extraction handler", r"ExtractingRequestHandler|/update/extract", "the extraction module must be enabled explicitly in Solr 9"),
            _m("removed spelling converter", r"SpellingQueryConverter", "removed in Solr 7"),
            _m("Solr 4 contrib lib path", r"<lib\b[^>]*\bdir=\"[^\"]*contrib", "contrib/ layout became modules/ in Solr 9"),
            _m("SolrCloud zkHost", r"\bzkHost\b|clusterstate\.json", "SolrCloud: per-collection state.json since Solr 5; CloudSolrClient builder"),
            _m("SolrJ setQueryType", r"\.setQueryType\s*\(", "removed — use setRequestHandler / the qt path"),
            _m("SolrJ 4 dependency", r"<artifactId>solr-(?:solrj|core)</artifactId>", "move to the Solr 9 SolrJ release"),
        ),
        dependency_filter=r"^org\.apache\.(?:solr|lucene)|solrj",
        tables=(("Schema & solrconfig.xml", _solr_schema),),
        behaviour=_solr_behaviour,
    ),
    "oracle-19c-to-23ai": Spec(
        pattern="oracle-19c-to-23ai", title="Oracle 19c → Oracle 23ai",
        objective="SQL/PL-SQL source and the JDBC driver compatible with Oracle 23ai; data and query results "
                  "unchanged.",
        out_of_scope="The database engine upgrade itself, data migration, and optional 23ai features not "
                     "requested in the BRD.",
        suffixes=frozenset({".sql", ".pks", ".pkb", ".plsql", ".ddl", ".pls", ".prc", ".fnc", ".trg",
                            ".java", ".xml", ".properties", ".yml", ".yaml", ".gradle", ".kts"}),
        checks=tuple(LEGACY_MARKERS["oracle-19c-to-23ai"]) + (
            _m("DBMS_JAVA usage", r"\bDBMS_JAVA\b", "review against 23ai's JVM-in-database changes", re.IGNORECASE),
            _m("32767-byte boundary", r"\b32767\b", "review against 23ai's extended limits; change only if it constrains a requirement"),
            _m("boolean-like column", r"\bNUMBER\s*\(\s*1\s*\)|\bCHAR\s*\(\s*1\s*\)", "candidate for native BOOLEAN (optional feature)", re.IGNORECASE),
            _m("old connection pool", r"\bcommons-dbcp\b|\bc3p0\b|BasicDataSource", "manual pooling; UCP optional, not required"),
            _m("ojdbc7 driver", r"\bojdbc7\b", "→ ojdbc11 for 23ai"),
            _m("CONNECT BY", r"\bCONNECT\s+BY\b(?!\s+NOCYCLE)", "hierarchical query without NOCYCLE — check whether cycles are possible", re.IGNORECASE),
            _m("SYS_GUID key", r"\bSYS_GUID\s*\(", "manual UUID key — optional modernisation, not broken", re.IGNORECASE),
            _m("AQ queue table", r"\bDBMS_AQADM\.CREATE_QUEUE_TABLE\b", "check the compatible parameter passed to the queue table", re.IGNORECASE),
            _m("compatible parameter", r"\bcompatible\s*=\s*'?1[0-9]\.", "database compatibility pin", re.IGNORECASE),
            _m("EDITIONABLE dictionary query", r"\b(?:USER|ALL|DBA)_OBJECTS\b[^;]*\bEDITIONABLE\b", "review against 23ai edition-based redefinition", re.IGNORECASE),
        ),
        dependency_filter=r"ojdbc|oracle|hibernate|dbcp|c3p0|hikari|ucp|flyway|liquibase|junit",
        tables=(("Database Objects", _sql_objects), ("JDBC Connections", _jdbc_config)),
        behaviour=_oracle_behaviour,
    ),
    "tibco-ems-to-pubsub": Spec(
        pattern="tibco-ems-to-pubsub", title="TIBCO EMS → Google Cloud Pub/Sub",
        objective="Every EMS destination, producer and consumer moved to Google Cloud Pub/Sub topics and "
                  "subscriptions, with delivery semantics reconciled; message contents unchanged.",
        out_of_scope="Message payload formats, business processing in consumers, and GCP infrastructure "
                     "provisioning beyond the topics and subscriptions this migration names.",
        suffixes=frozenset(_JAVA_BUILD | {".json", ".conf", ".cfg", ".substvar", ".bwp", ".process"}),
        checks=tuple(LEGACY_MARKERS["tibco-ems-to-pubsub"]) + (
            _m("durable subscriber", r"\bcreateDurable(?:Subscriber|Consumer)\s*\(|\bsubscriptionDurable\b|\bdurableSubscriptionName\b",
               "one Pub/Sub subscription per durable subscriber"),
            _m("message selector", r"\bmessageSelector\b|\bcreate(?:Consumer|DurableSubscriber|Receiver)\s*\([^;)]*,\s*\"",
               "Pub/Sub attribute filter where expressible, else filter in the consumer"),
            _m("acknowledgement mode", r"\bCLIENT_ACKNOWLEDGE\b|\bDUPS_OK_ACKNOWLEDGE\b|\.acknowledge\s*\(\s*\)|\bSESSION_TRANSACTED\b|createSession\s*\(\s*true",
               "ack()/nack() on the receiver; Pub/Sub is at-least-once — consumers must be idempotent"),
            _m("Spring JMS", r"<jms:listener-container|@(?:[\w$]+\.)*JmsListener\b|\bJmsTemplate\b|\bDefaultMessageListenerContainer\b",
               "Spring JMS wiring → Pub/Sub client or Spring Cloud GCP Pub/Sub"),
            _m("JMS message properties", r"\.set(?:String|Int|Long|Boolean|Object)Property\s*\(|\.setJMS(?:Type|CorrelationID|Priority)\s*\(",
               "JMS properties → Pub/Sub message attributes"),
            _m("EMS server URL", r"\b(?:tcp|ssl)://[\w.\-]+:\d+", "connection config removed; Pub/Sub project/topic config instead"),
            _m("BusinessWorks JMS activity", r"JMSQueue(?:Receiver|Sender)|JMSTopic(?:Subscriber|Publisher)|com\.tibco\.plugin\.jms",
               "BW process activity — flag; the BW process itself is outside a code migration"),
        ),
        dependency_filter=r"tibco|tibjms|jms|pubsub|spring-cloud-gcp|activemq",
        tables=(("Destinations, Producers & Consumers", _destinations),),
        behaviour=_tibco_behaviour,
    ),
}

INVENTORY_PATTERNS = frozenset(SPECS)


# ---------------------------------------------------------------------------
# Scan and render
# ---------------------------------------------------------------------------

def scan(workspace_dir: str, suffixes: frozenset) -> Scan:
    root = Path(workspace_dir)
    files, texts, skipped = [], {}, []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if EXCLUDED_DIRS & set(rel.parts):
            continue
        rel_s = rel.as_posix()
        files.append(rel_s)
        name = PurePosixPath(rel_s).name.lower()
        if PurePosixPath(rel_s).suffix.lower() in suffixes or name == "managed-schema":
            try:
                if path.stat().st_size > _MAX_FILE_BYTES:
                    skipped.append(rel_s)
                    continue
                texts[rel_s] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    files.sort()
    poms = {rel: p for rel in files if PurePosixPath(rel).name == "pom.xml" and (p := parse_pom(root, rel))}
    resolve, managed_version = resolver(poms)
    return Scan(root, files, texts, skipped, poms, resolve, managed_version)


def _alternatives(pattern: str) -> list[str]:
    """Split a regex on its top-level `|` (not inside a group or a class)."""
    parts, depth, in_class, start, i = [], 0, False, 0, 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            i += 2
            continue
        if in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "|" and depth == 0:
            parts.append(pattern[start:i])
            start = i + 1
        i += 1
    return parts + [pattern[start:]]


def _prefilter(checks) -> re.Pattern:
    """One regex that matches wherever any check could. A leading `\\b` is
    dropped from each alternative: that only widens the match (the checks
    themselves still decide), and it lets the regex engine scan for the
    literal instead of testing a word boundary at every position — measured
    5-10x faster on ordinary source."""
    alts = []
    for c in checks:
        flags = "i" if c.pattern.flags & re.IGNORECASE else ""
        for alt in _alternatives(c.pattern.pattern):
            alts.append(f"(?{flags}:{alt[2:] if alt.startswith(chr(92) + 'b') else alt})")
    return re.compile("|".join(alts))


def _file_findings(spec: Spec, sc: Scan) -> dict[str, list[tuple]]:
    """{check name: [(file, [lines], first matching line)]}"""
    # One pass over each file decides whether any check can match; only files
    # that pass are scanned line by line. Each check keeps its own flags.
    prefilter = _prefilter(spec.checks)
    out: dict[str, list[tuple]] = defaultdict(list)
    for rel in sorted(sc.texts):
        text = sc.texts[rel]
        # Candidate lines: every line a prefilter match touches. Each check
        # still decides per line, so the result is what a full line-by-line
        # scan gives, without running every check over every line.
        spans = [(m.start(), max(m.end() - 1, m.start())) for m in prefilter.finditer(text)]
        if not spans:
            continue
        lines = text.splitlines()
        candidates = sorted({n for a, b in spans
                             for n in range(text.count("\n", 0, a) + 1, text.count("\n", 0, b) + 2)})
        for check in spec.checks:
            hits = [n for n in candidates if n <= len(lines) and check.pattern.search(lines[n - 1])]
            if hits:
                out[check.name].append((rel, hits, sample(lines[hits[0] - 1])))
    return out


def _clip(rows: list[str], max_rows: int, what: str) -> list[str]:
    if len(rows) <= max_rows:
        return rows
    return rows[:max_rows] + ["", f"> **{len(rows) - max_rows} more {what} not listed here** "
                                  "(INVENTORY_MAX_ROWS). They exist in the repository and must still be planned — "
                                  "the Directory Rollup below covers every one of them."]


def to_document(pattern: str, workspace_dir: str, max_rows: int = 400) -> str:
    spec = SPECS[pattern]
    sc = scan(workspace_dir, spec.suffixes)
    findings = _file_findings(spec, sc)
    finding_files = sorted({f for rows in findings.values() for f, _, _ in rows})
    behaviour = spec.behaviour(sc) if spec.behaviour else []
    method = (
        "_Generated deterministically — no language model read this repository. Every relevant file was "
        f"scanned once ({len(sc.texts):,} of {len(sc.files):,} files, selected by type), POMs were parsed with "
        "properties resolved through in-repo parents, and every file was matched against this migration's "
        "legacy checklist — the same markers the code review audits the result against. A match means the text "
        "occurs; whether it is live code or a comment is decided when the file is changed. Business intent is "
        "not inferred._"
    )

    # Repo facts
    levels = [f"| `{rel}` | {s} | {l} |" for rel, p in sorted(sc.poms.items()) for s, l in p.levels]
    deps, plugins = [], []
    for rel, pom in sorted(sc.poms.items()):
        for g, a, v, scope, managed in pom.dependencies:
            if re.search(spec.dependency_filter, f"{g}:{a}", re.IGNORECASE):
                version = sc.resolve(pom, v) or ("" if managed else sc.managed_version(pom, g, a))
                deps.append(f"| `{rel}` | {g}:{a} | {version or '(unresolved)'} | {'managed' if managed else scope} |")
        for g, a, v, _ in pom.plugins:
            if spec.pattern == "java-8-to-25":
                plugins.append(f"| `{rel}` | {g}:{a} | {sc.resolve(pom, v) or sc.managed_version(pom, g, a) or '(inherited)'} |")
    gradle = [f for f in sc.files if PurePosixPath(f).name in ("build.gradle", "build.gradle.kts")]

    # Grouped by file, so one file's findings sit together as one manifest row would.
    order = {c.name: i for i, c in enumerate(spec.checks)}
    notes = {c.name: c.note for c in spec.checks}
    flat = sorted(((f, order[name], name, lines, sample) for name, rows in findings.items()
                   for f, lines, sample in rows))
    finding_rows = []
    for f, _, name, lines, first in flat:
        shown = ", ".join(map(str, lines[:8])) + (" …" if len(lines) > 8 else "")
        finding_rows.append(f"| `{f}` | {shown} | {name} | `{first}` | {notes[name]} |")
    rollup: dict[tuple, int] = defaultdict(int)
    for name, rows in findings.items():
        for f, _, _ in rows:
            rollup[(name, str(PurePosixPath(f).parent) + "/")] += 1

    out = ["<!-- SECTION: ANALYSIS -->", "", f"# {spec.title} — Inventory Analysis", "", method, "",
           "## Scope and Coverage", "",
           f"- Files in the repository (build output excluded): **{len(sc.files):,}**; scanned: **{len(sc.texts):,}**",
           f"- Maven modules: **{len(sc.poms)}**" + (f"; Gradle builds: **{len(gradle)}**" if gradle else ""),
           f"- Files with at least one legacy finding: **{len(finding_files)}**"]
    out += [f"- {name}: {len(rows)} file(s)" for name, rows in findings.items()]
    if sc.skipped_large:
        out.append(f"- **Not scanned (over {_MAX_FILE_BYTES:,} bytes):** " + ", ".join(f"`{f}`" for f in sc.skipped_large[:20]))
    out += ["", "The file-by-file findings are in the Technical Specification, which is what the planner reads."]

    out += ["", "<!-- SECTION: BRD -->", "", f"# {spec.title} — Scope", "", method, "",
            "## Objective", "", spec.objective, "",
            "## In Scope", "", f"- {len(finding_files)} file(s) listed under Legacy Stack Blockers in the Technical Specification",
            f"- {len(sc.poms) + len(gradle)} build file(s) (Repo Facts)", "",
            "## Out of Scope", "", spec.out_of_scope, "",
            "## Behaviour to Preserve", "",
            f"{len(behaviour)} item(s) found in the code — listed in the Technical Specification's Behaviour "
            "Inventory. Each must behave the same after the migration."]

    out += ["", "<!-- SECTION: TECHNICAL_SPECIFICATION -->", "", f"# {spec.title} — Technical Specification", "",
            "## Repo Facts", "", "Modules:", ""]
    out += _rows("| POM | artifactId | Packaging | Parent |",
                 [f"| `{r}` | {p.artifact} | {p.packaging} | {p.parent or '—'} |" for r, p in sorted(sc.poms.items())],
                 "| — | no Maven modules | — | — |")
    out += [""] + ([f"- Gradle build: `{g}`" for g in gradle] + [""] if gradle else [])
    out += ["Declared Java levels:", ""] + _rows("| File | Setting | Level |", levels, "| — | none declared literally | — |")
    out += ["", "Dependencies relevant to this migration (versions resolved through parents):", ""]
    out += _clip(_rows("| POM | Coordinate | Version | Scope |", deps, "| — | none found | — | — |"), max_rows + 2, "dependency rows")
    if plugins:
        out += ["", "Build plugins:", ""] + _clip(_rows("| POM | Plugin | Version |", plugins, "| — | — | — |"), max_rows + 2, "plugin rows")
    out += ["", "## Legacy Stack Blockers", "",
            "One row per file per finding — the File Change Manifest candidates.", ""]
    out += _clip(_rows("| File | Lines | Finding | First match | Note |", finding_rows, "| — | — | none found | — | — |"),
                 max_rows + 2, "finding rows")
    out += ["", "## Directory Rollup", "", "Every finding counted per directory — complete even when the table above is capped.", ""]
    out += _rows("| Finding | Directory | Files |", [f"| {n} | `{d}` | {c} |" for (n, d), c in sorted(rollup.items())],
                 "| — | — | 0 |")
    for heading, extractor in spec.tables:
        out += ["", f"## {heading}", ""] + _clip(extractor(sc), max_rows + 2, f"{heading} rows")
    out += ["", "## Behaviour Inventory", ""]
    out += _clip(_rows("| Kind | Value | Where |",
                       [f"| {k} | `{str(v).replace('|', '/')}` | `{w}` |" if v else f"| {k} | — | `{w}` |" for k, v, w in behaviour],
                       "| — | — | none found |"), max_rows + 2, "behaviour rows")

    tests: dict[str, set] = defaultdict(set)
    per_module: dict[str, int] = defaultdict(int)
    for rel, text in sc.texts.items():
        if rel.endswith(".java") and "/src/test/" in f"/{rel}":
            per_module[rel.split("/src/test/")[0] or "."] += 1
            for name, rx in TEST_FRAMEWORKS:
                if rx.search(text):
                    tests[name].add(rel)
    out += ["", "<!-- SECTION: TEST_INVENTORY -->", "", f"# {spec.title} — Tests", ""]
    out += _rows("| Framework | Test files |", [f"| {n} | {len(f)} |" for n, f in sorted(tests.items())], "| — | 0 |")
    out += [""] + _rows("| Module | Test source files |", [f"| `{m}` | {n} |" for m, n in sorted(per_module.items())], "| — | 0 |")
    out += ["", "No tests were executed. Test files and frameworks were found by scanning; which behaviours they "
            "cover was not inferred.", "", "<!-- SECTION: END -->", ""]
    return "\n".join(out)
