"""
Tech debt and dead-code candidates — computed from the repository without a
model, for a person to review.

Two kinds of finding, every one with the file:line that shows it:

- **Dead-code candidates**: classes nothing references, front-end modules
  nothing imports, page templates no handler renders and nothing includes,
  private methods never called, repository methods never called, tables no code
  touches, REST endpoints no UI control in the repository calls, and blocks of
  commented-out code. "Nothing references" is a text search over every source,
  configuration and template file, so reflection, external callers and
  configuration outside the repository can make a candidate live — each row
  carries a confidence and the reason, and the reviewer decides.
- **Tech debt**: marked debt (TODO / FIXME / HACK), code marked `@Deprecated`
  but still present, exceptions caught and dropped, broad catches, console
  output, SQL built by string concatenation, credentials written in
  configuration or code, hard-coded hosts, very large classes, field injection,
  JDK-internal and legacy APIs, `Thread.sleep` in application code, schema
  auto-update and debug settings left on, and security settings switched off.

The layered reverse-engineering passes add what they observe while tracing
(their "Tech Debt & Dead Code" evidence); `to_markdown` merges both into the
deliverable, with an empty review column for the decision.
"""
from __future__ import annotations

import re
from pathlib import Path

from .dependency_graph import EXCLUDED_DIRS

HEADING = "# Tech Debt & Dead Code — for review"
_TEST = re.compile(r"(?:^|/)(?:src/test|test|tests|__tests__|spec|e2e)/", re.I)
_VENDOR = re.compile(r"(?:^|/)(?:node_modules|vendor|vendors|lib|libs|third[-_]?party|bower_components)/")
_JVM = {".java", ".kt", ".groovy", ".scala"}
_FRONT = {".js", ".jsx", ".ts", ".tsx", ".vue", ".mjs"}
_TEXT = _JVM | _FRONT | {".xml", ".properties", ".yml", ".yaml", ".jsp", ".jspf", ".tag", ".html", ".htm",
                         ".sql", ".json", ".gradle", ".kts", ".conf", ".ftl", ".vm", ".hbs", ".py", ".cs"}
MAX_FILE_BYTES = 2_000_000

_ENTRY_ANNOTATIONS = re.compile(
    r"@(?:Controller|RestController|Component|Service|Repository|Configuration|SpringBootApplication|Entity|"
    r"Embeddable|MappedSuperclass|ControllerAdvice|RestControllerAdvice|WebServlet|WebFilter|WebListener|Path|"
    r"Provider|Aspect|Named|Stateless|Stateful|Singleton|MessageDriven|ApplicationScoped|RequestScoped|"
    r"SessionScoped|Dependent|Mapper|FeignClient|Converter|ConfigurationProperties|EnableAutoConfiguration|"
    r"Endpoint|WebService|WebEndpoint|Startup|ApplicationPath|FacesConverter|ManagedBean|SpringBootTest|"
    r"Document|Table|ConstructorBinding|AutoConfiguration|EnableWebSecurity|ServerEndpoint|Mojo)\b")
_FRAMEWORK_BASE = re.compile(r"\b(?:extends|implements)\s+[\w.<>, ]*\b(?:\w*Repository|HttpServlet|Filter|"
                             r"ServletContextListener|WebMvcConfigurer|ApplicationRunner|CommandLineRunner|"
                             r"SpringBootServletInitializer|Application|AbstractAnnotationConfigDispatcherServlet"
                             r"Initializer|WebApplicationInitializer|Plugin|Extension)\b")
_CLASS = re.compile(r"^\s*(?:public\s+|protected\s+|private\s+)?(?:abstract\s+|final\s+|sealed\s+|static\s+)*"
                    r"(?:class|interface|enum|record|@interface|object)\s+(\w+)", re.M)
_PRIVATE_METHOD = re.compile(r"^\s*private\s+(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?(?:<[^>]+>\s+)?"
                             r"[\w.<>\[\], ?]+\s+(\w+)\s*\([^;{]*\)\s*(?:throws\s+[\w.,\s]+)?\{", re.M)
