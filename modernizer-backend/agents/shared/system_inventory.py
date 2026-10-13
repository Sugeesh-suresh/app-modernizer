"""
System inventory: the facts of an existing system's architecture that the code
states outright, computed without a model, for the Technical Specification.

The Enterprise Architect agent describes the system from evidence packs, which
are written by agents that read the code — thorough, but a model's reading. The
areas a new engineer needs complete and exact are also stated plainly in the
code and its configuration, so they are listed here from the files themselves,
every item with the file:line that states it:

- **Database details** — data sources per configuration file (URL, driver,
  pool, JNDI; credentials redacted), JPA entities with their tables, columns,
  keys and relationships, tables/views/sequences/indexes/triggers/routines
  created by DDL, repositories and DAOs, MyBatis mappers, schema migrations and
  every `@Transactional` boundary.
- **Integrations** — every outbound client (HTTP/REST, SOAP, messaging, mail,
  LDAP, cloud SDKs, file transfer, caches and search), every configured endpoint
  URL with its host, and a host-based hint of third-party versus internal.
- **Security mechanisms** — authentication and authorisation configuration
  (Spring Security rules, `web.xml` constraints, method annotations), session,
  CSRF, CORS and headers, password encoding and cryptography, TLS and keystores,
  secrets in configuration, and the request filters and interceptors.
- **Logging, monitoring and auditing** — logging frameworks, every appender,
  file, rotation and level in the logging configuration, MDC keys, health checks,
  metrics, management endpoints, APM agents, and every auditing mechanism
  (auditing annotations, Envers, entity listeners, audit tables, aspects).

These are patterns over the source text: they find what is written, not what a
framework does by default, and the section says so.
"""
from __future__ import annotations

from . import fswalk
import re
from pathlib import Path

from .config_matrix import display as _display
from .dependency_graph import EXCLUDED_DIRS
from . import search_engine

HEADING = "## System Inventory (computed)"
MAX_FILE_BYTES = 2_000_000

_SUFFIXES = {".java", ".kt", ".groovy", ".scala", ".xml", ".properties", ".yml", ".yaml", ".sql", ".pls", ".pks",
             ".pkb", ".plsql", ".trg", ".ddl", ".js", ".jsx", ".ts", ".tsx", ".sh", ".bat", ".cmd", ".conf", ".cfg",
             ".gradle", ".kts", ".json", ".py", ".ini", ".env"}
_NAMED = {"Dockerfile", "Procfile", "standalone.conf", "catalina.properties", "setenv.sh", "Jenkinsfile",
          "managed-schema"}
_TEST = re.compile(r"(?:^|/)(?:src/test|test|tests|__tests__|spec)/", re.I)
_VENDOR = re.compile(r"(?:^|/)(?:vendor|vendors|lib|libs|third[-_]?party|node_modules)/")
_CODE = {".java", ".kt", ".groovy", ".scala"}
_SCRIPT = {".js", ".jsx", ".ts", ".tsx"}
_CONFIG = {".properties", ".yml", ".yaml", ".conf", ".cfg", ".ini", ".env"}
_SQL = {".sql", ".pls", ".pks", ".pkb", ".plsql", ".trg", ".ddl"}


# ─────────────────────────────────────────────────────────────────────────────
# Files and helpers
# ─────────────────────────────────────────────────────────────────────────────

