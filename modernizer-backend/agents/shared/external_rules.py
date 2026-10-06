"""
Where business rules may live outside the repository — found by reading the
code, no model involved.

Extraction can only state rules that are in the code it reads. This scan lists
every place the code hands a decision, a value or a text to something the
repository does not contain, so the gap is visible instead of assumed away:

- **Message texts not in the repository** — message keys the templates and code
  use (`#{key}`, `getMessage("key")`, `message = "{key}"`, `rejectValue(.., "code")`)
  that no message bundle in the repository defines.
- **External services** — HTTP clients (`@FeignClient`, `RestTemplate`,
  `WebClient`, `HttpClient`, `new URL(..)`): the rules applied there are not here.
- **Database tables with no definition here** — tables the SQL reads or writes that
  no `CREATE TABLE`, Liquibase `createTable`, `@Table` or `@Entity` in the
  repository defines: their content (codes, limits, configuration) may hold rules.
- **Stored procedures and functions not in the repository** — called
  (`{call x}`, `@Procedure`, `withProcedureName`, …) but never created here.
- **Logic evaluated at run time** — SpEL parsers and `#{…}` values, script
  engines, `Class.forName`, a rules engine loading rules that are not in the
  repository.
- **Feature switches** — `@ConditionalOnProperty`, `@Profile` and feature-flag
  clients: which branch runs depends on configuration or a flag service.

Every row cites where the code refers to it. The patterns are heuristics over
the source text; the section says so.
"""
import re
from pathlib import Path

from .dependency_graph import EXCLUDED_DIRS

HEADING = "## Rules That May Live Outside This Repository"
MAX_FILE_BYTES = 2_000_000
_TEST = re.compile(r"(?:^|/)(?:src/test|test|tests|__tests__)/", re.I)
_TEXT_SUFFIXES = {".java", ".kt", ".groovy", ".html", ".htm", ".jsp", ".jspf", ".tag", ".js", ".jsx", ".ts",
                  ".tsx", ".sql", ".pls", ".pks", ".pkb", ".plsql", ".xml", ".properties", ".yml", ".yaml", ".drl"}