_REPO_METHOD = re.compile(r"^\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:public\s+|default\s+)?[\w.<>\[\], ?]+\s+"
                          r"((?:find|get|read|query|count|exists|delete|remove|stream|search)\w*)\s*\(", re.M)


def _files(root: Path) -> list[tuple[str, str]]:
    out = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT:
            continue
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(Path(rel).parts) or _VENDOR.search(rel) or path.name.endswith(".min.js") \
                or path.name in ("package-lock.json", "yarn.lock"):
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


def _strip_comments(code: str) -> str:
    """Java/JS source without comments and string contents (line count kept)."""
    out = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), code, flags=re.S)
    out = re.sub(r"//[^\n]*", "", out)
    return re.sub(r"\"(?:[^\"\\\n]|\\.)*\"", '""', out)


def _block_after(text: str, open_at: int) -> tuple[int, int]:
    depth, i = 0, open_at
    while i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return open_at, i
        i += 1
    return open_at, len(text)


# ─────────────────────────────────────────────────────────────────────────────
# Scan
# ─────────────────────────────────────────────────────────────────────────────

def scan(workspace_dir: str, ui_result: dict | None = None, database: dict | None = None,
         observability: dict | None = None, security: dict | None = None) -> dict:
    """{"dead": [...], "debt": [...]} — rows {category, item, detail, where, confidence}."""
    root = Path(workspace_dir)
    if not root.is_dir():
        return {"dead": [], "debt": []}
    files = _files(root)
    dead: list[dict] = []
    debt: list[dict] = []

    def add(bucket, category, item, detail, where, confidence):
        bucket.append({"category": category, "item": item, "detail": detail, "where": where,
                       "confidence": confidence})

    corpus: dict[str, str] = {rel: text for rel, text in files}
    app = [(rel, text) for rel, text in files if not _TEST.search(rel)]
    # Every identifier-ish word, per file — for "is X named anywhere else".
    words_by_file = {rel: set(re.findall(r"[A-Za-z_$][\w$]*", text)) for rel, text in files}

    def named_elsewhere(word: str, own: str, include_tests: bool = False) -> bool:
        for rel, words in words_by_file.items():
            if rel == own or (not include_tests and _TEST.search(rel)):
                continue
            if word in words:
                return True
        return False

    # ── dead code: classes nothing references ────────────────────────────────
    for rel, text in app:
        if Path(rel).suffix.lower() not in _JVM or rel.endswith(("package-info.java", "module-info.java")):
            continue
        m = _CLASS.search(text)
        if not m:
            continue
        name = m.group(1)
        if _ENTRY_ANNOTATIONS.search(text[:m.end() + 200]) or _FRAMEWORK_BASE.search(text[m.start():m.end() + 300]) \
                or re.search(r"\bstatic\s+void\s+main\s*\(", text) or re.search(r"\bfun\s+main\s*\(", text):
            continue
        if not named_elsewhere(name, rel):
            used_in_tests = named_elsewhere(name, rel, include_tests=True)
            add(dead, "Class referenced by nothing", name,
                "No other source, configuration or template file names it"
                + (" (only tests do)" if used_in_tests else "") + "; no framework annotation or main method.",
                f"{rel}:{_line(text, m.start())}", "Medium" if used_in_tests else "High")

    # ── dead code: private methods never called ──────────────────────────────
    for rel, text in app:
        if Path(rel).suffix.lower() not in (".java", ".groovy"):
            continue
        code = _strip_comments(text)
        for m in _PRIVATE_METHOD.finditer(code):
            name = m.group(1)
            if name in ("readObject", "writeObject", "readResolve", "writeReplace", "readObjectNoData") \
                    or re.search(r"@(?:PostConstruct|PreDestroy|Scheduled|EventListener|Bean|Test|"
                                 r"JsonCreator|JsonProperty|Subscribe)\b", code[max(0, m.start() - 200):m.start()]):
                continue
            uses = len(re.findall(rf"\b{re.escape(name)}\s*\(", code)) + len(re.findall(rf"::\s*{re.escape(name)}\b",
                                                                                         code))
            if uses <= 1 and not re.search(rf"\"{re.escape(name)}\"", text):
                add(dead, "Private method never called", name, "Declared private and never called in its class.",
                    f"{rel}:{_line(code, m.start())}", "High")

    # ── dead code: repository query methods never called ─────────────────────
    for rel, text in app:
        if Path(rel).suffix.lower() not in _JVM or not re.search(r"interface\s+\w+\s+extends\s+[\w.]*Repository\b",
                                                                 text):
            continue
        for m in _REPO_METHOD.finditer(text):
            name = m.group(1)
            if not named_elsewhere(name, rel):
                add(dead, "Repository method never called", name, "Declared on a repository; no other file calls it.",
                    f"{rel}:{_line(text, m.start())}", "High")

    # ── dead code: front-end modules nothing imports ─────────────────────────
    entry_names = {"index", "main", "app", "setuptests", "serviceworker", "reportwebvitals", "vite.config",
                   "webpack.config", "babel.config", "jest.config", "router", "routes", "store", "polyfills",
                   "environment", "eslint.config", "tailwind.config", "postcss.config", "karma.conf"}
    for rel, text in app:
        p = Path(rel)
        if p.suffix.lower() not in _FRONT or p.stem.lower() in entry_names or p.stem.lower().endswith((".config",
                                                                                                         ".test", ".spec",
                                                                                                         ".d")):
            continue
        stem = p.stem
        referenced = any(o != rel and (re.search(rf"['\"/]{re.escape(stem)}(?:\.\w+)?['\"]", t) or
                                       re.search(rf"[/'\"]{re.escape(p.name)}\b", t))
                         for o, t in corpus.items())
        if not referenced:
            add(dead, "Front-end module nothing imports", rel, "No import, require or <script src> names it.",
                f"{rel}:1", "Medium")

    # ── dead code: templates nothing renders or includes ─────────────────────
    templates = [(rel, text) for rel, text in app
                 if (re.search(r"(?:^|/)templates/", rel) and rel.endswith((".html", ".ftl", ".vm", ".hbs")))
                 or rel.endswith((".jsp", ".jspf"))]
    for rel, text in templates:
        tail = re.split(r"(?:^|/)(?:templates|WEB-INF/views|WEB-INF/jsp|WEB-INF|webapp)/", rel)[-1]
        view = re.sub(r"\.\w+$", "", tail)
        base = Path(rel).name
        refs = [o for o, t in corpus.items() if o != rel and (view in t or base in t)]
        if not refs:
            add(dead, "Page template nothing renders or includes", rel,
                f"No handler returns view `{view}` and no page includes or links it.", f"{rel}:1", "Medium")

    # ── dead code: tables no code touches ────────────────────────────────────
    for obj in (database or {}).get("objects", []):
        if not obj["kind"].startswith(("TABLE", "VIEW")):
            continue
        name = obj["name"].split(".")[-1]
        users = [rel for rel, t in corpus.items() if not rel.endswith((".sql", ".pls", ".pks", ".pkb"))
                 and re.search(rf"\b{re.escape(name)}\b", t, re.I)]
        if not users:
            add(dead, "Table or view no application code uses", name,
                "Defined in DDL; named by no Java/JS/XML/configuration file (it may be used by other systems, "
                "triggers or reports).", obj["where"], "Low")

    # ── dead code: REST endpoints no UI calls ────────────────────────────────
    if ui_result and ui_result.get("screens"):
        for c in ui_result.get("contracts", []):
            if c.get("kind") == "REST" and not c.get("called_by"):
                add(dead, "REST endpoint no UI control calls", c["endpoint"],
                    f"Handled by `{c['handler']}`; no screen in this repository calls it (other systems may).",
                    c["source"], "Low")

    # ── dead code: commented-out code ────────────────────────────────────────
    for rel, text in app:
        if Path(rel).suffix.lower() not in _JVM | _FRONT:
            continue
        run_start, run = None, 0
        lines = text.splitlines()
        for n, line in enumerate(lines + [""], 1):
            s = line.strip()
            codeish = s.startswith("//") and re.search(r"[;{}]\s*$|^\s*//\s*(?:if|for|return|import|public|private)\b",
                                                       s)
            if codeish:
                run_start = run_start or n
                run += 1
            else:
                if run >= 3:
                    add(dead, "Commented-out code", f"{run} lines", "Consecutive commented-out statements.",
                        f"{rel}:{run_start}", "High")
                run_start, run = None, 0

    # ── tech debt ────────────────────────────────────────────────────────────
    for rel, text in app:
        suffix = Path(rel).suffix.lower()
        if suffix in _JVM | _FRONT | {".jsp", ".sql", ".py", ".cs"}:
            for m in re.finditer(r"(?://|#|/\*|\*|<!--|--)\s*(TODO|FIXME|HACK|XXX|KLUDGE|WORKAROUND)\b[:\s]*(.{0,140})",
                                 text):
                add(debt, f"Marked in code: {m.group(1)}", m.group(2).strip(" */-") or m.group(1), "",
                    f"{rel}:{_line(text, m.start())}", "High")
        if suffix in _JVM:
            code = _strip_comments(text)
            for m in re.finditer(r"@Deprecated\b", code):
                decl = re.search(r"(?:class|interface|enum|\w+\s*\()", code[m.end():m.end() + 300])
                add(debt, "Code marked @Deprecated still present", decl.group(0).rstrip("(") if decl else "",
                    "", f"{rel}:{_line(code, m.start())}", "High")
            for m in re.finditer(r"catch\s*\(([^)]*)\)\s*\{", code):
                _, end = _block_after(code, m.end() - 1)
                body = code[m.end():end].strip()
                where = f"{rel}:{_line(code, m.start())}"
                if not body:
                    add(debt, "Exception caught and ignored (empty catch)", m.group(1).strip(), "", where, "High")
                elif re.fullmatch(r"\w+\s*\.\s*printStackTrace\s*\(\s*\)\s*;", body):
                    add(debt, "Exception only printed (printStackTrace)", m.group(1).strip(), "", where, "High")
                if re.match(r"\s*(?:final\s+)?(?:java\.lang\.)?(?:Exception|Throwable|RuntimeException)\s+\w+\s*$",
                            m.group(1)):
                    add(debt, "Broad catch (Exception / Throwable)", m.group(1).strip(), "", where, "Medium")
            for m in re.finditer(r"System\s*\.\s*(?:out|err)\s*\.\s*print", code):
                add(debt, "Console output instead of logging", "System.out / System.err", "",
                    f"{rel}:{_line(code, m.start())}", "High")
            for m in re.finditer(r"\"(?:[^\"\\]|\\.)*\b(?:SELECT|INSERT|UPDATE|DELETE|WHERE|VALUES)\b(?:[^\"\\]|\\.)*\""
                                 r"\s*\+\s*(?!\")[\w.()]+", text, re.I):
                add(debt, "SQL built by string concatenation (injection risk)", m.group(0)[:120], "",
                    f"{rel}:{_line(text, m.start())}", "Medium")
            for m in re.finditer(r"(?i)\b(?:password|passwd|pwd|secret|apikey|api_key|token)\w*\s*=\s*\"([^\"]{3,})\"",
                                 text):
                if not m.group(1).startswith(("${", "#{")):
                    add(debt, "Credential written in code", m.group(0).split("=")[0].strip(), "value not shown",
                        f"{rel}:{_line(text, m.start())}", "Medium")
            for m in re.finditer(r"\"(https?://(?!(?:www\.)?(?:w3\.org|springframework\.org|java\.sun\.com|"
                                 r"xmlns\.jcp\.org|schemas\.|maven\.apache\.org|localhost\b))[^\"\s]+)\"", code):
                add(debt, "Hard-coded URL in code", m.group(1)[:120], "", f"{rel}:{_line(code, m.start())}", "Medium")
            lines = text.count("\n") + 1
            if lines > 1000:
                add(debt, "Very large source file", f"{lines} lines", "", f"{rel}:1", "Medium")
            methods = len(re.findall(r"^\s*(?:public|protected|private)\s+[\w<>\[\], ?]+\s+\w+\s*\([^;]*\)\s*"
                                     r"(?:throws[^{]*)?\{", code, re.M))
            if methods > 40:
                add(debt, "Class with very many methods", f"{methods} methods", "", f"{rel}:1", "Medium")
            fields = len(re.findall(r"@Autowired\s+(?:private|protected|public)?\s*(?:final\s+)?[\w.<>, ]+\s+\w+\s*;",
                                    code))
            if fields:
                add(debt, "Field injection (@Autowired on fields)", f"{fields} field(s)", "", f"{rel}:1", "Low")
            for m in re.finditer(r"^\s*import\s+(sun\.[\w.]+|com\.sun\.(?!xml\.bind|net\.httpserver)[\w.]+|"
                                 r"java\.util\.(?:Vector|Hashtable|Stack)|java\.lang\.StringBuffer)\s*;", text, re.M):
                add(debt, "JDK-internal or legacy API in use", m.group(1), "", f"{rel}:{_line(text, m.start())}",
                    "Medium")
            for m in re.finditer(r"\bThread\s*\.\s*sleep\s*\(", code):
                add(debt, "Thread.sleep in application code", "Thread.sleep", "", f"{rel}:{_line(code, m.start())}",
                    "Low")
            for m in re.finditer(r"@SuppressWarnings\s*\(([^)]*)\)", code):
                add(debt, "Compiler warnings suppressed", m.group(1).strip(), "", f"{rel}:{_line(code, m.start())}",
                    "Low")
        if suffix in _FRONT:
            for m in re.finditer(r"\bconsole\s*\.\s*(?:log|debug)\s*\(", text):
                add(debt, "Debug console output in front-end code", "console.log", "",
                    f"{rel}:{_line(text, m.start())}", "Low")
            for m in re.finditer(r"\beval\s*\(|\.innerHTML\s*=", text):
                add(debt, "eval / innerHTML assignment (injection risk)", m.group(0).strip(), "",
                    f"{rel}:{_line(text, m.start())}", "Medium")
        if suffix in (".properties", ".yml", ".yaml"):
            from .system_inventory import _config_entries
            for key, value, n in _config_entries(rel, text):
                k = key.lower()
                where = f"{rel}:{n}"
                if re.search(r"(?:password|passwd|secret|token|api[-_.]?key|credentials?)$", k) and value \
                        and not value.startswith(("${", "ENC(", "#{", "sm://", "vault:")) and value not in ('""', "''"):
                    add(debt, "Credential written in configuration", key, "value not shown", where, "High")
                if k.endswith(("ddl-auto", "hbm2ddl.auto")) and value.lower() in ("update", "create", "create-drop"):
                    add(debt, "Schema changed automatically at start-up", f"{key} = {value}", "", where, "High")
                if k.endswith("show-sql") and value.lower() == "true" or \
                        (k.startswith("logging.level") and value.upper() in ("DEBUG", "TRACE")):
                    add(debt, "Debug output enabled in configuration", f"{key} = {value}", "", where, "Low")
                if k.endswith("exposure.include") and value.strip() == "*":
                    add(debt, "Every management endpoint exposed", f"{key} = {value}", "", where, "High")

    # ── security and logging settings, from the System Inventory ─────────────
    for r in (security or {}).get("rows", []):
        if r["kind"] == "CSRF" and re.search(r"disable", r["detail"], re.I):
            add(debt, "CSRF protection switched off", r["detail"], "", r["where"], "Medium")
        if r["kind"] == "URL rule" and re.search(r"anyRequest\(\)\s*→\s*permitAll|\"/\*\*\"\)\s*→\s*permitAll",
                                                 r["detail"]):
            add(debt, "All requests permitted without authentication", r["detail"], "", r["where"], "High")
        if r["kind"] == "Password encoder" and "NoOp" in r["detail"]:
            add(debt, "Passwords stored without hashing (NoOpPasswordEncoder)", r["detail"], "", r["where"], "High")
    facades = [f for f in (observability or {}).get("facades", {}) if f not in ("Browser console",
                                                                                 "System.out / printStackTrace")]
    if len(facades) > 1:
        add(debt, "Several logging frameworks in use", ", ".join(sorted(facades)), "", "(see System Inventory)",
            "Medium")
    return {"dead": dead, "debt": debt}