def _files(root: Path) -> list[tuple[str, str]]:
    out = []
    for path in sorted(fswalk.files(root)):
        if not path.is_file() or (path.suffix.lower() not in _SUFFIXES and path.name not in _NAMED):
            continue
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(Path(rel).parts) or _TEST.search(rel) or _VENDOR.search(rel) \
                or path.name.endswith((".min.js", "package-lock.json")):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            out.append((rel, path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return out


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _where(rel: str, text: str, pos: int) -> str:
    return f"{rel}:{_line(text, pos)}"


def _clip(value: str, limit: int = 160) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ") if value not in (None, "") else "—"


def _code(value: str) -> str:
    return f"`{value.replace('`', chr(39))}`" if value else "—"


_USERINFO = re.compile(r"(//)[^/@\s:]+(?::[^/@\s]*)?@")


def _safe_url(value: str) -> str:
    return _USERINFO.sub(r"\1[REDACTED]@", value)


def _config_entries(rel: str, text: str) -> list[tuple[str, str, int]]:
    """(key, value, line) of a .properties / .yml / .conf file; YAML keys flattened
    with dots, line numbers taken from where each leaf is written."""
    suffix = Path(rel).suffix.lower()
    out = []
    if suffix in (".yml", ".yaml"):
        stack: list[tuple[int, str]] = []
        for n, raw in enumerate(text.splitlines(), 1):
            if not raw.strip() or raw.lstrip().startswith(("#", "- ", "---")):
                if raw.strip() == "---":
                    stack = []
                continue
            m = re.match(r"^(\s*)([\w.\-\[\]\"']+)\s*:\s*(.*)$", raw)
            if not m:
                continue
            indent, key, value = len(m.group(1)), m.group(2).strip("\"'"), m.group(3).strip()
            while stack and stack[-1][0] >= indent:
                stack.pop()
            stack.append((indent, key))
            if value and not value.startswith(("#", "|", ">")):
                out.append((".".join(k for _, k in stack), value.split(" #")[0].strip().strip("\"'"), n))
        return out
    for n, raw in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*([^#!\s=:][^=:]*?)\s*[=:]\s*(.*)$", raw)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip(), n))
    return out


def _value(key: str, value: str) -> str:
    """A configuration value as it may be printed: secrets and user:password@ never shown."""
    return _safe_url(_display(key, value))


# ─────────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────────

_DB_PRODUCTS = [("jdbc:oracle", "Oracle"), ("jdbc:mysql", "MySQL"), ("jdbc:mariadb", "MariaDB"),
                ("jdbc:postgresql", "PostgreSQL"), ("jdbc:sqlserver", "SQL Server"), ("jdbc:jtds", "SQL Server (jTDS)"),
                ("jdbc:db2", "DB2"), ("jdbc:h2", "H2"), ("jdbc:hsqldb", "HSQLDB"), ("jdbc:derby", "Derby"),
                ("jdbc:sqlite", "SQLite"), ("jdbc:as400", "DB2 for i"), ("mongodb://", "MongoDB"),
                ("mongodb+srv://", "MongoDB"), ("redis://", "Redis"), ("cassandra", "Cassandra")]
_DS_KEY = re.compile(r"(?:^|\.)(?:datasource|data-source|db|database|jdbc|r2dbc|mongodb|hikari|dbcp2?|tomcat|c3p0|"
                     r"jpa|hibernate|flyway|liquibase)(?:\.|$)|jdbc[._-]?url|connection[._-]?url|jndi", re.I)
_JDBC_ANY = re.compile(r"(jdbc:[a-z0-9]+:[^\s\"'<>]+|mongodb(?:\+srv)?://[^\s\"'<>]+)", re.I)
_XML_DS = re.compile(r"<(?:datasource|xa-datasource|Resource|bean)\b[^>]*?(?:jndi-name|name|id)\s*=\s*\"([^\"]+)\""
                     r"[^>]*>", re.I)
_TABLE_ANNO = re.compile(r"@Table\s*\(([^)]*)\)")
_ENTITY_CLASS = re.compile(r"@(?:Entity|Document|MappedSuperclass|Embeddable)\b(?:\s*\([^)]*\))?[\s\S]{0,600}?"
                           r"\bclass\s+(\w+)(?:\s+extends\s+([\w.<>]+))?")
_FIELD = re.compile(r"^\s*(?:private|protected|public)\s+(?:final\s+)?([\w.<>,\[\]? ]+?)\s+(\w+)\s*(?:=[^;]*)?;",
                    re.M)
_ANNO = re.compile(r"@(\w+)(\s*\((?:[^()]|\([^()]*\))*\))?")
_REL_ANNOS = {"OneToMany", "ManyToOne", "OneToOne", "ManyToMany", "ElementCollection", "Embedded", "EmbeddedId"}
_COLUMN_ANNOS = {"Id", "GeneratedValue", "Column", "JoinColumn", "JoinTable", "Version", "Lob", "Enumerated",
                 "Temporal", "Transient", "SequenceGenerator", "CreatedBy", "CreatedDate", "LastModifiedBy",
                 "LastModifiedDate", "NotNull", "Size", "Convert", "Formula", "Field", "MapsId", "OrderBy"} | _REL_ANNOS
_CREATE = re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:EDITIONABLE\s+|NONEDITIONABLE\s+)?(?:GLOBAL\s+TEMPORARY\s+)?"
                     r"(TABLE|VIEW|MATERIALIZED\s+VIEW|SEQUENCE|(?:UNIQUE\s+|BITMAP\s+)?INDEX|TRIGGER|PROCEDURE|FUNCTION|"
                     r"PACKAGE\s+BODY|PACKAGE|TYPE\s+BODY|TYPE|SYNONYM|PUBLIC\s+SYNONYM|DATABASE\s+LINK)\s+"
                     r"(?:IF\s+NOT\s+EXISTS\s+)?([\w$#\".]+)", re.I)
_REPO = re.compile(r"(?:interface|class)\s+(\w+)\s+(?:extends|implements)\s+[\w.]*?((?:Jpa|Crud|PagingAndSorting|"
                   r"ListCrud|ListPagingAndSorting|Mongo|Reactive(?:Crud|Mongo)?|R2dbc|Elasticsearch|Cassandra|Redis|"
                   r"Neo4j)?Repository)\s*<\s*([\w.]+)\s*,")
_DAO_HINT = re.compile(r"@(Repository|Mapper)\b|\bJdbcTemplate\b|\bNamedParameterJdbcTemplate\b|\bSimpleJdbcCall\b|"
                       r"\bEntityManager\b|\bSessionFactory\b|\bSqlSession\b|\bCallableStatement\b|\bPreparedStatement\b|"
                       r"\bDataSource\b\s+\w+\s*[;=)]")
_QUERY = re.compile(r"@(Query|NamedQuery|NamedNativeQuery|Procedure|Modifying)\b")
_TX = re.compile(r"@Transactional\b(\s*\((?:[^()]|\([^()]*\))*\))?")
_DECL_AFTER = re.compile(r"\s*(?:@\w+(?:\s*\((?:[^()]|\([^()]*\))*\))?\s*)*"
                         r"(?:public|protected|private|static|final|abstract|synchronized|\s)*"
                         r"(?:class|interface|enum)?\s*[\w<>\[\],.? ]*?\b(\w+)\s*[({<]")
_MYBATIS_NS = re.compile(r"<mapper\s+namespace\s*=\s*\"([\w.]+)\"")
_MYBATIS_STMT = re.compile(r"<(select|insert|update|delete)\s+id\s*=\s*\"(\w+)\"")


def _anno_args(raw: str | None) -> str:
    return _clip((raw or "").strip()[1:-1] if raw else "", 140)


def _arg(args: str, name: str) -> str:
    m = re.search(rf"\b{name}\s*=\s*\"([^\"]*)\"", args or "")
    return m.group(1) if m else ""


def _entities(rel: str, text: str) -> list[dict]:
    out = []
    for m in _ENTITY_CLASS.finditer(text):
        name = m.group(1)
        head = text[max(0, m.start() - 400):m.end()]
        kind = "Document" if "@Document" in head[-(m.end() - m.start()) - 10:] else \
            "Embeddable" if "@Embeddable" in text[m.start():m.end()] else \
            "Mapped superclass" if "@MappedSuperclass" in text[m.start():m.end()] else "Entity"
        table = ""
        t = _TABLE_ANNO.search(text[max(0, m.start() - 300):m.end()])
        if t:
            table = _arg(t.group(1), "name") or ""
            schema = _arg(t.group(1), "schema")
            table = f"{schema}.{table}" if schema and table else table
        if kind == "Document":
            d = re.search(r"@Document\s*\(\s*(?:collection\s*=\s*)?\"([^\"]+)\"", text[m.start():m.end()])
            table = d.group(1) if d else ""
        body_start = text.find("{", m.end())
        depth, i = 0, body_start
        while i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            if depth == 0:
                break
            i += 1
        body = text[body_start:i]
        fields = []
        for f in _FIELD.finditer(body):
            if " static " in f.group(0) or f.group(0).lstrip().startswith(("public static", "private static")):
                continue
            pre = body[max(0, f.start() - 600):f.start()]
            pre = pre[pre.rfind(";") + 1:] if ";" in pre else pre
            pre = pre[pre.rfind("}") + 1:] if "}" in pre else pre
            annos = [(a.group(1), _anno_args(a.group(2))) for a in _ANNO.finditer(pre) if a.group(1) in _COLUMN_ANNOS]
            if any(a == "Transient" for a, _ in annos):
                continue
            col = next((_arg(args, "name") for a, args in annos if a in ("Column", "JoinColumn")), "")
            notes = []
            for a, args in annos:
                if a == "Column":
                    extras = [p for p in ("nullable = false", "unique = true", "length", "precision", "scale",
                                          "columnDefinition", "insertable = false", "updatable = false")
                              if p.split(" ")[0] in args]
                    if extras:
                        notes.append("Column(" + ", ".join(re.findall(r"(?:nullable|unique|length|precision|scale|"
                                                                      r"columnDefinition|insertable|updatable)\s*=\s*"
                                                                      r"(?:\"[^\"]*\"|\w+)", args)) + ")")
                elif a not in ("Column",):
                    notes.append(f"@{a}" + (f"({args})" if args and a in _REL_ANNOS | {"GeneratedValue",
                                                                                          "JoinColumn", "JoinTable",
                                                                                          "Enumerated",
                                                                                          "SequenceGenerator"}
                                             else ""))
            fields.append({"field": f.group(2), "type": _clip(f.group(1), 60), "column": col,
                           "notes": _clip("; ".join(notes), 220),
                           "where": _where(rel, text, body_start + f.start())})
        out.append({"class": name, "kind": kind, "table": table, "extends": m.group(2) or "",
                    "where": _where(rel, text, m.start()), "fields": fields})
    return out


def _ddl_columns(text: str, start: int) -> list[str]:
    """Column definitions of a CREATE TABLE starting at `start` (best effort)."""
    open_at = text.find("(", start)
    if open_at < 0 or open_at - start > 300:
        return []
    depth, i = 0, open_at
    while i < len(text):
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        if depth == 0:
            break
        i += 1
    body = text[open_at + 1:i]
    parts, depth, cur = [], 0, ""
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [_clip(re.sub(r"--[^\n]*", "", p), 140) for p in parts if p.strip()]


def scan_database(files: list[tuple[str, str]]) -> dict:
    sources, entities, objects, repos, daos, mappers, migrations, tx = [], [], [], [], [], [], [], []
    seen_src = set()
    for rel, text in files:
        suffix = Path(rel).suffix.lower()
        if suffix in _CONFIG:
            for key, value, n in _config_entries(rel, text):
                if _DS_KEY.search(key) or _JDBC_ANY.search(value):
                    if (rel, key) in seen_src:
                        continue
                    seen_src.add((rel, key))
                    product = next((p for prefix, p in _DB_PRODUCTS if value.lower().startswith(prefix)), "")
                    sources.append({"key": key, "value": _value(key, value), "product": product,
                                    "where": f"{rel}:{n}"})
        elif suffix == ".xml":
            for m in _JDBC_ANY.finditer(text):
                product = next((p for prefix, p in _DB_PRODUCTS if m.group(1).lower().startswith(prefix)), "")
                sources.append({"key": "(XML)", "value": _safe_url(_clip(m.group(1), 120)), "product": product,
                                "where": _where(rel, text, m.start())})
            for m in _XML_DS.finditer(text):
                tag = m.group(0)
                if re.search(r"DataSource|datasource|jndi", tag) and not re.search(r"<bean\b(?![^>]*DataSource)", tag):
                    sources.append({"key": "(XML data source)", "value": _clip(m.group(1), 120), "product": "",
                                    "where": _where(rel, text, m.start())})
            for m in _MYBATIS_NS.finditer(text):
                stmts = [f"{s.group(1)} {s.group(2)}" for s in _MYBATIS_STMT.finditer(text)]
                mappers.append({"name": m.group(1), "detail": _clip(", ".join(stmts), 400),
                                "where": _where(rel, text, m.start())})
            if re.search(r"<databaseChangeLog\b", text):
                migrations.append({"tool": "Liquibase", "file": rel,
                                   "detail": f"{len(re.findall(r'<changeSet\b', text))} changeSet(s)"})
        if suffix in _CODE:
            entities += _entities(rel, text)
            for m in _REPO.finditer(text):
                queries = len(_QUERY.findall(text))
                repos.append({"name": m.group(1), "base": m.group(2), "entity": m.group(3),
                              "detail": f"{queries} @Query/@Procedure method(s)" if queries else "",
                              "where": _where(rel, text, m.start())})
            if not _REPO.search(text):
                hits = sorted({h.group(1) or h.group(0).split()[0] for h in _DAO_HINT.finditer(text)})
                if hits and re.search(r"@Repository\b|Dao\b|DAO\b|Repository\b|Mapper\b", text):
                    cls = re.search(r"(?:class|interface)\s+(\w+)", text)
                    daos.append({"name": cls.group(1) if cls else Path(rel).stem,
                                 "detail": ", ".join(h for h in hits if h),
                                 "where": _where(rel, text, cls.start() if cls else 0)})
            for m in _TX.finditer(text):
                after = _DECL_AFTER.match(text, m.end())
                target = after.group(1) if after else ""
                tx.append({"target": target, "args": _anno_args(m.group(1)), "where": _where(rel, text, m.start())})
        if suffix in _SQL or (suffix == ".xml" and "createTable" in text):
            for m in _CREATE.finditer(text):
                kind = re.sub(r"\s+", " ", m.group(1).upper())
                detail = ""
                if kind == "TABLE":
                    cols = _ddl_columns(text, m.end())
                    detail = "; ".join(cols)
                elif "INDEX" in kind:
                    on = re.match(r"\s*ON\s+([\w$#\".]+)\s*\(([^)]*)\)", text[m.end():m.end() + 300], re.I)
                    detail = f"on {on.group(1)}({_clip(on.group(2), 80)})" if on else ""
                elif kind == "TRIGGER":
                    on = re.search(r"\b(BEFORE|AFTER|INSTEAD\s+OF)\s+([\w\s,]+?)\s+ON\s+([\w$#\".]+)",
                                   text[m.end():m.end() + 400], re.I)
                    detail = _clip(f"{on.group(1)} {on.group(2)} ON {on.group(3)}", 120) if on else ""
                objects.append({"kind": kind, "name": m.group(2).strip('"'), "detail": _clip(detail, 1200),
                                "where": _where(rel, text, m.start())})
            for m in re.finditer(r"<createTable[^>]*tableName\s*=\s*\"([\w$#]+)\"", text):
                cols = re.findall(r"<column\s+name\s*=\s*\"(\w+)\"\s+type\s*=\s*\"([^\"]+)\"",
                                  text[m.end():text.find("</createTable>", m.end())])
                objects.append({"kind": "TABLE (Liquibase)", "name": m.group(1),
                                "detail": _clip("; ".join(f"{c} {t}" for c, t in cols), 1200),
                                "where": _where(rel, text, m.start())})
        if suffix == ".sql" and re.search(r"(?:^|/)(?:db/migration|migrations?|flyway)/", rel, re.I) \
                or re.match(r"(?:.*/)?[VRU]\d[\w.]*__\w+\.sql$", rel):
            migrations.append({"tool": "Flyway" if re.search(r"[VRU]\d[\w.]*__", rel) else "versioned SQL script",
                               "file": rel, "detail": ""})
    return {"sources": sources, "entities": entities, "objects": objects, "repositories": repos, "daos": daos,
            "mappers": mappers, "migrations": migrations, "transactions": tx}


# ─────────────────────────────────────────────────────────────────────────────
# Integrations
# ─────────────────────────────────────────────────────────────────────────────

_CLIENTS: list[tuple[str, str, re.Pattern]] = [
    ("HTTP / REST", "Feign client", re.compile(r"@FeignClient\s*\(([^)]*)\)")),
    ("HTTP / REST", "RestTemplate", re.compile(r"\b(?:restTemplate|RestTemplate|rest)\s*\.\s*(getForObject|getForEntity|"
                                               r"postForObject|postForEntity|postForLocation|put|delete|exchange|"
                                               r"patchForObject)\s*\(\s*([^,)]{0,160})")),
    ("HTTP / REST", "WebClient", re.compile(r"WebClient\s*\.\s*(?:create|builder)\s*\(\s*([^)]{0,160})\)")),
    ("HTTP / REST", "RestClient", re.compile(r"RestClient\s*\.\s*(?:create|builder)\s*\(\s*([^)]{0,160})\)")),
    ("HTTP / REST", "Java HttpClient", re.compile(r"HttpRequest\s*\.\s*newBuilder\s*\(\s*([^)]{0,160})\)")),
    ("HTTP / REST", "Apache HttpClient", re.compile(r"new\s+Http(Get|Post|Put|Delete|Patch)\s*\(\s*([^)]{0,160})\)")),
    ("HTTP / REST", "OkHttp", re.compile(r"new\s+Request\.Builder\s*\(\s*\)[\s\S]{0,120}?\.url\s*\(\s*([^)]{0,160})\)")),
    ("HTTP / REST", "java.net.URL", re.compile(r"new\s+URL\s*\(\s*([^)]{0,160})\)")),
    ("HTTP / REST", "JAX-RS client", re.compile(r"ClientBuilder\s*\.\s*newClient\s*\([\s\S]{0,200}?\.target\s*\(\s*"
                                                r"([^)]{0,160})\)")),
    ("HTTP / REST", "browser fetch/axios", re.compile(r"\b(?:fetch|axios(?:\.(?:get|post|put|delete|patch))?)\s*\(\s*"
                                                      r"([`'\"]https?://[^`'\"]+[`'\"])")),
    ("SOAP", "JAX-WS client", re.compile(r"@WebServiceClient\s*\(([^)]*)\)|@WebServiceRef\b|Service\.create\s*\(")),
    ("SOAP", "Spring WebServiceTemplate", re.compile(r"WebServiceTemplate\b[\s\S]{0,80}?marshalSendAndReceive\s*\("
                                                     r"\s*([^,)]{0,160})|\bmarshalSendAndReceive\s*\(\s*([^,)]{0,160})")),
    ("SOAP", "Axis / CXF", re.compile(r"\borg\.apache\.(?:axis2?|cxf)\.[\w.]+")),
    ("Messaging", "JMS send", re.compile(r"\bjmsTemplate\s*\.\s*(?:convertAndSend|send)\s*\(\s*([^,)]{0,120})", re.I)),
    ("Messaging", "JMS listener", re.compile(r"@JmsListener\s*\(([^)]*)\)")),
    ("Messaging", "JMS API", re.compile(r"\bcreate(?:Producer|Consumer)\s*\(\s*([^)]{0,120})\)")),
    ("Messaging", "Kafka send", re.compile(r"\bkafkaTemplate\s*\.\s*send\s*\(\s*([^,)]{0,120})", re.I)),
    ("Messaging", "Kafka listener", re.compile(r"@KafkaListener\s*\(([^)]*)\)")),
    ("Messaging", "RabbitMQ send", re.compile(r"\brabbitTemplate\s*\.\s*(?:convertAndSend|send)\s*\(\s*([^)]{0,160})",
                                              re.I)),
    ("Messaging", "RabbitMQ listener", re.compile(r"@RabbitListener\s*\(([^)]*)\)")),
    ("Messaging", "Cloud Pub/Sub", re.compile(r"\b(?:Publisher|Subscriber)\s*\.\s*newBuilder\s*\(\s*([^)]{0,160})\)|"
                                              r"PubSubTemplate\b")),
    ("Messaging", "AWS SQS/SNS", re.compile(r"\bSqs(?:Async)?Client\b|\bSns(?:Async)?Client\b|@SqsListener\s*\(([^)]*)\)")),
    ("Mail", "JavaMail / Spring Mail", re.compile(r"\bJavaMailSender\b|\bTransport\s*\.\s*send\s*\(|\bMimeMessageHelper\b")),
    ("Directory", "LDAP", re.compile(r"\bLdapTemplate\b|\bInitialDirContext\b|\bLdapContextSource\b|\"ldaps?://[^\"]+\"")),
    ("Cloud service", "Google Cloud SDK", re.compile(r"import\s+com\.google\.cloud\.([\w]+)")),
    ("Cloud service", "AWS SDK", re.compile(r"import\s+(?:software\.amazon\.awssdk\.services|com\.amazonaws\.services)"
                                            r"\.([\w]+)")),
    ("Cloud service", "Azure SDK", re.compile(r"import\s+com\.azure\.([\w]+)")),
    ("File transfer", "SFTP / FTP", re.compile(r"\bJSch\b|\bChannelSftp\b|\bFTPClient\b|\bFTPSClient\b|\bSftpClient\b")),
    ("Cache / data service", "Redis", re.compile(r"\bRedisTemplate\b|\bStringRedisTemplate\b|\bJedis\b|\bLettuce\b|"
                                                 r"\bRedissonClient\b")),
    ("Cache / data service", "Elasticsearch / Solr", re.compile(r"\bRestHighLevelClient\b|\bElasticsearchClient\b|"
                                                                r"\b(?:Http|Cloud|Concurrent\w*)SolrClient\b|"
                                                                r"\bSolrServer\b")),
    ("Cache / data service", "Memcached / Hazelcast / Ehcache", re.compile(r"\bMemcachedClient\b|\bHazelcastInstance\b|"
                                                                           r"\bCacheManager\b")),
]
_ENDPOINT_VALUE = re.compile(r"^(?:https?|wss?|ldaps?|amqps?|tcp|ssl|ftp|sftp|smtp|tibjmsnaming|t3|iiop|rmi)://",
                             re.I)
_PUBLIC = ("googleapis.com", "google.com", "amazonaws.com", "azure.com", "windows.net", "microsoft.com",
           "salesforce.com", "force.com", "stripe.com", "paypal.com", "twilio.com", "sendgrid.net", "sendgrid.com",
           "github.com", "gitlab.com", "slack.com", "atlassian.net", "okta.com", "auth0.com", "facebook.com",
           "twitter.com", "linkedin.com", "mailgun.net", "mailchimp.com", "zendesk.com", "servicenow.com",
           "sap.com", "oracle.com", "maps.googleapis.com", "cloudflare.com", "pagerduty.com", "datadoghq.com",
           "newrelic.com", "sentry.io", "algolia.net", "hubspot.com", "docusign.net", "adobe.io")


def host_of(url: str) -> str:
    m = re.match(r"^[a-z][\w+.-]*://(?:[^@/]*@)?([^/:?#\s]+)", url.strip(), re.I)
    return m.group(1).lower() if m else ""


def classify_host(host: str) -> str:
    """Third-party / internal hint from the host alone; '' when it says nothing."""
    if not host or "${" in host or "{" in host:
        return ""
    if host in ("localhost",) or re.match(r"^(?:127\.|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)", host) \
            or host.endswith((".local", ".internal", ".corp", ".lan", ".intra", ".intranet", ".svc",
                              ".cluster.local")) or "." not in host:
        return "internal (private host)"
    if any(host == p or host.endswith("." + p) for p in _PUBLIC):
        return "third-party (public service)"
    return ""


_PLACEHOLDER = re.compile(r"\$\{([\w.\-]+)(?::[^}]*)?\}")


def _settings(files: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """{key: [(value, file:line), ...]} across every configuration file (all profiles)."""
    out: dict[str, list[tuple[str, str]]] = {}
    for rel, text in files:
        if Path(rel).suffix.lower() in _CONFIG:
            for key, value, n in _config_entries(rel, text):
                out.setdefault(key, []).append((value, f"{rel}:{n}"))
    return out


def scan_integrations(files: list[tuple[str, str]]) -> dict:
    clients, endpoints = [], []
    settings = _settings(files)

    def resolve(target: str) -> str:
        """`${key}` placeholders in a client target, with each value the configuration gives it."""
        found = []
        for key in _PLACEHOLDER.findall(target):
            for value, where in settings.get(key, []):
                found.append(f"{key} = {_value(key, value)} ({where})")
            if key not in settings:
                found.append(f"{key}: not set in the repository")
        return "; ".join(found)

    for rel, text in files:
        suffix = Path(rel).suffix.lower()
        if suffix in _CODE or suffix in _SCRIPT:
            for category, kind, pattern in _CLIENTS:
                if category == "HTTP / REST" and kind == "browser fetch/axios" and suffix in _CODE:
                    continue
                if category != "HTTP / REST" and kind == "browser fetch/axios":
                    continue
                if kind == "Memcached / Hazelcast / Ehcache" and "CacheManager" in pattern.pattern \
                        and not re.search(r"memcache|hazelcast|ehcache|caffeine|jcache", text, re.I):
                    continue
                for m in pattern.finditer(text):
                    groups = [g for g in m.groups() if g] if m.groups() else []
                    target = _clip(" ".join(groups) if kind in ("RestTemplate", "Apache HttpClient") else
                                   (groups[0] if groups else ""), 160)
                    resolved = resolve(target)
                    url = next((u for u in re.findall(r"[a-z]+://[^\s;()]+", resolved + " " + target)), "")
                    clients.append({"category": category, "kind": kind, "target": target, "resolved": resolved,
                                    "host_hint": classify_host(host_of(url.strip("\"'`"))),
                                    "where": _where(rel, text, m.start())})
        if suffix in _CONFIG or suffix == ".xml":
            entries = _config_entries(rel, text) if suffix in _CONFIG else [
                (m.group(1) or "(XML)", m.group(2), _line(text, m.start()))
                for m in re.finditer(r"(?:(?:name|key|property)\s*=\s*\"([\w.\-]+)\"[^>]*?\s(?:value|url)\s*=\s*|"
                                     r"(?:url|endpoint|address|location|wsdlLocation)\s*=\s*)\"((?:https?|ldaps?|amqps?|"
                                     r"tcp|ssl|sftp|ftp|smtp|tibjmsnaming)://[^\"]+)\"", text, re.I)]
            for key, value, n in entries:
                if value and _ENDPOINT_VALUE.match(value.strip("\"'")):
                    url = _safe_url(_clip(value.strip("\"'"), 160))
                    host = host_of(url)
                    endpoints.append({"key": key, "url": url, "host": host, "host_hint": classify_host(host),
                                      "where": f"{rel}:{n}"})
    return {"clients": clients, "endpoints": endpoints}


# ─────────────────────────────────────────────────────────────────────────────
# Security
# ─────────────────────────────────────────────────────────────────────────────

_SECURITY: list[tuple[str, str, re.Pattern]] = [
    ("Authentication", "Spring Security enabled", re.compile(r"@EnableWebSecurity\b|@EnableWebFluxSecurity\b|"
                                                             r"<http\b[^>]*security|<security:http\b")),
    ("Authentication", "Security filter chain", re.compile(r"\bSecurityFilterChain\b\s+\w+\s*\(|extends\s+"
                                                           r"WebSecurityConfigurerAdapter\b|SecurityWebFilterChain\b")),
    ("Authentication", "Form login", re.compile(r"\.formLogin\s*\(|<(?:security:)?form-login\b")),
    ("Authentication", "HTTP Basic", re.compile(r"\.httpBasic\s*\(|<(?:security:)?http-basic\b")),
    ("Authentication", "OAuth2 / OIDC login", re.compile(r"\.oauth2Login\s*\(|spring\.security\.oauth2\.client")),
    ("Authentication", "OAuth2 resource server / JWT", re.compile(r"\.oauth2ResourceServer\s*\(|\.jwt\s*\(|"
                                                                 r"spring\.security\.oauth2\.resourceserver|"
                                                                 r"\bJwtDecoder\b|\bJwts\s*\.|\bJWT\s*\.\s*(?:create|"
                                                                 r"require|decode)")),
    ("Authentication", "SAML", re.compile(r"\.saml2Login\s*\(|\bSAMLAuthenticationProvider\b|saml2")),
    ("Authentication", "LDAP / Active Directory", re.compile(r"\.ldapAuthentication\s*\(|ActiveDirectoryLdap"
                                                             r"AuthenticationProvider|LdapAuthenticationProvider|"
                                                             r"<(?:security:)?ldap-")),
    ("Authentication", "JDBC / in-memory users", re.compile(r"\.jdbcAuthentication\s*\(|\.inMemoryAuthentication\s*\(|"
                                                            r"JdbcUserDetailsManager|InMemoryUserDetailsManager|"
                                                            r"<(?:security:)?jdbc-user-service")),
    ("Authentication", "Custom user / authentication provider", re.compile(r"implements\s+(?:UserDetailsService|"
                                                                           r"AuthenticationProvider|"
                                                                           r"ReactiveUserDetailsService)\b")),
    ("Authentication", "Container-managed login (web.xml)", re.compile(r"<login-config>[\s\S]*?</login-config>")),
    ("Authentication", "Logout", re.compile(r"\.logout\s*\(|<(?:security:)?logout\b")),
    ("Authorisation", "URL rule", re.compile(r"\.(requestMatchers|antMatchers|mvcMatchers|regexMatchers|"
                                            r"pathMatchers|anyRequest|anyExchange)\s*\(([^)]*)\)\s*\.\s*(\w+)\s*\("
                                            r"([^)]*)\)")),
    ("Authorisation", "URL rule (XML)", re.compile(r"<(?:security:)?intercept-url\b[^>]*>")),
    ("Authorisation", "web.xml security constraint", re.compile(r"<security-constraint>[\s\S]*?</security-constraint>")),
    ("Authorisation", "Method security enabled", re.compile(r"@EnableMethodSecurity\b|@EnableGlobalMethodSecurity\b|"
                                                            r"<(?:security:)?global-method-security\b")),
    ("Authorisation", "Method rule", re.compile(r"@(?:PreAuthorize|PostAuthorize|Secured|RolesAllowed|PermitAll|"
                                                r"DenyAll)\s*(\((?:[^()]|\([^()]*\))*\))?")),
    ("Authorisation", "Programmatic check", re.compile(r"\.isUserInRole\s*\(\s*([^)]*)\)|"
                                                       r"SecurityContextHolder\s*\.\s*getContext\s*\(\s*\)|"
                                                       r"\.getAuthorities\s*\(\s*\)")),
    ("Session", "Session management", re.compile(r"\.sessionManagement\s*\(|<session-config>[\s\S]*?</session-config>|"
                                                 r"server\.servlet\.session\.|\.maximumSessions\s*\(|"
                                                 r"\.sessionFixation\s*\(|\.rememberMe\s*\(")),
    ("Request protection", "CSRF", re.compile(r"\.csrf\s*\(|<(?:security:)?csrf\b[^>]*>|_csrf\b|"
                                              r"CsrfTokenRepository")),
    ("Request protection", "CORS", re.compile(r"@CrossOrigin\s*(\([^)]*\))?|\.cors\s*\(|CorsConfiguration\b|"
                                              r"addCorsMappings\s*\(|Access-Control-Allow-Origin")),
    ("Request protection", "Security headers", re.compile(r"\.headers\s*\(|frameOptions|contentSecurityPolicy|"
                                                          r"X-Frame-Options|Strict-Transport-Security|httpStrict"
                                                          r"TransportSecurity")),
    ("Request protection", "Input validation", re.compile(r"@Valid\b|@Validated\b")),
    ("Credentials & cryptography", "Password encoder", re.compile(r"\b(\w*PasswordEncoder)\b\s*\(|"
                                                                  r"PasswordEncoderFactories|NoOpPasswordEncoder")),
    ("Credentials & cryptography", "Cryptography", re.compile(r"Cipher\s*\.\s*getInstance\s*\(\s*([^)]*)\)|"
                                                              r"MessageDigest\s*\.\s*getInstance\s*\(\s*([^)]*)\)|"
                                                              r"Mac\s*\.\s*getInstance\s*\(\s*([^)]*)\)|"
                                                              r"KeyStore\s*\.\s*getInstance\s*\(\s*([^)]*)\)|"
                                                              r"SecretKeySpec\b")),
    ("Credentials & cryptography", "Encrypted configuration", re.compile(r"@EnableEncryptableProperties|jasypt|"
                                                                         r"StringEncryptor\b")),
    ("Credentials & cryptography", "Secret store", re.compile(r"\bsm://|\bSecretManagerServiceClient\b|"
                                                              r"\bSecretsManagerClient\b|spring\.cloud\.vault|"
                                                              r"\bVaultTemplate\b|\bSecretClient\b")),
    ("Request filters", "Servlet filter / interceptor", re.compile(r"(?:class\s+(\w+)\s+(?:extends|implements)\s+"
                                                                   r"[\w.]*\b(?:OncePerRequestFilter|Filter|"
                                                                   r"GenericFilterBean|HandlerInterceptor|"
                                                                   r"HandlerInterceptorAdapter|WebFilter|"
                                                                   r"AbstractAuthenticationProcessingFilter)\b)|"
                                                                   r"<filter-class>([^<]+)</filter-class>|"
                                                                   r"@WebFilter\s*(\([^)]*\))?")),
]
_SECURITY_KEYS = re.compile(r"^(?:server\.ssl\.|server\.servlet\.session\.|spring\.security\.|security\.|"
                            r"jasypt\.|management\.endpoints?\.web\.exposure|.*(?:keystore|truststore|"
                            r"\.cors\.|csrf|session\.timeout|jwt|oauth|saml|ldap|auth))", re.I)


def scan_security(files: list[tuple[str, str]], root: Path) -> dict:
    rows, keys, stores = [], [], []
    encrypted = 0
    for rel, text in files:
        suffix = Path(rel).suffix.lower()
        if suffix in _CODE or suffix == ".xml" or suffix in _CONFIG or suffix in _SCRIPT:
            for area, kind, pattern in _SECURITY:
                if suffix in _CONFIG and area not in ("Authentication", "Session", "Credentials & cryptography"):
                    continue
                if kind == "Input validation" and suffix not in _CODE:
                    continue
                for m in pattern.finditer(text):
                    detail = next((g for g in m.groups() if g), "") if m.groups() else ""
                    if kind in ("URL rule",):
                        detail = f"{m.group(1)}({_clip(m.group(2), 120)}) → {m.group(3)}({_clip(m.group(4), 80)})"
                    elif kind in ("URL rule (XML)", "web.xml security constraint", "Container-managed login (web.xml)"):
                        detail = _clip(re.sub(r"<[^>]+>", " ", m.group(0)) if "constraint" in kind or "login" in kind
                                       else m.group(0), 300)
                    elif kind in ("CSRF", "Session management", "Security headers", "CORS") and not detail:
                        start = text.rfind("\n", 0, m.start()) + 1
                        end = text.find("\n", m.end())
                        detail = _clip(text[start:end if end > 0 else len(text)], 160)
                    elif kind == "Method rule":
                        detail = _clip(m.group(0), 160)
                        after = _DECL_AFTER.match(text, m.end())
                        if after:
                            detail += f" on `{after.group(1)}`"
                    where = _where(rel, text, m.start())
                    if any(r["kind"] == kind and r["where"] == where for r in rows[-20:]):
                        continue
                    rows.append({"area": area, "kind": kind, "detail": _clip(detail, 300), "where": where})
        if suffix in _CONFIG:
            for key, value, n in _config_entries(rel, text):
                if value.startswith("ENC("):
                    encrypted += 1
                if _SECURITY_KEYS.match(key):
                    keys.append({"key": key, "value": _value(key, value), "where": f"{rel}:{n}"})
    for path in sorted(fswalk.files(root)):
        if path.is_file() and path.suffix.lower() in (".jks", ".p12", ".pfx", ".keystore", ".truststore", ".pem",
                                                      ".crt", ".cer", ".key") \
                and not EXCLUDED_DIRS & set(path.relative_to(root).parts):
            stores.append(path.relative_to(root).as_posix())
    return {"rows": rows, "keys": keys, "stores": stores, "encrypted_values": encrypted}


# ─────────────────────────────────────────────────────────────────────────────
# Logging, monitoring, auditing
# ─────────────────────────────────────────────────────────────────────────────

_LOG_FACADES = [("SLF4J", re.compile(r"import\s+org\.slf4j\.|@Slf4j\b")),
                ("Log4j 2", re.compile(r"import\s+org\.apache\.logging\.log4j\.|@Log4j2\b")),
                ("Log4j 1.x", re.compile(r"import\s+org\.apache\.log4j\.|@Log4j\b")),
                ("java.util.logging", re.compile(r"import\s+java\.util\.logging\.|@Log\b")),
                ("Commons Logging", re.compile(r"import\s+org\.apache\.commons\.logging\.|@CommonsLog\b")),
                ("JBoss Logging", re.compile(r"import\s+org\.jboss\.logging\.|@JBossLog\b")),
                ("System.out / printStackTrace", re.compile(r"System\s*\.\s*(?:out|err)\s*\.\s*print|"
                                                            r"\.printStackTrace\s*\(")),
                ("Browser console", re.compile(r"\bconsole\s*\.\s*(?:log|error|warn|info|debug)\s*\("))]
_LOG_CALL = re.compile(r"\b(?:log|logger|LOG|LOGGER|_log|_logger)\s*\.\s*(trace|debug|info|warn|warning|error|fatal|"
                       r"severe)\s*\(", re.I)
_MDC = re.compile(r"\b(?:MDC|ThreadContext)\s*\.\s*put\s*\(\s*\"?([\w.\-]+)")
_MONITOR: list[tuple[str, re.Pattern]] = [
    ("Spring Boot Actuator", re.compile(r"spring-boot-starter-actuator|org\.springframework\.boot\.actuate")),
    ("Health indicator", re.compile(r"implements\s+(?:Reactive)?HealthIndicator\b|extends\s+AbstractHealthIndicator\b")),
    ("Micrometer metrics", re.compile(r"\bMeterRegistry\b|@Timed\b|@Counted\b|Counter\s*\.\s*builder\s*\(|"
                                      r"Timer\s*\.\s*builder\s*\(|micrometer-registry-(\w+)")),
    ("Dropwizard metrics", re.compile(r"com\.codahale\.metrics|io\.dropwizard\.metrics")),
    ("Prometheus", re.compile(r"prometheus", re.I)),
    ("JMX", re.compile(r"@ManagedResource\b|@ManagedOperation\b|MBeanServer\b|registerMBean\s*\(")),
    ("Distributed tracing", re.compile(r"spring-cloud-starter-sleuth|micrometer-tracing|opentelemetry|zipkin|jaeger",
                                       re.I)),
    ("APM agent", re.compile(r"-javaagent:\S+|newrelic|dynatrace|appdynamics|elastic-apm|dd-java-agent|"
                             r"applicationinsights|instana", re.I)),
    ("Error reporting", re.compile(r"\bSentry\b|io\.sentry|rollbar|bugsnag|raygun", re.I)),
    ("Scheduled / health job logging", re.compile(r"@Scheduled\b[\s\S]{0,300}?\blog(?:ger)?\s*\.", re.I)),
]
_AUDIT: list[tuple[str, re.Pattern]] = [
    ("Spring Data auditing enabled", re.compile(r"@Enable(?:Jpa|Mongo|Jdbc|R2dbc)Auditing\b(\s*\([^)]*\))?")),
    ("Auditor provider", re.compile(r"implements\s+(?:Reactive)?AuditorAware\b")),
    ("Audit field", re.compile(r"@(CreatedBy|CreatedDate|LastModifiedBy|LastModifiedDate)\b")),
    ("Hibernate Envers", re.compile(r"@Audited\b|@AuditTable\b|@RevisionEntity\b|org\.hibernate\.envers")),
    ("Entity listener", re.compile(r"@EntityListeners\s*\(([^)]*)\)|@(?:PrePersist|PreUpdate|PreRemove|PostPersist|"
                                   r"PostUpdate|PostRemove)\b")),
    ("Audit aspect / advice", re.compile(r"@Aspect\b[\s\S]{0,2000}?@(?:Around|AfterReturning|Before|After)\s*\(([^)]*)\)")),
    ("Audit event", re.compile(r"\bAuditEvent(?:Repository)?\b|AuditApplicationEvent|AbstractAuditListener")),
    ("Database audit", re.compile(r"\bAUDIT\s+(?:ALL|SELECT|INSERT|UPDATE|DELETE|POLICY|SESSION)\b|"
                                  r"CREATE\s+AUDIT\s+POLICY", re.I)),
]
_AUDIT_TABLE = re.compile(r"(?:audit|_aud\b|_aud$|history|_hist\b|journal|_log\b|event_log|change_log|activity)", re.I)


def _logging_config(rel: str, text: str) -> list[dict]:
    """Every appender and logger level a logging configuration file sets."""
    name = Path(rel).name.lower()
    rows = []
    if name.endswith(".xml") and re.search(r"<configuration\b|<Configuration\b|<log4j:configuration", text):
        for m in re.finditer(r"<appender\b[^>]*\bname\s*=\s*\"([^\"]+)\"[^>]*?(?:class\s*=\s*\"([^\"]+)\")?[^>]*>"
                             r"([\s\S]*?)</appender>", text):
            body = m.group(3)
            bits = [f"{tag}={_clip(v, 80)}" for tag in ("file", "fileNamePattern", "maxFileSize", "maxHistory",
                                                       "totalSizeCap", "pattern", "remoteHost", "destination")
                    for v in re.findall(rf"<{tag}>\s*([^<]+?)\s*</{tag}>", body)]
            bits += [f"{k}={_clip(v, 80)}" for k, v in re.findall(r"\b(fileName|filePattern|value)\s*=\s*\"([^\"]+)\"",
                                                                  body)]
            rows.append({"kind": "appender", "name": m.group(1), "detail": _clip(f"{m.group(2) or ''} "
                                                                                 + "; ".join(bits), 400),
                         "where": _where(rel, text, m.start())})
        appenders = re.search(r"<Appenders>([\s\S]*?)</Appenders>", text)
        if appenders:
            for m in re.finditer(r"<(\w+)\s+name\s*=\s*\"([^\"]+)\"([^>]*)>", appenders.group(1)):
                attrs = "; ".join(f"{k}={_clip(v, 80)}" for k, v in re.findall(r"(\w+)\s*=\s*\"([^\"]+)\"",
                                                                                m.group(3)))
                rows.append({"kind": "appender", "name": m.group(2), "detail": _clip(f"{m.group(1)} {attrs}", 400),
                             "where": _where(rel, text, appenders.start(1) + m.start())})
        for m in re.finditer(r"<(?:logger|Logger|AsyncLogger)\s+name\s*=\s*\"([^\"]+)\"([^>]*)>", text):
            level = re.search(r"level\s*=\s*\"([^\"]+)\"", m.group(2))
            rows.append({"kind": "logger level", "name": m.group(1), "detail": level.group(1) if level else "",
                         "where": _where(rel, text, m.start())})
        for m in re.finditer(r"<(?:root|Root|AsyncRoot)\b([^>]*)>", text):
            level = re.search(r"level\s*=\s*\"([^\"]+)\"", m.group(1))
            rows.append({"kind": "root level", "name": "root", "detail": level.group(1) if level else "",
                         "where": _where(rel, text, m.start())})
        for m in re.finditer(r"<springProfile\s+name\s*=\s*\"([^\"]+)\"", text):
            rows.append({"kind": "profile block", "name": m.group(1), "detail": "", "where": _where(rel, text,
                                                                                                    m.start())})
    elif name.endswith(".properties") and ("log4j" in name or "logging" in name):
        for key, value, n in _config_entries(rel, text):
            if re.match(r"log4j\.(?:rootLogger|rootCategory|logger\.|appender\.\w+$|appender\.\w+\.(?:File|"
                        r"MaxFileSize|MaxBackupIndex|DatePattern|layout\.ConversionPattern|Threshold))|"
                        r"(?:handlers|\.level|java\.util\.logging\.)", key):
                rows.append({"kind": "setting", "name": key, "detail": _clip(value, 200), "where": f"{rel}:{n}"})
    return rows


def scan_observability(files: list[tuple[str, str]]) -> dict:
    facades: dict[str, set[str]] = {}
    levels: dict[str, int] = {}
    log_config, log_keys, mdc, monitoring, auditing, audit_tables, mgmt_keys = [], [], [], [], [], [], []
    for rel, text in files:
        suffix = Path(rel).suffix.lower()
        name = Path(rel).name.lower()
        if suffix in _CODE or suffix in _SCRIPT:
            for label, pattern in _LOG_FACADES:
                if label == "Browser console" and suffix in _CODE:
                    continue
                if pattern.search(text):
                    facades.setdefault(label, set()).add(rel)
            for m in _LOG_CALL.finditer(text):
                levels[m.group(1).lower()] = levels.get(m.group(1).lower(), 0) + 1
            for m in _MDC.finditer(text):
                mdc.append({"key": m.group(1), "where": _where(rel, text, m.start())})
        if re.search(r"(?:^|/)(?:logback|log4j2?|logging)[\w.\-]*\.(?:xml|properties)$|"
                     r"(?:^|/)jboss-log4j\.xml$", rel, re.I):
            log_config += [{**r, "file": rel} for r in _logging_config(rel, text)]
        if suffix in _CONFIG:
            for key, value, n in _config_entries(rel, text):
                if key.startswith(("logging.", "log.", "log4j")) and "log4j" not in name:
                    log_keys.append({"key": key, "value": _value(key, value), "where": f"{rel}:{n}"})
                if key.startswith(("management.", "endpoints.", "info.", "metrics.", "otel.", "newrelic.",
                                   "spring.sleuth", "sentry.")):
                    mgmt_keys.append({"key": key, "value": _value(key, value), "where": f"{rel}:{n}"})
        for label, pattern in _MONITOR:
            if label == "Scheduled / health job logging" or (label == "Prometheus" and "micrometer-registry-prometheus"
                                                             in text and suffix in (".xml", ".gradle", ".kts")):
                continue
            if label == "Prometheus" and suffix not in _CODE | _CONFIG | {".xml", ".gradle", ".kts"}:
                continue
            m = pattern.search(text)
            if m and not (label == "APM agent" and suffix in _SCRIPT):
                detail = next((g for g in m.groups() if g), "") if m.groups() else _clip(m.group(0), 100)
                monitoring.append({"kind": label, "detail": _clip(detail, 160), "where": _where(rel, text, m.start())})
        if suffix in _CODE or suffix in _SQL or suffix == ".xml":
            for label, pattern in _AUDIT:
                if label == "Database audit" and suffix not in _SQL:
                    continue
                for m in pattern.finditer(text):
                    detail = next((g for g in m.groups() if g), "") if m.groups() else ""
                    if label == "Audit field":
                        after = _DECL_AFTER.match(text, m.end())
                        detail = f"@{m.group(1)}" + (f" on `{after.group(1)}`" if after else "")
                    auditing.append({"kind": label, "detail": _clip(detail, 200),
                                     "where": _where(rel, text, m.start())})
            for m in re.finditer(r"(?:CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?|@Table\s*\([^)]*name\s*=\s*\"|"
                                 r"tableName\s*=\s*\")([\w$#\".]+)", text, re.I):
                table = m.group(1).strip('"')
                if _AUDIT_TABLE.search(table):
                    audit_tables.append({"table": table, "where": _where(rel, text, m.start())})
    return {"facades": {k: sorted(v) for k, v in facades.items()}, "levels": levels, "config": log_config,
            "keys": log_keys, "mdc": mdc, "monitoring": monitoring, "management_keys": mgmt_keys,
            "auditing": auditing, "audit_tables": audit_tables}


# ─────────────────────────────────────────────────────────────────────────────
# Scan and render
# ─────────────────────────────────────────────────────────────────────────────

def scan(workspace_dir: str) -> dict:
    root = Path(workspace_dir)
    if not root.is_dir():
        return {}
    files = _files(root)
    database = scan_database(files)
    # The search engine (Solr) is a data store too: the data-layer pass traces its cores.
    search = search_engine.scan(files, _settings(files))
    if search:
        from .interfaces import scan as scan_interfaces
        search["backed"] = search_engine.backed_endpoints(search, scan_interfaces(workspace_dir)["endpoints"], files)
        database["search"] = search
    return {"database": database, "integrations": scan_integrations(files),
            "security": scan_security(files, root), "observability": scan_observability(files)}


def _table(headers: list[str], rows: list[list], empty: str = "None found in the repository.") -> list[str]:
    if not rows:
        return [f"_{empty}_", ""]
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return out + [""]


def to_markdown(inv: dict) -> str:
    if not inv:
        return ""
    db, integ, sec, obs = inv["database"], inv["integrations"], inv["security"], inv["observability"]
    lines = [HEADING, "",
             "_Computed by the pipeline from the repository's source and configuration files (no model): every item "
             "the files state, with the file and line that states it. Pattern matching over the text — it lists what "
             "is written, not framework defaults or what is configured outside the repository. Credentials are never "
             "shown. Test code is excluded._", ""]

    lines += ["### Database Details (computed)", "", "#### Data sources and connection settings", ""]
    lines += _table(["Setting", "Value", "Database", "Where"],
                    [[_code(s["key"]), _code(s["value"]), s["product"], _code(s["where"])] for s in db["sources"]])
    lines += ["#### Entities and their mapping", ""]
    if not db["entities"]:
        lines += ["_No JPA/MongoDB entity classes found._", ""]
    for e in db["entities"]:
        title = f"`{e['class']}` — {e['kind']}" + (f", table `{e['table']}`" if e["table"] else
                                                     ", table name not set (framework naming applies)"
                                                     if e["kind"] == "Entity" else "")
        lines += [f"**{title}** ({_code(e['where'])}" + (f"; extends `{e['extends']}`" if e["extends"] else "") + ")",
                  ""]
        lines += _table(["Field", "Java type", "Column", "Mapping", "Where"],
                        [[_code(f["field"]), _code(f["type"]), _code(f["column"]), f["notes"], _code(f["where"])]
                         for f in e["fields"]], "No persistent fields found.")
    lines += ["#### Schema objects created by DDL", ""]
    lines += _table(["Kind", "Name", "Definition", "Where"],
                    [[o["kind"], _code(o["name"]), o["detail"], _code(o["where"])] for o in db["objects"]])
    lines += ["#### Repositories, DAOs and mappers", ""]
    lines += _table(["Component", "Type", "Entity / detail", "Where"],
                    [[_code(r["name"]), r["base"], f"`{r['entity']}`" + (f"; {r['detail']}" if r["detail"] else ""),
                      _code(r["where"])] for r in db["repositories"]]
                    + [[_code(d["name"]), "DAO / data access", d["detail"], _code(d["where"])] for d in db["daos"]]
                    + [[_code(m["name"]), "MyBatis mapper", m["detail"], _code(m["where"])] for m in db["mappers"]])
    lines += ["#### Schema change scripts (Flyway, Liquibase, versioned SQL)", ""]
    lines += _table(["Tool", "File", "Detail"], [[m["tool"], _code(m["file"]), m["detail"]] for m in db["migrations"]])
    lines += ["#### Transaction boundaries (`@Transactional`)", ""]
    lines += _table(["Applies to", "Attributes", "Where"],
                    [[_code(t["target"]), t["args"] or "defaults", _code(t["where"])] for t in db["transactions"]])

    if db.get("search"):
        lines += [search_engine.to_markdown(db["search"], db["search"].get("backed")), ""]
    lines += ["### Integrations (computed)", "",
              "_Host hint: `internal (private host)` for localhost, private IP ranges and internal domain suffixes; "
              "`third-party (public service)` for well-known public service domains; blank when the host alone does "
              "not say (the evidence and the Enterprise Architect decide)._", "",
              "#### Outbound clients in the code", ""]
    lines += _table(["Category", "Client", "Target as written", "Configured value", "Host hint", "Where"],
                    [[c["category"], c["kind"], _code(c["target"]), c.get("resolved", ""), c["host_hint"],
                      _code(c["where"])] for c in integ["clients"]])
    lines += ["#### Endpoints in configuration", ""]
    lines += _table(["Setting", "URL", "Host", "Host hint", "Where"],
                    [[_code(e["key"]), _code(e["url"]), _code(e["host"]), e["host_hint"], _code(e["where"])]
                     for e in integ["endpoints"]])

    lines += ["### Security Mechanisms (computed)", ""]
    for area in dict.fromkeys(a for a, _, _ in _SECURITY):
        rows = [r for r in sec["rows"] if r["area"] == area]
        lines += [f"#### {area}", ""]
        lines += _table(["Mechanism", "Detail", "Where"], [[r["kind"], _code(r["detail"]) if r["detail"] else "",
                                                           _code(r["where"])] for r in rows],
                        f"No {area.lower()} mechanism found in the repository's files.")
    lines += ["#### Security-related configuration", ""]
    lines += _table(["Key", "Value", "Where"], [[_code(k["key"]), _code(k["value"]), _code(k["where"])]
                                               for k in sec["keys"]])
    lines.append(f"- Encrypted configuration values (`ENC(...)`): {sec['encrypted_values']}")
    lines.append("- Key and certificate files in the repository: "
                 + (", ".join(f"`{s}`" for s in sec["stores"]) if sec["stores"] else "none"))
    lines.append("")

    lines += ["### Logging, Monitoring & Auditing (computed)", "", "#### Logging frameworks used in code", ""]
    lines += _table(["Framework", "Files using it"],
                    [[k, f"{len(v)}: " + ", ".join(f"`{f}`" for f in v)] for k, v in sorted(obs["facades"].items())])
    if obs["levels"]:
        lines += ["Log statements by level: " + ", ".join(f"{k} {v}" for k, v in sorted(obs["levels"].items())), ""]
    lines += ["#### Logging configuration files", ""]
    lines += _table(["File", "Kind", "Name", "Detail", "Where"],
                    [[_code(c["file"]), c["kind"], _code(c["name"]), _code(c["detail"]) if c["detail"] else "",
                      _code(c["where"])] for c in obs["config"]])
    lines += ["#### Logging settings in application configuration", ""]
    lines += _table(["Key", "Value", "Where"], [[_code(k["key"]), _code(k["value"]), _code(k["where"])]
                                               for k in obs["keys"]])
    lines += ["#### Correlation / MDC keys", ""]
    lines += _table(["Key", "Where"], [[_code(m["key"]), _code(m["where"])] for m in obs["mdc"]])
    lines += ["#### Monitoring, health and metrics", ""]
    lines += _table(["Mechanism", "Detail", "Where"], [[m["kind"], _code(m["detail"]) if m["detail"] else "",
                                                       _code(m["where"])] for m in obs["monitoring"]])
    lines += ["#### Management and monitoring configuration", ""]
    lines += _table(["Key", "Value", "Where"], [[_code(k["key"]), _code(k["value"]), _code(k["where"])]
                                               for k in obs["management_keys"]])
    lines += ["#### Auditing", ""]
    lines += _table(["Mechanism", "Detail", "Where"], [[a["kind"], _code(a["detail"]) if a["detail"] else "",
                                                       _code(a["where"])] for a in obs["auditing"]])
    lines += ["#### Tables that look like audit or history records", ""]
    lines += _table(["Table", "Where"], [[_code(t["table"]), _code(t["where"])] for t in obs["audit_tables"]])
    return "\n".join(lines).rstrip() + "\n"