_MESSAGE_USE = [
    re.compile(r"#\{\s*([A-Za-z][\w.\-]*)\s*(?:\(|\})"),                         # Thymeleaf #{key} / #{key(..)}
    re.compile(r"<(?:spring|fmt):message\b[^>]*\b(?:code|key)\s*=\s*[\"']([\w.\-]+)"),  # JSP
    re.compile(r"getMessage\s*\(\s*\"([\w.\-]+)\""),
    re.compile(r"\bmessage\s*=\s*\"\{([\w.\-]+)\}\""),                          # @NotNull(message = "{key}")
    re.compile(r"\bmessage\s*\(\s*\)\s*default\s*\"\{([\w.\-]+)\}\""),          # custom constraint default
    re.compile(r"\.\s*(?:rejectValue\s*\(\s*\"[^\"]*\"\s*,|reject\s*\()\s*\"([\w.\-]+)\""),
]
_FRAMEWORK_KEYS = ("javax.", "jakarta.", "org.hibernate.", "org.springframework.")
_HTTP = [
    (re.compile(r"@FeignClient\s*\(([^)]*)\)"), "Feign client"),
    (re.compile(r"\.\s*(?:getForObject|getForEntity|postForObject|postForEntity|postForLocation|exchange|"
                r"patchForObject)\s*\(\s*(\"[^\"]+\"|[\w.]+)"), "RestTemplate call"),
    (re.compile(r"WebClient\s*\.\s*(?:create\s*\(\s*(\"[^\"]*\"|[\w.]+)|builder\s*\(\s*\))"), "WebClient"),
    (re.compile(r"\.\s*baseUrl\s*\(\s*(\"[^\"]*\"|[\w.]+)"), "WebClient base URL"),
    (re.compile(r"new\s+URL\s*\(\s*(\"https?://[^\"]+\"|[\w.]+)"), "java.net.URL"),
    (re.compile(r"URI\s*\.\s*create\s*\(\s*(\"https?://[^\"]+\")"), "HttpClient request"),
]
_SQL_REF = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE|MERGE\s+INTO|DELETE\s+FROM)\s+([A-Za-z_][\w$#]*(?:\.[A-Za-z_][\w$#]*)?)",
                      re.I)
_SQL_LITERAL = re.compile(r"\"([^\"]*\b(?:SELECT|INSERT|UPDATE|DELETE|MERGE)\b[^\"]*)\"", re.I)
_CREATE_TABLE = re.compile(r"CREATE\s+(?:GLOBAL\s+TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                           r"([\w$#\".]+)", re.I)
_CREATE_VIEW = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW\s+([\w$#\".]+)", re.I)
_LIQUIBASE_TABLE = re.compile(r"createTable[^>]*tableName\s*=\s*\"([\w$#]+)\"|tableName:\s*([\w$#]+)")
_TABLE_ANNO = re.compile(r"@Table\s*\([^)]*\bname\s*=\s*\"([\w$#.]+)\"")
_ENTITY = re.compile(r"@Entity\b[\s\S]{0,300}?\bclass\s+(\w+)")
_PROC_CALL = [
    re.compile(r"\{\s*\??\s*=?\s*call\s+([\w$#.]+)", re.I),
    re.compile(r"@Procedure\s*\(\s*(?:(?:name|procedureName|value)\s*=\s*)?\"([\w$#.]+)\""),
    re.compile(r"procedureName\s*=\s*\"([\w$#.]+)\""),
    re.compile(r"with(?:Procedure|Function)Name\s*\(\s*\"([\w$#.]+)\""),
    re.compile(r"createStoredProcedureQuery\s*\(\s*\"([\w$#.]+)\""),
]
_CREATE_ROUTINE = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:EDITIONABLE\s+)?(?:PROCEDURE|FUNCTION|PACKAGE(?:\s+BODY)?)"
                             r"\s+([\w$#\".]+)", re.I)
_RUNTIME = [
    (re.compile(r"\bSpelExpressionParser\b|\.parseExpression\s*\("), "SpEL expression evaluated at run time"),
    (re.compile(r"@Value\s*\(\s*\"#\{"), "SpEL value computed at run time"),
    (re.compile(r"\bScriptEngineManager\b|\bGroovyShell\b|\bNashorn"), "script evaluated at run time"),
    (re.compile(r"\bClass\s*\.\s*forName\s*\("), "class chosen at run time"),
    (re.compile(r"\bKieServices\b|\bKieContainer\b|\bKnowledgeBuilder\b"), "rules engine"),
]
_SWITCHES = [
    (re.compile(r"@ConditionalOnProperty\s*\(([^)]*)\)"), "bean enabled by a property"),
    (re.compile(r"@Profile\s*\(([^)]*)\)"), "bean enabled by a profile"),
    (re.compile(r"\b(?:FeatureManager|Togglz)\b|\.isActive\s*\(\s*\w*Feature"), "Togglz feature flag"),
    (re.compile(r"\bff4j\b\s*\.\s*check\s*\(|\bFF4j\b"), "FF4j feature flag"),
    (re.compile(r"\bLDClient\b|\.\s*(?:bool|string|int)Variation\s*\("), "LaunchDarkly feature flag"),
    (re.compile(r"\bunleash\s*\.\s*isEnabled\s*\(|\bUnleash\b"), "Unleash feature flag"),
    (re.compile(r"\.\s*getTreatment\s*\("), "Split feature flag"),
]
_KEYWORDS = {"select", "where", "set", "values", "dual", "the", "a", "an", "as", "on", "lateral", "table", "only",
             "unnest", "json_table", "xmltable"}


def _files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(Path(rel).parts) or "node_modules" in rel or _TEST.search(rel) \
                or path.name.endswith(".min.js") or re.search(r"(?:^|/)(?:vendor|lib|libs)/", rel):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            yield rel, path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _bare(name: str) -> str:
    return name.strip('"').split(".")[-1].upper()


def scan(workspace_dir: str) -> list[dict]:
    """[{"category", "reference", "kind", "where": ["file:line", …]}] in a fixed order."""
    root = Path(workspace_dir)
    if not root.is_dir():
        return []
    files = list(_files(root))
    found: dict[tuple, dict] = {}

    def add(category: str, reference: str, kind: str, rel: str, line: int):
        key = (category, reference)
        row = found.setdefault(key, {"category": category, "reference": reference, "kind": kind, "where": []})
        spot = f"{rel}:{line}"
        if spot not in row["where"]:
            row["where"].append(spot)

    # Message keys defined in the repository's bundles.
    defined_keys: set[str] = set()
    for rel, text in files:
        if rel.endswith(".properties") and re.search(r"(?:^|/)(?:messages|ValidationMessages|[\w-]*message[\w-]*)"
                                                     r"[\w-]*\.properties$|(?:^|/)i18n/", rel, re.I):
            defined_keys.update(m.group(1).strip() for m in re.finditer(r"^\s*([^#!=:\s][^=:]*?)\s*[=:]", text, re.M))
    defined_tables: set[str] = set()
    defined_routines: set[str] = set()
    for rel, text in files:
        for pattern in (_CREATE_TABLE, _CREATE_VIEW, _TABLE_ANNO):
            defined_tables.update(_bare(m.group(1)) for m in pattern.finditer(text))
        for m in _LIQUIBASE_TABLE.finditer(text):
            defined_tables.add(_bare(m.group(1) or m.group(2)))
        for m in _ENTITY.finditer(text):
            name = m.group(1)
            defined_tables.update({name.upper(), re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).upper()})
        defined_routines.update(_bare(m.group(1)) for m in _CREATE_ROUTINE.finditer(text))
    has_drl = any(rel.endswith(".drl") for rel, _ in files)

    for rel, text in files:
        suffix = Path(rel).suffix.lower()
        code = suffix not in (".properties", ".yml", ".yaml")
        if code:
            for pattern in _MESSAGE_USE:
                if pattern is _MESSAGE_USE[0] and suffix in (".java", ".kt", ".groovy"):
                    continue                       # #{…} in Java is SpEL, not a message key
                for m in pattern.finditer(text):
                    key = m.group(1)
                    if key not in defined_keys and not key.startswith(_FRAMEWORK_KEYS):
                        add("Message texts not in the repository", key, "message key", rel, _line(text, m.start()))
        if suffix in (".java", ".kt", ".groovy", ".js", ".ts", ".jsx", ".tsx"):
            for pattern, kind in _HTTP:
                for m in pattern.finditer(text):
                    if kind == "RestTemplate call" and "RestTemplate" not in text and "restTemplate" not in text:
                        continue
                    ref = (m.group(1) or kind) if m.groups() else kind
                    add("External services", re.sub(r"\s+", " ", ref.strip())[:120], kind, rel, _line(text, m.start()))
        if suffix in (".java", ".kt", ".groovy"):
            for pattern, kind in _RUNTIME:
                for m in pattern.finditer(text):
                    if kind == "rules engine" and has_drl:
                        continue
                    add("Logic evaluated at run time", kind, "rules loaded from outside the repository"
                        if kind == "rules engine" else kind, rel, _line(text, m.start()))
            for pattern, kind in _SWITCHES:
                for m in pattern.finditer(text):
                    ref = re.sub(r"\s+", " ", m.group(1)).strip()[:120] if m.groups() and m.group(1) else kind
                    add("Feature switches", ref, kind, rel, _line(text, m.start()))
        # SQL: in .sql / mapper XML text, and in string literals of code.
        chunks = [(0, text)] if suffix in (".sql", ".pls", ".pks", ".pkb", ".plsql", ".xml") else \
            [(m.start(1), m.group(1)) for m in _SQL_LITERAL.finditer(text)] if code else []
        for offset, chunk in chunks:
            for m in _SQL_REF.finditer(chunk):
                name = m.group(1)
                if name.lower() in _KEYWORDS or "(" in name or _bare(name) in defined_tables:
                    continue
                if not re.search(r"[A-Za-z]", name) or name.startswith(("#", "$")):
                    continue
                add("Database tables with no definition here", name, "table or view", rel,
                    _line(text, offset + m.start()))
        for pattern in _PROC_CALL:
            for m in pattern.finditer(text):
                if _bare(m.group(1)) not in defined_routines:
                    add("Stored procedures and functions not in the repository", m.group(1), "stored routine", rel,
                        _line(text, m.start()))
    order = ["Message texts not in the repository", "External services", "Database tables with no definition here",
             "Stored procedures and functions not in the repository", "Logic evaluated at run time",
             "Feature switches"]
    return sorted(found.values(), key=lambda r: (order.index(r["category"]), r["reference"].lower()))


_NOTES = {
    "Message texts not in the repository": "The text users see for these keys is not in the repository (another "
                                           "bundle, a database or a message service); rules that quote them cannot "
                                           "give the wording.",
    "External services": "Decisions taken by these services are not in this code; only how this application "
                         "calls them and uses the answer is.",
    "Database tables with no definition here": "No CREATE TABLE, @Table or @Entity in the repository defines these; "
                                               "codes, limits or configuration held in them may be rules.",
    "Stored procedures and functions not in the repository": "Called here but created elsewhere: their logic is not "
                                                             "in this repository.",
    "Logic evaluated at run time": "What these evaluate is decided at run time (expressions, scripts, classes or "
                                   "rules loaded from configuration or storage).",
    "Feature switches": "Which code runs depends on configuration or a flag service; the active setting per "
                        "environment is not in the code.",
}


def to_markdown(rows: list[dict]) -> str:
    lines = [HEADING, "",
             "_Found by reading the source text for references the repository does not resolve — a heuristic, not a "
             "proof: it lists what the code points to outside itself, so these gaps are reviewed rather than assumed "
             "away. Framework defaults (for example Spring's response to invalid input) are not listed._", ""]
    if not rows:
        return "\n".join(lines + ["Nothing found."])
    for category in dict.fromkeys(r["category"] for r in rows):
        group = [r for r in rows if r["category"] == category]
        lines += [f"### {category} ({len(group)})", "", _NOTES[category], "",
                  "| Reference | Kind | Used at |", "|---|---|---|"]
        lines += ["| `" + r["reference"].replace("|", "\\|").replace("`", "'") + f"` | {r['kind']} | "
                  + "; ".join(f"`{w}`" for w in r["where"]) + " |" for r in group]
        lines.append("")
    return "\n".join(lines).rstrip()