_WHY = {
    "Class referenced by nothing": "Unreachable code still compiled, shipped and maintained.",
    "Private method never called": "Cannot be called from outside its class; nothing inside calls it.",
    "Repository method never called": "A query kept alive with no caller.",
    "Front-end module nothing imports": "Shipped or built but never loaded.",
    "Page template nothing renders or includes": "A page no handler returns and no page links or includes.",
    "Table or view no application code uses": "Schema kept with no reader or writer in this code base.",
    "REST endpoint no UI control calls": "An API surface with no caller in this repository.",
    "Commented-out code": "Old code kept as comments obscures what runs.",
}


def to_markdown(found: dict, observations: list[tuple[str, str]] | None = None, title: str = "",
                strategy: str = "") -> str:
    """The review deliverable: counts, then every finding with a review column.
    `observations`: (evidence id, text) the reverse-engineering passes recorded."""
    dead, debt = found.get("dead", []), found.get("debt", [])
    lines = [HEADING + (f" — {title}" if title else ""), "",
             "_A list for a person to decide on, not a verdict. Dead-code candidates come from text searches over "
             "the whole repository: reflection, other systems and configuration outside the repository can make a "
             "candidate live, so each carries a confidence. Fill in the **Decision** column (remove / keep / "
             "investigate)._", ""]
    if strategy:
        lines += [f"Reverse-engineering strategy: **{strategy}**.", ""]
    lines += ["## Summary", "", "| Area | Category | Findings |", "|---|---|---|"]
    for area, rows in (("Dead code", dead), ("Tech debt", debt)):
        for cat in dict.fromkeys(r["category"] for r in rows):
            lines.append(f"| {area} | {cat} | {sum(1 for r in rows if r['category'] == cat)} |")
    if observations:
        lines.append(f"| Observed while tracing | Agent observations | {len(observations)} |")
    if not dead and not debt and not observations:
        lines.append("| — | Nothing found | 0 |")
    lines.append("")

    def table(rows: list[dict]) -> list[str]:
        out = ["| # | Item | Detail | Where | Confidence | Decision |", "|---|---|---|---|---|---|"]
        for n, r in enumerate(rows, 1):
            cells = [str(n), f"`{r['item']}`" if r["item"] else "—", r["detail"] or "—", f"`{r['where']}`",
                     r["confidence"], " "]
            out.append("| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
        return out + [""]

    lines += ["## Dead-Code Candidates", ""]
    if not dead:
        lines += ["_No candidate found._", ""]
    for cat in dict.fromkeys(r["category"] for r in dead):
        rows = [r for r in dead if r["category"] == cat]
        lines += [f"### {cat} ({len(rows)})", "", _WHY.get(cat, ""), ""] + table(rows)
    lines += ["## Tech Debt", ""]
    if not debt:
        lines += ["_No finding._", ""]
    for cat in dict.fromkeys(r["category"] for r in debt):
        rows = [r for r in debt if r["category"] == cat]
        lines += [f"### {cat} ({len(rows)})", ""] + table(rows)
    if observations:
        lines += ["## Observed While Tracing the Flows", "",
                  "_What the reverse-engineering passes recorded as tech debt or dead code while following the "
                  "flows; each is cited to the code and kept only when the cited file exists._", "",
                  "| Evidence | Observation | Decision |", "|---|---|---|"]
        lines += [f"| `{eid}` | {text.replace('|', chr(92) + '|')} |   |" for eid, text in observations]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
