"""
UI-to-backend contracts, read from the code — no model involved.

For every screen, the controls that talk to the server and exactly what they
send and get back, so a developer can rebuild a control and the logic behind it
from one place:

- **The UI side.** Templates (Thymeleaf, JSP, plain HTML, Angular/Vue
  templates) are read for forms (fields and their client-side checks), buttons
  and links, inline handlers (`onclick="search()"`, `(click)`, `@click`),
  server-rendered grids (`th:each` / `c:forEach` rows: their columns and the
  model value behind each) and server-filled selects. Scripts (JavaScript,
  TypeScript, JSX/TSX, the `<script>` of a Vue file and inline `<script>`
  blocks) are read with tree-sitter for HTTP calls — `fetch`, axios / Angular
  `http`, `$.ajax` / `$.get` / `$.post` / `$.getJSON` / `.load`, DataTables and
  jqGrid `ajax`/`url`, `XMLHttpRequest.open`, Backbone `url`/`urlRoot`,
  `location.href = …` — and each call is tied to what triggers it: a jQuery /
  DOM event binding, a Backbone `events` map, a JSX `onClick`, a page-load
  hook, or an inline handler in a template that names the function.
- **The backend side.** Each call is matched to the handler that serves it from
  the computed interface inventory (method and path, `{var}` segments, a
  leading context path). The handler's contract is read from its signature and
  body: request parameters (`@RequestParam`, `@PathVariable`, `@RequestHeader`,
  JAX-RS `@QueryParam`/`@PathParam`/`@FormParam`, `request.getParameter("x")`),
  the request body or form object flattened to its fields with their types and
  validation annotations, the response (the JSON type flattened the same way,
  or the view, its model attributes and redirects), the HTTP statuses the code
  sets, the exceptions it throws with the status an exception handler gives
  them, and the access rule on the handler.

URLs built at run time keep their unknown parts as `{}`. A call the scan
cannot tie to a handler is listed with the reason — nothing is guessed.
"""
import html.parser
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .dependency_graph import EXCLUDED_DIRS
from .rule_candidates import _PARSERS, _TEST_PATH, _VENDORED, VALIDATION_ANNOTATIONS

MAX_FILE_BYTES = 1_000_000
MAX_DEPTH = 8                # nesting levels of a schema; a cycle is cut where it repeats
HEADING = "## UI-to-Backend Contracts (computed)"
CONTRACTS_HEADING = "## Endpoint Contracts (computed)"
ID_RE = re.compile(r"\bUI-\d{3,}\b")

_TEMPLATE_SUFFIXES = (".html", ".htm", ".jsp", ".jspf", ".xhtml", ".ftl", ".vm")
_SCRIPT_SUFFIXES = {".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
                    ".ts": "typescript", ".tsx": "tsx"}
_LIBRARY = re.compile(r"(?:^|/)(?:jquery|bootstrap|backbone|underscore|lodash|require|angular|react|react-dom|vue|"
                      r"moment|popper|d3|chart|datatables|select2|knockout|handlebars|mustache)[\w.-]*\.js$", re.I)
_VERBS = ("GET", "POST", "PUT", "DELETE", "PATCH")
_STATUS = {
    "OK": 200, "CREATED": 201, "ACCEPTED": 202, "NO_CONTENT": 204, "MOVED_PERMANENTLY": 301, "FOUND": 302,
    "SEE_OTHER": 303, "NOT_MODIFIED": 304, "TEMPORARY_REDIRECT": 307, "BAD_REQUEST": 400, "UNAUTHORIZED": 401,
    "FORBIDDEN": 403, "NOT_FOUND": 404, "METHOD_NOT_ALLOWED": 405, "NOT_ACCEPTABLE": 406, "CONFLICT": 409,
    "GONE": 410, "PRECONDITION_FAILED": 412, "PAYLOAD_TOO_LARGE": 413, "REQUEST_ENTITY_TOO_LARGE": 413,
    "UNSUPPORTED_MEDIA_TYPE": 415, "UNPROCESSABLE_ENTITY": 422, "LOCKED": 423, "TOO_MANY_REQUESTS": 429,
    "INTERNAL_SERVER_ERROR": 500, "NOT_IMPLEMENTED": 501, "BAD_GATEWAY": 502, "SERVICE_UNAVAILABLE": 503,
    "GATEWAY_TIMEOUT": 504,
}
_ENTITY_CALLS = {"ok": 200, "created": 201, "accepted": 202, "noContent": 204, "badRequest": 400,
                 "notFound": 404, "unprocessableEntity": 422, "internalServerError": 500}
_SCALARS = {
    "String": "string", "CharSequence": "string", "char": "string", "Character": "string",
    "int": "integer", "Integer": "integer", "short": "integer", "Short": "integer", "byte": "integer",
    "Byte": "integer", "long": "integer (64-bit)", "Long": "integer (64-bit)", "BigInteger": "integer",
    "double": "number", "Double": "number", "float": "number", "Float": "number", "BigDecimal": "decimal",
    "Number": "number", "boolean": "boolean", "Boolean": "boolean", "LocalDate": "date", "Date": "date-time",
    "LocalDateTime": "date-time", "ZonedDateTime": "date-time", "OffsetDateTime": "date-time",
    "Instant": "date-time", "Timestamp": "date-time", "LocalTime": "time", "UUID": "uuid",
    "MultipartFile": "file", "Part": "file", "byte[]": "binary", "Resource": "binary",
    "InputStreamResource": "binary", "Object": "any", "JsonNode": "any JSON", "Void": "empty", "void": "empty",
}
_WRAPPERS = {"Optional", "ResponseEntity", "Mono", "CompletableFuture", "Future", "Callable", "DeferredResult",
             "HttpEntity", "Uni", "CompletionStage", "WebAsyncTask"}
_COLLECTIONS = {"List", "ArrayList", "LinkedList", "Set", "HashSet", "LinkedHashSet", "TreeSet", "SortedSet",
                "Collection", "Iterable", "Flux", "Stream", "Multi"}
# Spring Data's Page / Slice as Jackson writes them: the rows under `content`, then the paging fields.
_PAGED = {"Page": [("totalElements", "integer (64-bit)"), ("totalPages", "integer")],
          "Slice": []}
_PAGE_FIELDS = [("number", "integer (zero-based page index)"), ("size", "integer"),
                ("numberOfElements", "integer"), ("first", "boolean"), ("last", "boolean"), ("empty", "boolean")]
_MAPS = {"Map", "HashMap", "LinkedHashMap", "TreeMap", "SortedMap", "MultiValueMap"}
_FRAMEWORK = re.compile(
    r"^(?:Model|ModelMap|RedirectAttributes|BindingResult|Errors|Principal|Authentication|HttpServletRequest|"
    r"HttpServletResponse|HttpSession|ServletRequest|ServletResponse|WebRequest|NativeWebRequest|Locale|"
    r"SessionStatus|UriComponentsBuilder|Pageable|Sort|ServerWebExchange|OAuth2User|UserDetails|"
    r"ServerHttpRequest|ServerHttpResponse|TimeZone|ZoneId|UriInfo|HttpHeaders|SecurityContext|Request)\b")


# ── small helpers ───────────────────────────────────────────────────────────

def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _annotations(node, src: bytes) -> dict[str, str]:
    out = {}
    for child in node.children:
        if child.type == "modifiers":
            for a in child.children:
                if a.type in ("annotation", "marker_annotation"):
                    name = a.child_by_field_name("name")
                    args = a.child_by_field_name("arguments")
                    out[_text(name, src).rsplit(".", 1)[-1] if name else ""] = _text(args, src) if args else ""
    return out


def _attr(args: str, *keys: str) -> str:
    for key in keys:
        m = re.search(rf"\b{key}\s*=\s*(\"[^\"]*\"|[^,)]+)", args or "")
        if m:
            return m.group(1).strip().strip('"')
    return ""


def _first_string(args: str) -> str:
    """The annotation's value: ("q"), (value = "q"), (name = "q")."""
    named = _attr(args, "value", "name")
    if named:
        return named
    m = re.match(r"\(\s*\"([^\"]*)\"", args or "")
    return m.group(1) if m else ""


def _base(type_text: str) -> str:
    t = re.sub(r"<.*>", "", (type_text or "").strip()).strip()
    t = re.sub(r"^(?:final\s+|@\w+(?:\([^)]*\))?\s+)+", "", t)
    return t.rsplit(".", 1)[-1] if "." in t and not t.endswith("]") else t


def _args(type_text: str) -> list[str]:
    m = re.search(r"<(.*)>\s*$", (type_text or "").strip())
    if not m:
        return []
    out, depth, cur = [], 0, ""
    for ch in m.group(1):
        depth += ch == "<"
        depth -= ch == ">"
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return [re.sub(r"^\?\s*(?:extends|super)\s+", "", a) for a in out]


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _skip(rel: str) -> bool:
    return bool(EXCLUDED_DIRS & set(Path(rel).parts) or _TEST_PATH.search(rel) or _VENDORED.search(rel)
                or ".min." in Path(rel).name or _LIBRARY.search(rel))


# ── URLs ────────────────────────────────────────────────────────────────────

@dataclass
class Url:
    path: str              # "/api/jobs/{}" — unknown parts as {} ; "" when nothing is known
    query: list            # query parameter names written in the URL
    raw: str               # as written
    external: str = ""     # the host, for an absolute URL to another host
    relative: bool = False


def normalize(raw: str) -> Url:
    """A URL as written in a template or script → its path and query names."""
    text = (raw or "").strip().strip("'\"`")
    m = re.search(r"<c:url\s+value\s*=\s*['\"]([^'\"]+)['\"]", text)
    if m:
        text = m.group(1)
    query: list[str] = []
    m = re.fullmatch(r"[@~]\{\s*(.*?)\s*\}", text, re.S)                 # Thymeleaf @{/x/{id}(id=${..},q=..)}
    if m:
        text = m.group(1)
        pm = re.search(r"\(([^()]*)\)\s*$", text)
        if pm:
            text = text[:pm.start()]
            for name in re.findall(r"([A-Za-z_][\w.-]*)\s*=", pm.group(1)):
                if "{" + name + "}" not in text:
                    query.append(name)
    text = re.sub(r"^\s*\|\s*|\s*\|\s*$", "", text)                       # |literal substitution|
    text = re.sub(r"^(?:\$\{[^}]*\}|<%=[^%]*%>|#\{[^}]*\})+(?=/)", "", text)  # context path prefix
    external = ""
    hm = re.match(r"^(?:https?:)?//([^/{}]+)", text)
    if hm:
        host = hm.group(1)
        text = text[hm.end():]
        if not re.match(r"^(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?$", host):
            external = host
    text = text.split("#", 1)[0]
    if "?" in text:
        text, qs = text.split("?", 1)
        query += [k for k in re.findall(r"(?:^|&)([A-Za-z_][\w.\[\]-]*)=", qs)]
    text = re.sub(r"\$\{[^}]*\}|<%=[^%]*%>|#\{[^}]*\}|\[\[.*?\]\]|\{\{.*?\}\}", "{}", text)
    text = re.sub(r"\{[A-Za-z_][\w-]*\}", "{}", text)                     # a named variable is one segment
    relative = bool(text) and not text.startswith("/") and not text.startswith("{}")
    path = "/" + "/".join(s for s in text.split("/") if s)
    path = re.sub(r"\{\}[^/]+|[^/]+\{\}", "{}", path)                   # a partly-known segment is unknown
    if path == "/" and not text.strip("/"):
        path = "/" if text.startswith("/") else ""
    return Url(path, sorted(dict.fromkeys(query)), raw.strip(), external, relative)


def _segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s]


def match(url: Url, verb: str, endpoints: list[dict]) -> tuple[list[dict], str]:
    """The endpoints that serve a call, best first, and why none did."""
    if url.external:
        return [], f"absolute URL to another host ({url.external})"
    if not url.path or url.path == "/{}" or set(_segments(url.path)) <= {"{}"}:
        return [], "URL built at run time — no fixed path to match"

    def score(call: list[str], ep: list[str]) -> int | None:
        if ep and ep[-1] == "**":
            if len(call) < len(ep) - 1:
                return None
            ep = ep[:-1]
            call = call[:len(ep)]
        if len(call) != len(ep):
            return None
        s = 0
        for c, e in zip(call, ep):
            variable = e.startswith("{") or e == "*"
            if variable:
                continue
            if c == "{}" or c != e:
                return None
            s += 1
        return s

    def best(call: list[str]) -> list[tuple[int, dict]]:
        found = []
        for e in endpoints:
            s = score(call, _segments(e["path"]))
            if s is not None:
                found.append((s, e))
        return found

    call = _segments(url.path)
    found = best(call)
    if not found and len(call) > 1:                       # a leading context path
        found = best(call[1:])
    if not found:
        return [], "no handler in the code serves this path"
    top = max(s for s, _ in found)
    paths = [e for s, e in found if s == top]
    verbs = [e for e in paths if e["verb"] in (verb, "ANY") or verb == "ANY"]
    if not verbs:
        served = ", ".join(sorted({e["verb"] for e in paths}))
        return [], f"the path is served for {served} only, not {verb}"
    return verbs, ""


# ── UI elements ─────────────────────────────────────────────────────────────

@dataclass
class Element:
    file: str
    line: int
    kind: str              # form | button | link | grid | select | input | script | data model
    label: str
    event: str
    verb: str = ""
    url: Url | None = None
    sends: list = field(default_factory=list)       # parameter / field names the UI sends
    data: str = ""         # server-rendered: the model value the element shows
    columns: list = field(default_factory=list)     # grid: [(header, value)]
    fields: list = field(default_factory=list)      # form: [(name, input, client-side checks)]
    via: str = ""          # how it was tied: "jQuery click binding", "inline onclick → search()", …
    client_type: str = ""  # a response type the client declares (http.get<Job[]>)
    id: str = ""
    endpoints: list = field(default_factory=list)
    reason: str = ""


_FORM_TAGS = {"form", "form:form", "h:form"}
_FIELD_TAGS = {"input", "select", "textarea", "form:input", "form:select", "form:textarea", "form:password",
               "form:checkbox", "form:checkboxes", "form:radiobutton", "form:radiobuttons", "form:hidden",
               "form:errors"}
_INLINE_EVENTS = re.compile(r"^(?:on(\w+)|th:on(\w+)|data-th-on(\w+)|\((\w+)\)|@(\w+)|v-on:(\w+)|ng-(click|submit|change))$")
_EACH_ATTRS = ("th:each", "data-th-each", "ng-repeat", "v-for", "*ngfor")
_HANDLER_CALL = re.compile(r"([A-Za-z_$][\w$]*)\s*\(")
_JS_KEYWORDS = {"if", "for", "while", "return", "function", "new", "typeof", "alert", "confirm", "this",
                "event", "window", "document", "console", "parseInt", "encodeURIComponent", "String", "Number"}


def _label_of(attrs: dict, text: str = "") -> str:
    for key in ("id", "name", "th:object", "modelattribute", "commandname", "formgroup", "aria-label", "title"):
        if attrs.get(key):
            v = attrs[key]
            return f"#{v}" if key == "id" else f"{v}"
    return ""


def _short(text: str, n: int = 40) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[:n - 1] + "…"


def _expr_root(value: str) -> str:
    """`${jobs}` / `${job.name}` / `item in items` → the value path as written."""
    m = re.search(r"[$*]\{\s*([A-Za-z_][\w.]*)", value or "")
    if m:
        return m.group(1)
    m = re.search(r"\b(?:in|of)\s+([A-Za-z_][\w.]*)", value or "")
    return m.group(1) if m else ""


class _TemplateReader(html.parser.HTMLParser):
    """Forms, controls, grids, inline handlers, script includes and inline scripts of one template."""

    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr",
             "form:input", "form:hidden", "form:password", "form:errors", "form:checkbox", "form:radiobutton"}

    def __init__(self, rel: str):
        super().__init__(convert_charrefs=True)
        self.rel = rel
        self.elements: list[Element] = []
        self.handlers: list[tuple[str, str, str, int, str]] = []   # (function, event, label, line, kind)
        self.scripts: list[str] = []                               # script src as written
        self.inline: list[tuple[int, str]] = []                    # (first line, code)
        self.ids: set[str] = set()
        self._forms: list[Element] = []
        self._tables: list[dict] = []
        self._capture: list[dict] = []        # elements whose text is being read (buttons, links, th)
        self._script: dict | None = None
        self._stack: list[str] = []

    def _line(self) -> int:
        return self.getpos()[0]

    def handle_starttag(self, tag, attrs_list):
        a = {k.lower(): (v or "") for k, v in attrs_list}
        tag = tag.lower()
        line = self._line()
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "script":
            src = a.get("th:src") or a.get("src") or a.get("data-th-src")
            if src:
                self.scripts.append(src)
                if a.get("data-main"):
                    self.scripts.append(a["data-main"] + ".js")
            self._script = {"line": line, "code": [], "src": bool(src)}
        if tag in _FORM_TAGS:
            action = a.get("th:action") or a.get("data-th-action") or a.get("action") or ""
            verb = (a.get("th:method") or a.get("method") or "GET").upper()
            form = Element(self.rel, line, "form", _label_of(a) or "form", "submit", verb,
                           normalize(action) if action else None)
            if not action:
                form.reason = "the form has no action — it posts back to the page's own URL"
            obj = a.get("th:object") or a.get("modelattribute") or a.get("commandname")
            if obj:
                form.data = _expr_root(obj) or obj
            self._forms.append(form)
            self.elements.append(form)
        if self._forms and tag in _FIELD_TAGS and tag != "form:errors":
            name = a.get("name") or a.get("path") or ""
            tf = a.get("th:field") or a.get("data-th-field") or ""
            if tf:
                name = name or re.sub(r"^[*$]\{\s*|\s*\}$", "", tf)
            name = name or a.get("formcontrolname") or a.get("ng-model") or a.get("v-model") or ""
            itype = a.get("type", "text" if tag.endswith("input") else tag.split(":")[-1])
            if name and name != "_csrf" and itype not in ("submit", "button", "reset", "image"):
                checks = [k if not a[k] else f"{k}={a[k]}" for k in
                          ("required", "maxlength", "minlength", "min", "max", "pattern", "step", "accept")
                          if k in a]
                if itype in ("email", "number", "date", "url", "tel", "file", "datetime-local"):
                    checks.insert(0, f"type={itype}")
                self._forms[-1].fields.append((name, itype, ", ".join(checks)))
                self._forms[-1].sends.append(name)
        if tag in ("button", "a", "input") or (tag in ("select", "form:select") and not self._forms):
            itype = a.get("type", "")
            capture = {"tag": tag, "attrs": a, "line": line, "text": [], "form": self._forms[-1] if self._forms else None}
            if tag == "input" and itype in ("submit", "button", "image"):
                capture["text"].append(a.get("value", ""))
                self._finish_control(capture)
            elif tag in ("button", "a"):
                self._capture.append(capture)
            if tag in ("select", "form:select"):
                self._capture.append(capture)
        for name, value in a.items():
            m = _INLINE_EVENTS.match(name)
            if not m or not value:
                continue
            event = next(g for g in m.groups() if g).lower()
            for fn in _HANDLER_CALL.findall(value):
                if fn not in _JS_KEYWORDS:
                    self.handlers.append((fn, event, f"{tag} {_label_of(a)}".strip(), line, tag))
                    if tag in ("button", "a") and self._capture and self._capture[-1]["tag"] == tag:
                        self._capture[-1].setdefault("handlers", []).append(len(self.handlers) - 1)
        if tag == "table":
            self._tables.append({"line": line, "attrs": a, "headers": [], "cells": [], "data": "", "in_th": None})
        if self._tables:
            t = self._tables[-1]
            each = next((a[k] for k in _EACH_ATTRS if a.get(k)), "") or a.get("items", "") if tag in (
                "tr", "c:foreach", "ui:repeat", "tbody", "div", "li") else ""
            if each and not t["data"]:
                m = re.match(r"\s*(?:let\s+)?(\w+)\s*(?:,\s*\w+\s*)?(?::|\bin\b|\bof\b)\s*(.*)$", each, re.S)
                t["data"] = _expr_root(m.group(2)) if m else _expr_root(each)
                t["var"] = m.group(1) if m else a.get("var", "")
                if tag == "c:foreach":
                    t["var"] = a.get("var", "")
            if tag == "th":
                t["in_th"] = []
            if tag == "td" and t["data"]:
                value = a.get("th:text") or a.get("th:utext") or a.get("data-th-text") or ""
                t["cells"].append([value, line])
        if tag in ("select", "form:select"):
            items = a.get("items") or ""
            if items:
                self.elements.append(Element(self.rel, line, "select", _label_of(a) or "select",
                                             "page load (server-rendered)", data=_expr_root(items)))
        if tag == "option":
            each = a.get("th:each") or a.get("data-th-each") or a.get("ng-repeat") or a.get("v-for") or ""
            if each:
                m = re.match(r"\s*(\w+)\s*(?:,\s*\w+\s*)?(?::|\bin\b|\bof\b)\s*(.*)$", each, re.S)
                sel = next((c for c in reversed(self._capture) if c["tag"] in ("select", "form:select")), None)
                label = _label_of(sel["attrs"]) if sel else ""
                self.elements.append(Element(self.rel, line, "select", label or "select",
                                             "page load (server-rendered)",
                                             data=_expr_root(m.group(2) if m else each)))
        if tag not in self._VOID:
            self._stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._VOID:
            self.handle_endtag(tag)

    def _finish_control(self, c: dict):
        a, tag, text = c["attrs"], c["tag"], _short(" ".join(c["text"]))
        label = f"{tag} \"{text}\"" if text else f"{tag} {_label_of(a)}".strip()
        for i in c.get("handlers", []):
            fn, event, _, line, t = self.handlers[i]
            self.handlers[i] = (fn, event, label, line, t)
        if tag == "a":
            href = a.get("th:href") or a.get("data-th-href") or a.get("href") or ""
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")) or \
                    re.search(r"\.(?:css|js|png|jpe?g|gif|svg|ico|pdf|zip|woff2?)(?:$|\?)", href, re.I):
                return
            url = normalize(href)
            if url.external:
                return
            self.elements.append(Element(self.rel, c["line"], "link", label, "click (navigation)", "GET", url))
            return
        itype = a.get("type", "submit" if tag == "button" and c["form"] else "button")
        formaction = a.get("th:formaction") or a.get("formaction")
        if formaction:
            verb = (a.get("formmethod") or (c["form"].verb if c["form"] else "GET")).upper()
            self.elements.append(Element(self.rel, c["line"], "button", label, "click (submits the form)", verb,
                                         normalize(formaction), list(c["form"].sends) if c["form"] else []))
        elif itype in ("submit", "image") and c["form"] is not None:
            c["form"].label = f"{c['form'].label} — {label}" if " — " not in c["form"].label else \
                f"{c['form'].label}, {label}"

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "script" and self._script is not None:
            if not self._script["src"] and self._script["code"]:
                self.inline.append((self._script["line"], "".join(self._script["code"])))
            self._script = None
        for c in reversed(self._capture):
            if c["tag"] == tag:
                self._capture.remove(c)
                if tag in ("button", "a"):
                    self._finish_control(c)
                break
        if tag in _FORM_TAGS and self._forms:
            self._forms.pop()
        if self._tables and tag == "th":
            t = self._tables[-1]
            if t["in_th"] is not None:
                t["headers"].append(_short(" ".join(t["in_th"]), 30))
                t["in_th"] = None
        if tag == "table" and self._tables:
            t = self._tables.pop()
            if t["data"]:
                var = t.get("var", "")
                cols = []
                for i, (value, _) in enumerate(t["cells"]):
                    root = _expr_root(value)
                    if var and root.split(".")[0] == var:
                        root = t["data"] + "[]" + root[len(var):]
                    header = t["headers"][i] if i < len(t["headers"]) else ""
                    if header or root:
                        cols.append((header, root))
                self.elements.append(Element(self.rel, t["line"], "grid", _label_of(t["attrs"]) or "table",
                                             "page load (server-rendered)", data=t["data"], columns=cols))
        while self._stack:
            if self._stack.pop() == tag:
                break

    def handle_data(self, data):
        if self._script is not None:
            self._script["code"].append(data)
            return
        for c in self._capture:
            c["text"].append(data)
        if self._tables:
            t = self._tables[-1]
            if t["in_th"] is not None:
                t["in_th"].append(data)
            elif t["cells"] and "${" in data and not t["cells"][-1][0]:
                t["cells"][-1][0] = data


# ── scripts ─────────────────────────────────────────────────────────────────

@dataclass
class Call:
    line: int
    verb: str
    url: Url
    sends: list
    node: object
    element: str = ""          # a selector the call itself names (DataTable grid, $('#x').load)
    kind: str = "script"
    client_type: str = ""
    param_arg: int | None = None   # the payload is the enclosing function's argument n: the caller names it


def _str_value(node, src: bytes, consts: dict) -> str | None:
    """A JS expression as a URL template: literals kept, anything else `{}`."""
    if node is None:
        return None
    t = node.type
    if t == "string":
        return _text(node, src)[1:-1]
    if t == "template_string":
        out = ""
        for c in node.children:
            if c.type == "string_fragment":
                out += _text(c, src)
            elif c.type == "template_substitution":
                inner = next((g for g in c.children if g.is_named), None)
                known = consts.get(_text(inner, src)) if inner is not None and inner.type == "identifier" else None
                out += known if known is not None else "{}"
            elif c.type == "escape_sequence":
                out += _text(c, src)
        return out
    if t == "binary_expression" and _text(node.child_by_field_name("operator"), src) == "+":
        left = _str_value(node.child_by_field_name("left"), src, consts)
        right = _str_value(node.child_by_field_name("right"), src, consts)
        return (left if left is not None else "{}") + (right if right is not None else "{}")
    if t == "identifier":
        return consts.get(_text(node, src), "{}")
    if t == "parenthesized_expression":
        inner = [c for c in node.children if c.is_named]
        return _str_value(inner[0], src, consts) if inner else None
    if t in ("member_expression", "call_expression", "subscript_expression"):
        return "{}"
    return None


def _object_pairs(node, src: bytes) -> dict:
    out = {}
    if node is None or node.type != "object":
        return out
    for p in node.children:
        if p.type == "pair":
            key = p.child_by_field_name("key")
            k = _text(key, src).strip("'\"`")
            out[k] = p.child_by_field_name("value")
        elif p.type == "shorthand_property_identifier":
            out[_text(p, src)] = p
        elif p.type == "method_definition":
            out[_text(p.child_by_field_name("name"), src)] = p
    return out


def _sent_names(node, src: bytes, consts: dict) -> list[str]:
    """Field names in a request payload: an object literal, JSON.stringify({..}), $(form).serialize()."""
    if node is None:
        return []
    if node.type == "object":
        return [k for k in _object_pairs(node, src)]
    if node.type == "call_expression":
        fn = _text(node.child_by_field_name("function"), src)
        args = [c for c in node.child_by_field_name("arguments").children if c.is_named]
        if fn.endswith("JSON.stringify") and args:
            return _sent_names(args[0], src, consts)
        if fn.endswith((".serialize", ".serializeArray")):
            return [f"(all fields of {_text(node.child_by_field_name('function').child_by_field_name('object'), src)})"]
    return []


def _form_data_names(fn_node, src: bytes) -> list[str]:
    return re.findall(r"\.append\(\s*['\"]([\w.\[\]-]+)['\"]", _text(fn_node, src)) if fn_node is not None else []


def _selector_of(node, src: bytes, aliases: dict) -> str:
    """`$('#save')`, `document.getElementById('save')`, `document.querySelector('.x')`, or a variable holding one."""
    if node is None:
        return ""
    if node.type == "identifier":
        return aliases.get(_text(node, src), "")
    if node.type == "call_expression":
        fn = _text(node.child_by_field_name("function"), src)
        args = [c for c in node.child_by_field_name("arguments").children if c.is_named]
        if not args:
            return ""
        lit = _text(args[0], src).strip("'\"`") if args[0].type in ("string", "template_string") else ""
        if fn in ("$", "jQuery"):
            if _text(args[0], src) in ("document", "window"):
                return "document"
            return lit
        if fn.endswith("getElementById"):
            return "#" + lit if lit else ""
        if fn.endswith(("querySelector", "querySelectorAll")):
            return lit
        if fn.endswith((".find", ".closest", ".children")):
            return lit
    if node.type == "member_expression" and _text(node, src) in ("document", "window", "document.body"):
        return "document"
    return ""


_LOAD_HOOKS = {"ngOnInit", "componentDidMount", "mounted", "created", "beforeMount", "onMounted", "initialize"}
_JQ_EVENTS = {"click", "submit", "change", "keyup", "keydown", "keypress", "input", "blur", "focus", "dblclick",
              "select", "load"}


class _Script:
    """HTTP calls in one script and what triggers each."""

    def __init__(self, rel: str, code: str, grammar: str, first_line: int = 1, consts: dict | None = None,
                 instances: dict | None = None, numbers: dict | None = None):
        self.rel, self.first_line = rel, first_line
        self.src = code.encode("utf-8", "replace")
        self.tree = _PARSERS[grammar].parse(self.src)
        self.consts: dict[str, str] = dict(consts or {})          # imported URL constants included
        self.numbers: dict[str, str] = dict(numbers or {})
        self.instances: dict[str, str] = dict(instances or {})    # HTTP client -> its base URL
        self.functions: dict[str, list] = {}            # name -> function nodes
        self.triggers: dict[tuple, list] = {}           # function node span -> [(label, event, via)]
        self.calls: list[Call] = []
        self.callers: dict[str, list] = {}               # function name -> nodes of the functions calling it
        self.aliases: dict[str, str] = {}
        self.imports: dict[str, tuple] = {}             # local name -> (module as written, imported name)
        self.exports: dict[str, str] = {}               # exported name ("default" too) -> local name
        self.call_nodes: list = []
        self.setters: dict[str, str] = {}               # React: setX -> x
        self.effects: list = []                         # React: (effect function, [dependency names])
        self.jsx_handlers: list = []                    # (label, event, handler node, attribute)
        self.feeds: list = []                           # (call node, state set from its result, argument text)
        self.tables: list = []                          # JSX grids
        self.control_lines: dict[tuple, int] = {}       # (label, event) -> the line of the control itself
        self._walk()

    def line(self, node) -> int:
        return node.start_point[0] + self.first_line

    @staticmethod
    def _key(node) -> tuple:
        return (node.start_byte, node.end_byte)

    def _fn_value(self, node):
        if node is None:
            return None
        if node.type in ("function_expression", "arrow_function", "function", "function_declaration",
                         "method_definition", "generator_function"):
            return node
        if node.type == "identifier":
            nodes = self.functions.get(_text(node, self.src))
            return nodes[0] if nodes else ("name", _text(node, self.src))
        if node.type == "member_expression":          # this.save / self.save
            prop = node.child_by_field_name("property")
            nodes = self.functions.get(_text(prop, self.src)) if prop is not None else None
            return nodes[0] if nodes else None
        return None

    def _trigger(self, fn, label: str, event: str, via: str, at=None):
        if at is not None:
            self.control_lines.setdefault((label, event), self.line(at))
        if fn is None:
            return
        if isinstance(fn, tuple):                     # a function declared later: resolved in a second pass
            self._pending.append((fn[1], label, event, via))
            return
        self.triggers.setdefault(self._key(fn), []).append((label, event, via))

    def _walk(self):
        src = self.src
        self._pending: list = []
        nodes = []
        stack = [self.tree.root_node]
        while stack:
            node = stack.pop()
            nodes.append(node)
            stack.extend(reversed(node.children))
        for node in nodes:                             # declarations first
            if node.type == "import_statement":
                self._import(node)
            elif node.type == "export_statement":
                self._export(node)
            if node.type == "function_declaration":
                self.functions.setdefault(_text(node.child_by_field_name("name"), src), []).append(node)
            elif node.type == "variable_declarator":
                name, value = node.child_by_field_name("name"), node.child_by_field_name("value")
                if name is None or value is None:
                    continue
                if value.type == "await_expression":
                    value = next((c for c in value.children if c.is_named), value)
                if value.type == "call_expression":
                    callee = _text(value.child_by_field_name("function"), src)
                    args = [c for c in value.child_by_field_name("arguments").children if c.is_named] \
                        if value.child_by_field_name("arguments") is not None else []
                    if callee == "require" and args and args[0].type == "string":
                        module = _text(args[0], src)[1:-1]
                        if name.type == "identifier":
                            self.imports[_text(name, src)] = (module, "default")
                        elif name.type == "object_pattern":
                            for prop in re.findall(r"[A-Za-z_$][\w$]*", _text(name, src)):
                                self.imports[prop] = (module, prop)
                        continue
                    if callee.endswith(".create") and args and args[0].type == "object":
                        base = _object_pairs(args[0], src).get("baseURL") or _object_pairs(args[0], src).get("baseUrl")
                        if base is not None:                  # axios.create({ baseURL: '/api' })
                            v = _str_value(base, src, self.consts)
                            if v is not None:
                                self.instances[_text(name, src)] = v
                        else:
                            self.instances.setdefault(_text(name, src), "")
                        continue
                    if callee in ("useState", "React.useState") and name.type == "array_pattern":
                        parts = [c for c in name.children if c.is_named]
                        if len(parts) == 2:
                            self.setters[_text(parts[1], src)] = _text(parts[0], src)
                        continue
                if value.type == "number":
                    self.numbers[_text(name, src)] = _text(value, src)
                    continue
                if value.type in ("arrow_function", "function_expression", "function"):
                    self.functions.setdefault(_text(name, src), []).append(value)
                elif value.type in ("string", "template_string", "binary_expression"):
                    v = _str_value(value, src, self.consts)
                    if v is not None:
                        self.consts[_text(name, src)] = v
                else:
                    sel = _selector_of(value, src, self.aliases)
                    if sel:
                        self.aliases[_text(name, src)] = sel
            elif node.type == "pair":
                value = node.child_by_field_name("value")
                if value is not None and value.type in ("arrow_function", "function_expression", "function"):
                    self.functions.setdefault(_text(node.child_by_field_name("key"), src).strip("'\""), []).append(value)
            elif node.type == "method_definition":
                self.functions.setdefault(_text(node.child_by_field_name("name"), src), []).append(node)
            elif node.type == "assignment_expression":       # App.search = function () { … }
                left, value = node.child_by_field_name("left"), node.child_by_field_name("right")
                if left is not None and value is not None and value.type in (
                        "arrow_function", "function_expression", "function"):
                    prop = left.child_by_field_name("property") if left.type == "member_expression" else left
                    if prop is not None:
                        self.functions.setdefault(_text(prop, src), []).append(value)
        for node in nodes:
            if node.type == "call_expression":
                self.call_nodes.append(node)
                self._call(node)
            elif node.type == "jsx_element" and self._tag(node) == "table":
                self._table(node)
            elif node.type == "assignment_expression":
                self._assignment(node)
            elif node.type == "jsx_attribute":
                self._jsx(node)
            elif node.type == "pair" and _text(node.child_by_field_name("key"), src).strip("'\"") == "events":
                self._backbone_events(node.child_by_field_name("value"))
            elif node.type == "method_definition" and _text(node.child_by_field_name("name"), src) in _LOAD_HOOKS:
                self._trigger(node, "page", "page load", f"{_text(node.child_by_field_name('name'), src)}()")
            elif node.type == "pair" and _text(node.child_by_field_name("key"), src).strip("'\"") in _LOAD_HOOKS:
                self._trigger(self._fn_value(node.child_by_field_name("value")), "page", "page load",
                              _text(node.child_by_field_name("key"), src) + "()")
        for name, label, event, via in self._pending:
            for fn in self.functions.get(name, []):
                self.triggers.setdefault(self._key(fn), []).append((label, event, via))
        self._effects_from_state()
        # Who calls each named function (one hop is enough to reach a bound handler).
        for node in nodes:
            if node.type == "call_expression":
                f = node.child_by_field_name("function")
                name = _text(f.child_by_field_name("property"), src) if f is not None and f.type == "member_expression" \
                    and f.child_by_field_name("property") is not None else _text(f, src) if f is not None else ""
                if name in self.functions:
                    encl = self.enclosing(node)
                    if encl:
                        self.callers.setdefault(name, []).append(encl[0])

    # ── modules ──
    def _import(self, node):
        src = self.src
        source = node.child_by_field_name("source")
        if source is None:
            return
        module = _text(source, src)[1:-1]
        clause = next((c for c in node.children if c.type == "import_clause"), None)
        for c in (clause.children if clause is not None else []):
            if c.type == "identifier":
                self.imports[_text(c, src)] = (module, "default")
            elif c.type == "namespace_import":
                ident = next((g for g in c.children if g.type == "identifier"), None)
                if ident is not None:
                    self.imports[_text(ident, src)] = (module, "*")
            elif c.type == "named_imports":
                for spec in c.children:
                    if spec.type == "import_specifier":
                        name, alias = spec.child_by_field_name("name"), spec.child_by_field_name("alias")
                        self.imports[_text(alias or name, src)] = (module, _text(name, src))

    def _export(self, node):
        src = self.src
        decl, value = node.child_by_field_name("declaration"), node.child_by_field_name("value")
        default = any(c.type == "default" for c in node.children)
        if decl is not None:
            names = []
            if decl.type in ("function_declaration", "class_declaration", "generator_function_declaration"):
                n = decl.child_by_field_name("name")
                names = [_text(n, src)] if n is not None else []
            else:
                names = [_text(d.child_by_field_name("name"), src) for d in decl.children
                         if d.type == "variable_declarator" and d.child_by_field_name("name") is not None]
            for n in names:
                self.exports["default" if default else n] = n
        elif value is not None and value.type == "identifier":
            self.exports["default"] = _text(value, src)
        for c in node.children:
            if c.type == "export_clause":
                for spec in c.children:
                    if spec.type == "export_specifier":
                        name, alias = spec.child_by_field_name("name"), spec.child_by_field_name("alias")
                        self.exports[_text(alias or name, src)] = _text(name, src)

    # ── JSX ──
    def _tag(self, element) -> str:
        opening = element.children[0] if element.children else None
        if opening is None or opening.type not in ("jsx_opening_element", "jsx_self_closing_element"):
            opening = element if element.type == "jsx_self_closing_element" else None
        name = opening.child_by_field_name("name") if opening is not None else None
        return _text(name, self.src) if name is not None else ""

    def _jsx_label(self, opening) -> str:
        """A control's label: its text, else id / name / placeholder / aria-label, else its <label>'s text."""
        src = self.src
        name = opening.child_by_field_name("name")
        tag = _text(name, src) if name is not None else "element"
        attrs = {}
        for a in opening.children:
            if a.type == "jsx_attribute" and a.children:
                value = a.children[-1] if len(a.children) > 1 else None
                if value is None or value.type == "string":       # a bound value ({search}) names no control
                    attrs[_text(a.children[0], src)] = _text(value, src).strip("'\"") if value is not None else ""
        element = opening.parent if opening.type == "jsx_opening_element" else None
        text = ""
        if element is not None:
            text = " ".join(_text(c, src).strip() for c in element.children
                            if c.type in ("jsx_text", "jsx_expression") and _text(c, src).strip())
        if not text:
            for key in ("aria-label", "placeholder", "title", "value"):
                if attrs.get(key) and not attrs[key].startswith(("(", "e =>")) and "=>" not in attrs[key]:
                    text = attrs[key]
                    break
        if not text:
            p = opening.parent
            for _ in range(3):
                if p is None:
                    break
                if p.type == "jsx_element" and self._tag(p) == "label":
                    text = " ".join(_text(c, src).strip() for c in p.children if c.type == "jsx_text").strip()
                    break
                p = p.parent
        kind = f"{tag}[{attrs['type']}]" if attrs.get("type") and tag == "input" else tag
        ident = f"#{attrs['id']}" if attrs.get("id") else ""
        return " ".join(x for x in (kind, ident, f"\"{_short(text)}\"" if text else "") if x)

    def _table(self, element):
        """A JSX grid: its header cells and, for `rows.map((row) => <tr>…)`, the value each cell shows."""
        src = self.src
        headers = [_short(" ".join(_text(c, src).strip() for c in th.children if c.type == "jsx_text"), 30)
                   for th in self._descendants(element, "jsx_element") if self._tag(th) == "th"]
        mapping = next((n for n in self._descendants(element, "call_expression")
                        if _text(n.child_by_field_name("function"), src).endswith(".map")), None)
        if mapping is None:
            return
        source = _text(mapping.child_by_field_name("function").child_by_field_name("object"), src)
        args = [c for c in mapping.child_by_field_name("arguments").children if c.is_named]
        if not args or args[0].type not in ("arrow_function", "function_expression"):
            return
        params = args[0].child_by_field_name("parameters") or args[0].child_by_field_name("parameter")
        row = re.findall(r"[A-Za-z_$][\w$]*", _text(params, src))[:1] if params is not None else []
        cells = []
        for td in self._descendants(args[0], "jsx_element"):
            if self._tag(td) != "td":
                continue
            fields = []
            for m in re.finditer(rf"\b{re.escape(row[0])}((?:\.[A-Za-z_$][\w$]*)+)", _text(td, src)) if row else []:
                parts = m.group(1).strip(".").split(".")
                field = ".".join(p for p in parts if p not in ("length", "join", "map", "toString"))
                if field and field not in fields:
                    fields.append(field)
            cells.append(fields)
        ident = ""
        opening = element.children[0]
        for a in opening.children:
            if a.type == "jsx_attribute" and _text(a.children[0], src) == "id" and len(a.children) > 1:
                ident = _text(a.children[-1], src).strip("'\"")
        self.tables.append({"node": element, "id": ident, "source": source, "headers": headers, "cells": cells})

    @staticmethod
    def _descendants(node, kind: str) -> list:
        out, stack = [], list(reversed(node.children))
        while stack:
            n = stack.pop()
            if n.type == kind:
                out.append(n)
            stack.extend(reversed(n.children))
        return out

    def _effects_from_state(self):
        """A control that sets state an effect depends on (`onClick={() => setPage(page + 1)}` with
        `useEffect(load, [page])`) triggers that effect's calls."""
        src = self.src
        for label, event, handler, attr in self.jsx_handlers:
            text = _text(handler, src)
            if handler.type == "identifier" and self.functions.get(text):
                text = _text(self.functions[text][0], src)
            for called in set(re.findall(r"([A-Za-z_$][\w$]*)\s*\(", text)):     # one hop: local helpers
                if called in self.functions and called not in self.setters:
                    text += "\n" + _text(self.functions[called][0], src)
            states = {self.setters[s] for s in re.findall(r"\b(set[A-Z]\w*)\s*\(", text) if s in self.setters}
            for effect, deps in self.effects:
                for state in sorted(states & set(deps)):
                    self.triggers.setdefault(self._key(effect), []).append(
                        (label, event, f"JSX {attr} sets `{state}`, which re-runs the effect"))

    def enclosing(self, node) -> list:
        out = []
        p = node.parent
        while p is not None:
            if p.type in ("function_expression", "arrow_function", "function", "function_declaration",
                          "method_definition", "generator_function"):
                out.append(p)
            p = p.parent
        return out

    def name_of(self, fn) -> str:
        if fn.type in ("function_declaration", "method_definition"):
            n = fn.child_by_field_name("name")
            return _text(n, self.src) if n is not None else ""
        p = fn.parent
        if p is not None and p.type == "variable_declarator":
            return _text(p.child_by_field_name("name"), self.src)
        if p is not None and p.type == "pair":
            return _text(p.child_by_field_name("key"), self.src).strip("'\"")
        return ""

    def _assignment(self, node):
        src = self.src
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        lt = _text(left, src)
        if re.search(r"(?:^|\.)location(?:\.href)?$", lt):
            v = _str_value(right, src, self.consts)
            if v is not None:
                self.calls.append(Call(self.line(node), "GET", normalize(v), [], node, kind="navigation"))
        elif lt.endswith(".defaults.baseURL"):                 # axios.defaults.baseURL = '/api'
            v = _str_value(right, src, self.consts)
            if v is not None:
                self.instances[lt[:-len(".defaults.baseURL")]] = v
        elif lt in ("window.onload", "document.onload"):
            self._trigger(self._fn_value(right), "page", "page load", "window.onload")
        elif left.type == "member_expression":
            prop = _text(left.child_by_field_name("property"), src)
            if prop.startswith("on") and prop[2:] in _JQ_EVENTS:
                sel = _selector_of(left.child_by_field_name("object"), src, self.aliases)
                if sel:
                    self._trigger(self._fn_value(right), sel, prop[2:], f"{prop} handler")

    def _jsx(self, node):
        src = self.src
        name = _text(node.children[0], src) if node.children else ""
        if not re.match(r"on[A-Z]\w+$", name):
            return
        value = next((c for c in node.children if c.type == "jsx_expression"), None)
        inner = next((c for c in value.children if c.is_named), None) if value is not None else None
        el = node.parent
        label = self._jsx_label(el) if el is not None and el.type in ("jsx_opening_element",
                                                                       "jsx_self_closing_element") else "element"
        event = name[2:].lower()
        fn = self._fn_value(inner)
        self._trigger(fn, label, event, f"JSX {name}", at=node)
        if inner is not None:
            self.jsx_handlers.append((label, event, inner, name))

    def _backbone_events(self, obj):
        for key, value in _object_pairs(obj, self.src).items():
            parts = key.split(None, 1)
            event, sel = parts[0], (parts[1] if len(parts) > 1 else "view")
            if value.type == "string":
                self._pending.append((_text(value, self.src)[1:-1], sel, event, "Backbone events map"))
            else:
                self._trigger(self._fn_value(value), sel, event, "Backbone events map")

    def _call(self, node):
        src = self.src
        f = node.child_by_field_name("function")
        if f is not None and f.type == "await_expression":
            f = next((c for c in f.children if c.is_named), f)
        argn = node.child_by_field_name("arguments")
        if f is None or argn is None:
            return
        args = [c for c in argn.children if c.is_named]
        fn = _text(f, src)
        prop = _text(f.child_by_field_name("property"), src) if f.type == "member_expression" else ""
        obj = f.child_by_field_name("object") if f.type == "member_expression" else None
        ctype = ""
        ta = node.child_by_field_name("type_arguments")
        if ta is not None:
            ctype = _text(ta, src).strip("<>")

        # Event bindings.
        if prop in ("on", "bind", "live", "delegate") and obj is not None and args:
            sel = _selector_of(obj, src, self.aliases)
            evt = _text(args[0], src).strip("'\"`")
            target = sel
            if len(args) >= 3 and args[1].type == "string":
                target = _text(args[1], src).strip("'\"`")
            if target and target != "document" or (sel == "document" and len(args) >= 3):
                self._trigger(self._fn_value(args[-1]), target, evt.split(".")[0], f"jQuery .{prop}('{evt}')",
                              at=node)
            return
        if prop in _JQ_EVENTS and obj is not None and args:
            sel = _selector_of(obj, src, self.aliases)
            if sel == "document" and prop == "ready" or sel and sel != "document":
                self._trigger(self._fn_value(args[-1]), sel, prop, f"jQuery .{prop}()")
            return
        if prop == "ready" and obj is not None and args:
            self._trigger(self._fn_value(args[0]), "page", "page load", "jQuery ready")
            return
        if fn in ("$", "jQuery") and args and args[0].type in ("function_expression", "arrow_function"):
            self._trigger(args[0], "page", "page load", "jQuery ready")
            return
        if prop == "addEventListener" and obj is not None and len(args) >= 2:
            evt = _text(args[0], src).strip("'\"`")
            sel = _selector_of(obj, src, self.aliases)
            if evt in ("DOMContentLoaded", "load") and sel in ("document", ""):
                self._trigger(self._fn_value(args[1]), "page", "page load", evt)
            elif sel:
                self._trigger(self._fn_value(args[1]), sel, evt, "addEventListener", at=node)
            return
        if fn in ("useEffect", "React.useEffect", "useLayoutEffect", "onMounted") and args:
            effect = self._fn_value(args[0])
            self._trigger(effect, "page", "page load", fn)
            if len(args) > 1 and args[1].type == "array" and effect is not None and not isinstance(effect, tuple):
                self.effects.append((effect, re.findall(r"[A-Za-z_$][\w$]*", _text(args[1], src))))
            return
        if fn in ("setInterval", "window.setInterval") and args:
            ms = _text(args[1], src) if len(args) > 1 else ""
            ms = self.numbers.get(ms, ms)
            self._trigger(self._fn_value(args[0]), "timer", f"every {ms} ms" if ms.isdigit() else "on a timer",
                          f"setInterval({_text(args[0], src)}, {_text(args[1], src) if len(args) > 1 else ''})",
                          at=node)
            return
        if prop == "then" and obj is not None and args:
            # `load().then((res) => setRows(res.data))`: which state the call's result fills.
            callback = args[0]
            for setter, value in re.findall(r"\b(set[A-Z]\w*)\s*\(\s*([^)]*)\)", _text(callback, src)):
                if setter in self.setters:
                    target = obj
                    while target is not None and target.type == "call_expression" and _text(
                            target.child_by_field_name("function"), src).endswith(".then"):
                        target = target.child_by_field_name("function").child_by_field_name("object")
                    self.feeds.append((target, self.setters[setter], value.strip()))

        # HTTP calls.
        base = self._base_for(obj, fn)

        def add(verb, url_node, sends=None, element="", kind="script", param_arg=None):
            if url_node is None:
                return
            v = _str_value(url_node, src, self.consts)
            if v is None:
                return
            if not (v.startswith(("/", "http", "{}", ".")) or "/" in v or base):
                return                                   # not a URL: map.get('x'), cache.get(key)
            if base and not re.match(r"^(?:https?:)?//", v):
                v = base.rstrip("/") + "/" + v.lstrip("/")     # the client's baseURL
            self.calls.append(Call(self.line(node), verb, normalize(v), sends or [], node, element, kind, ctype,
                                   param_arg))

        if fn == "fetch" and args:
            verb, sends = "GET", []
            if len(args) > 1:
                opts = _object_pairs(args[1], src)
                if "method" in opts:
                    verb = _text(opts["method"], src).strip("'\"`").upper()
                sends = _sent_names(opts.get("body"), src, self.consts)
                if not sends and "body" in opts:
                    sends = _form_data_names(self.enclosing(node)[0] if self.enclosing(node) else None, src)
            add(verb, args[0], sends)
            return
        if prop.lower() in ("get", "post", "put", "delete", "patch", "head") and obj is not None and args and (
                re.search(r"(?i)axios|http|api|client|\$resource|request|\$$|^jquery$", _text(obj, src))
                or _text(obj, src) in self.instances):
            verb = prop.upper()
            if _text(obj, src) in ("$", "jQuery"):
                verb = "GET" if prop == "get" else "POST"
            sends = _sent_names(args[1], src, self.consts) if len(args) > 1 and verb in ("POST", "PUT", "PATCH") or \
                (len(args) > 1 and _text(obj, src) in ("$", "jQuery")) else []
            param_arg = None
            if len(args) > 1 and verb == "GET" and args[1].type == "object":
                params = _object_pairs(args[1], src).get("params")
                sends = _sent_names(params, src, self.consts) if params is not None else sends
                if params is not None and params.type in ("identifier", "shorthand_property_identifier"):
                    param_arg = self._param_index(node, _text(params, src))
            elif len(args) > 1 and args[1].type == "identifier":
                param_arg = self._param_index(node, _text(args[1], src))
            add(verb, args[0], sends, param_arg=param_arg)
            return
        if fn in ("$.getJSON", "jQuery.getJSON") and args:
            add("GET", args[0], _sent_names(args[1], src, self.consts) if len(args) > 1 else [])
            return
        if fn in ("$.ajax", "jQuery.ajax", "axios") and args:
            first = args[0]
            opts = _object_pairs(first if first.type == "object" else (args[1] if len(args) > 1 else None), src)
            url_node = opts.get("url") if first.type == "object" else first
            verb = _text(opts["type"] if "type" in opts else opts["method"], src).strip("'\"`").upper() \
                if ("type" in opts or "method" in opts) else "GET"
            add(verb, url_node, _sent_names(opts.get("data"), src, self.consts) or
                _sent_names(opts.get("params"), src, self.consts))
            return
        if prop == "load" and obj is not None and args and args[0].type in ("string", "template_string",
                                                                              "binary_expression"):
            add("GET", args[0], [], _selector_of(obj, src, self.aliases), "panel")
            return
        if prop in ("DataTable", "dataTable", "jqGrid", "bootstrapTable", "kendoGrid") and obj is not None and args:
            opts = _object_pairs(args[0], src)
            ajax = opts.get("ajax") or opts.get("url") or opts.get("sAjaxSource")
            verb = "GET"
            if ajax is not None and ajax.type == "object":
                inner = _object_pairs(ajax, src)
                if "type" in inner or "method" in inner:
                    verb = _text(inner.get("type") or inner.get("method"), src).strip("'\"`").upper()
                ajax = inner.get("url")
            if "mtype" in opts:
                verb = _text(opts["mtype"], src).strip("'\"`").upper()
            add(verb, ajax, [], _selector_of(obj, src, self.aliases) or "grid", "grid")
            return
        if prop == "open" and len(args) >= 2 and args[0].type == "string" and \
                _text(args[0], src).strip("'\"").upper() in _VERBS:
            add(_text(args[0], src).strip("'\"").upper(), args[1])
            return
        if prop == "extend" and obj is not None and re.search(r"Backbone\.(?:Model|Collection)$", _text(obj, src)) \
                and args:
            opts = _object_pairs(args[0], src)
            model = _text(obj, src).rsplit(".", 1)[-1]
            parent = node.parent
            name = _text(parent.child_by_field_name("name"), src) if parent is not None and \
                parent.type == "variable_declarator" else Path(self.rel).stem
            if "urlRoot" in opts:
                base = _str_value(opts["urlRoot"], src, self.consts) or ""
                for verb, path in (("GET", base + "/{}"), ("POST", base), ("PUT", base + "/{}"),
                                   ("DELETE", base + "/{}")):
                    self.calls.append(Call(self.line(node), verb, normalize(path), [], node,
                                           f"Backbone {model} {name}", "data model"))
            elif "url" in opts and opts["url"].type in ("string", "template_string", "binary_expression"):
                self.calls.append(Call(self.line(node), "GET", normalize(_str_value(opts["url"], src, self.consts)),
                                       [], node, f"Backbone {model} {name}", "data model"))

    def _base_for(self, obj, fn: str) -> str:
        """The base URL of the HTTP client a call goes through (`api` from `axios.create({ baseURL })`)."""
        name = _text(obj, self.src) if obj is not None else fn
        return self.instances.get(name, "") or (self.instances.get("axios", "") if name == "axios" else "")

    def _param_index(self, node, name: str) -> int | None:
        """The position of `name` among the enclosing function's parameters."""
        fn = next(iter(self.enclosing(node)), None)
        if fn is None:
            return None
        params = fn.child_by_field_name("parameters") or fn.child_by_field_name("parameter")
        names = [_text(p, self.src) for p in (params.children if params is not None else []) if p.is_named] \
            if params is not None and params.type != "identifier" else ([_text(params, self.src)] if params is not None
                                                                        else [])
        return names.index(name) if name in names else None

    def triggers_of(self, call: Call, inline: dict[str, list]) -> list[tuple[str, str, str]]:
        return self.triggers_for(call.node, inline)

    def triggers_for(self, node, inline: dict[str, list]) -> list[tuple[str, str, str]]:
        """[(element, event, via)] for a call: the innermost bound function, its callers, inline handlers."""
        found: list = []
        seen = set()

        def visit(fn, depth):
            if fn is None or self._key(fn) in seen or depth > 3:
                return
            seen.add(self._key(fn))
            found.extend(self.triggers.get(self._key(fn), []))
            name = self.name_of(fn)
            if name:
                for label, event, via in inline.get(name, []):
                    found.append((label, event, via))
                for caller in self.callers.get(name, []):
                    visit(caller, depth + 1)

        enclosing = self.enclosing(node)
        for fn in enclosing:
            visit(fn, 0)
            if found:
                break
        if not enclosing:
            found.append(("page", "page load", "script runs when loaded"))
        return found


# ── backend contracts ───────────────────────────────────────────────────────

_DECLARATION_PATH = {"class_declaration", "record_declaration", "enum_declaration", "interface_declaration",
                     "class_body", "interface_body", "enum_body", "enum_body_declarations"}


class _Java:
    """The repository's classes, their fields with annotations, and exception handlers."""

    def __init__(self, workspace_dir: str):
        self.root = Path(workspace_dir)
        self.classes: dict[str, dict] = {}
        self.handlers: dict[str, list[str]] = {}       # exception class -> ["400 (Advice.method)"]
        self.exception_status: dict[str, str] = {}
        if "java" not in _PARSERS:
            return
        for path in sorted(self.root.rglob("*.java")):
            rel = path.relative_to(self.root).as_posix()
            if EXCLUDED_DIRS & set(Path(rel).parts) or _TEST_PATH.search(rel):
                continue
            try:
                src = path.read_bytes()
            except OSError:
                continue
            if len(src) > MAX_FILE_BYTES:
                continue
            self._index(rel, src)

    def _index(self, rel: str, src: bytes):
        tree = _PARSERS["java"].parse(src)
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            # Declarations only: method bodies are never searched for classes.
            stack.extend(c for c in reversed(node.children) if c.type in _DECLARATION_PATH)
            if node.type not in ("class_declaration", "record_declaration", "enum_declaration",
                                 "interface_declaration"):
                continue
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = _text(name_node, src)
            ann = _annotations(node, src)
            info = {"path": rel, "fields": [], "constants": [], "super": "", "kind": node.type}
            sup = node.child_by_field_name("superclass")
            if sup is not None:
                info["super"] = _base(_text(sup, src).replace("extends", "").strip())
            if "ResponseStatus" in ann:
                m = re.search(r"HttpStatus\.(\w+)", ann["ResponseStatus"])
                if m:
                    self.exception_status[name] = _status(m.group(1))
            if node.type == "record_declaration":
                params = node.child_by_field_name("parameters")
                for p in (params.children if params else []):
                    if p.type == "formal_parameter":
                        info["fields"].append(self._field(p, src, _text(p.child_by_field_name("name"), src)))
            body = node.child_by_field_name("body")
            for member in (body.children if body else []):
                if member.type == "enum_constant":
                    info["constants"].append(_text(member.child_by_field_name("name"), src))
                elif member.type == "enum_body":
                    pass
                elif member.type == "field_declaration":
                    mods = next((_text(c, src) for c in member.children if c.type == "modifiers"), "")
                    if re.search(r"\bstatic\b", mods):
                        continue
                    for d in member.children:
                        if d.type == "variable_declarator":
                            info["fields"].append(self._field(member, src, _text(d.child_by_field_name("name"), src)))
                elif member.type == "method_declaration":
                    mann = _annotations(member, src)
                    if "ExceptionHandler" in mann:
                        excs = re.findall(r"(\w+)\.class", mann["ExceptionHandler"])
                        if not excs:
                            params = member.child_by_field_name("parameters")
                            excs = [_base(_text(p.child_by_field_name("type"), src)) for p in
                                    (params.children if params else []) if p.type == "formal_parameter"
                                    and re.search(r"Exception|Error|Throwable", _text(p, src))]
                        status = _statuses(_text(member, src), mann)
                        where = f"{name}.{_text(member.child_by_field_name('name'), src)}"
                        for e in excs:
                            self.handlers.setdefault(e, []).append(
                                f"{', '.join(status) or 'status not set in the code'} ({where})")
            if node.type == "enum_declaration" and body is not None:
                info["constants"] = [_text(c.child_by_field_name("name"), src) for c in body.children
                                     if c.type == "enum_constant"]
            self.classes.setdefault(name, info)

    @staticmethod
    def _field(decl, src: bytes, name: str) -> dict:
        ann = _annotations(decl, src)
        ftype = _text(decl.child_by_field_name("type"), src)
        json_name = _first_string(ann["JsonProperty"]) if "JsonProperty" in ann else ""
        constraints = []
        for a, args in ann.items():
            if a in VALIDATION_ANNOTATIONS and a not in ("Valid",):
                if a == "Column":
                    bits = [b for b in (f"nullable={_attr(args, 'nullable')}" if _attr(args, "nullable") else "",
                                        f"length={_attr(args, 'length')}" if _attr(args, "length") else "") if b]
                    if bits:
                        constraints.append(f"@Column({', '.join(bits)})")
                    continue
                constraints.append(f"@{a}{_compact(args)}")
        if "JsonFormat" in ann and _attr(ann["JsonFormat"], "pattern"):
            constraints.append(f"format {_attr(ann['JsonFormat'], 'pattern')}")
        return {"name": name, "json": json_name, "type": ftype, "constraints": constraints,
                "ignored": "JsonIgnore" in ann}

    def fields(self, name: str, depth: int = 0) -> list[dict]:
        info = self.classes.get(name)
        if not info or depth > 5:
            return []
        inherited = self.fields(info["super"], depth + 1) if info["super"] else []
        return inherited + info["fields"]

    def exception_statuses(self, exc: str) -> str:
        found = list(self.handlers.get(exc, []))
        if exc in self.exception_status:
            found.append(f"{self.exception_status[exc]} (@ResponseStatus on {exc})")
        sup = self.classes.get(exc, {}).get("super", "")
        if not found and sup and sup != exc:
            return self.exception_statuses(sup)
        return "; ".join(found)


def _compact(args: str) -> str:
    args = re.sub(r"\s+", " ", args or "").strip()
    args = re.sub(r",?\s*message\s*=\s*\"[^\"]*\"", "", args)
    return "" if args in ("", "()") else args


def _status(name: str) -> str:
    code = _STATUS.get(name)
    return f"{code} {name}" if code else name


def _statuses(body: str, ann: dict) -> list[str]:
    found = []
    if "ResponseStatus" in ann:
        code = re.search(r"HttpStatus\.(\w+)", ann["ResponseStatus"])
        if code:
            found.append(_status(code.group(1)))
    for m in re.finditer(r"(?:HttpStatus|Response\.Status|Status)\.([A-Z_]+)\b", body):
        found.append(_status(m.group(1)))
    for m in re.finditer(r"ResponseEntity\s*\.\s*(\w+)\s*\(", body):
        if m.group(1) in _ENTITY_CALLS:
            found.append(_status(next(k for k, v in _STATUS.items() if v == _ENTITY_CALLS[m.group(1)])))
    for m in re.finditer(r"Response\s*\.\s*(ok|noContent|created|accepted)\s*\(", body):
        found.append(_status({"ok": "OK", "noContent": "NO_CONTENT", "created": "CREATED",
                              "accepted": "ACCEPTED"}[m.group(1)]))
    for m in re.finditer(r"\.status\(\s*(\d{3})\s*\)|setStatus\(\s*(\d{3})\s*\)|sendError\(\s*(\d{3})", body):
        found.append(next(g for g in m.groups() if g))
    return list(dict.fromkeys(found))


def _type_label(type_text: str, java: _Java) -> str:
    type_text = re.sub(r"^new\s+", "", (type_text or "").strip())
    base = _base(type_text)
    args = _args(type_text)
    if base in _SCALARS:
        return _SCALARS[base]
    if base in _WRAPPERS and args:
        return _type_label(args[0], java)
    if base in _COLLECTIONS:
        return f"list of {_type_label(args[0], java)}" if args else "list"
    if base in _PAGED or base == "PageImpl":
        return f"page of {_type_label(args[0], java)}" if args else "page"
    if base in _MAPS:
        k, v = (args + ["Object", "Object"])[:2]
        return f"map of {_type_label(k, java)} → {_type_label(v, java)}"
    if base.endswith("[]"):
        return f"array of {_type_label(base[:-2], java)}"
    info = java.classes.get(base)
    if info and info["constants"]:
        return "enum: " + " | ".join(info["constants"][:12]) + (" …" if len(info["constants"]) > 12 else "")
    if info:
        return f"object ({base})"
    return f"{base} (not in the repository)"


def schema(type_text: str, java: _Java, prefix: str = "", depth: int = 0, seen: tuple = (),
           json_names: bool = True) -> list[tuple[str, str, str]]:
    """[(field path, type, constraints)] for a type, flattened: `items[].sku`."""
    type_text = re.sub(r"^new\s+", "", (type_text or "").strip())
    base = _base(type_text)
    args = _args(type_text)
    if base in _WRAPPERS:
        return schema(args[0], java, prefix, depth, seen, json_names) if args else \
            [(prefix or "(body)", "not declared in the signature", "")]
    if base in _PAGED or base == "PageImpl":
        inner = args[0] if args else "Object"
        rows = schema(inner, java, f"{prefix}.content[]" if prefix else "content[]", depth, seen, json_names)
        return rows + [(f"{prefix}.{name}" if prefix else name, kind, "Spring Data page")
                       for name, kind in _PAGED.get(base, _PAGED["Page"]) + _PAGE_FIELDS]
    if base in _COLLECTIONS:
        inner = args[0] if args else "Object"
        return schema(inner, java, (prefix or "") + "[]", depth, seen, json_names)
    if base.endswith("[]") and base not in _SCALARS:
        return schema(base[:-2], java, (prefix or "") + "[]", depth, seen, json_names)
    if base in _MAPS:
        k, v = (args + ["Object", "Object"])[:2]
        return [(prefix or "(body)", f"map of {_type_label(k, java)} → {_type_label(v, java)}", "")]
    info = java.classes.get(base)
    if base in _SCALARS or not info or info["constants"] or info["kind"] == "interface_declaration":
        return [(prefix or "(body)", _type_label(type_text, java), "")]
    if base in seen or depth >= MAX_DEPTH:
        return [(prefix or "(body)", f"object ({base}) — {'recursive' if base in seen else 'nested further'}", "")]
    rows = []
    for f in java.fields(base):
        if f["ignored"]:
            continue
        name = (f["json"] or f["name"]) if json_names else f["name"]
        path = f"{prefix}.{name}" if prefix else name
        sub = schema(f["type"], java, path, depth + 1, seen + (base,), json_names)
        if len(sub) == 1 and sub[0][0] == path:
            rows.append((path, sub[0][1], ", ".join(f["constraints"])))
        else:
            if f["constraints"]:
                rows.append((path, f"object ({_base(f['type'])})", ", ".join(f["constraints"])))
            rows += sub
    return rows or [(prefix or "(body)", f"object ({base}) with no fields", "")]


def _method_node(workspace_dir: str, source: str):
    rel, _, line = source.rpartition(":")
    path = Path(workspace_dir) / rel
    if "java" not in _PARSERS or not path.is_file() or not line.isdigit():
        return None, None, None
    src = path.read_bytes()
    tree = _PARSERS["java"].parse(src)
    target = int(line) - 1
    stack = [(tree.root_node, None)]
    while stack:
        node, cls = stack.pop()
        if node.type == "class_declaration":
            cls = node
        if node.type == "method_declaration" and node.start_point[0] <= target <= node.end_point[0]:
            return node, cls, src
        stack.extend((c, cls) for c in reversed(node.children))
    return None, None, None


def _empty_contract(endpoint: dict) -> dict:
    return {"endpoint": f"{endpoint['verb']} {endpoint['path']}", "handler": endpoint["handler"],
            "source": endpoint["source"], "kind": endpoint["kind"], "params": [], "body": [], "body_type": "",
            "body_in": "", "response": [], "response_type": "", "view": endpoint.get("view", ""), "model": [],
            "model_fields": [], "redirects": [], "statuses": [], "errors": [], "access": "", "consumes": "",
            "produces": "", "validation": []}


def contract(workspace_dir: str, endpoint: dict, java: _Java) -> dict:
    """The request and response contract of one handler, from its signature and body."""
    method, cls, src = _method_node(workspace_dir, endpoint["source"])
    out = _empty_contract(endpoint)
    if method is None:
        return out
    ann = _annotations(method, src)
    cls_ann = _annotations(cls, src) if cls is not None else {}
    mapping = next((ann[a] for a in ann if a.endswith("Mapping")), "")
    out["consumes"] = _attr(mapping, "consumes") or _first_string(ann.get("Consumes", ""))
    out["produces"] = _attr(mapping, "produces") or _first_string(ann.get("Produces", ""))
    for a in ("PreAuthorize", "Secured", "RolesAllowed"):
        rule = ann.get(a) or cls_ann.get(a)
        if rule:
            out["access"] = f"@{a}" + re.sub(r"\s+", " ", rule) + ("" if a in ann else " (on the class)")
            break
    verb = endpoint["verb"]
    params = method.child_by_field_name("parameters")
    for p in (params.children if params else []):
        if p.type not in ("formal_parameter", "spread_parameter"):
            continue
        pann = _annotations(p, src)
        ptype = _text(p.child_by_field_name("type"), src) if p.child_by_field_name("type") else ""
        pname_node = p.child_by_field_name("name")
        pname = _text(pname_node, src) if pname_node is not None else ""
        checks = [f"@{a}{_compact(v)}" for a, v in pann.items() if a in VALIDATION_ANNOTATIONS and a != "Valid"]
        if "DateTimeFormat" in pann:                     # how a date parameter must be written
            fmt = pann["DateTimeFormat"]
            pattern = _attr(fmt, "pattern")
            iso = re.search(r"ISO\.(DATE_TIME|DATE|TIME)", fmt)
            checks.append(f"format {pattern}" if pattern else
                          {"DATE": "format yyyy-MM-dd", "DATE_TIME": "format ISO date-time",
                           "TIME": "format HH:mm:ss"}.get(iso.group(1), "") if iso else "")
            checks = [c for c in checks if c]
        optional = _base(ptype) == "Optional"
        inner_type = _args(ptype)[0] if optional and _args(ptype) else ptype

        def param(where, name, args):
            required = not optional and _attr(args, "required") != "false" and not _attr(args, "defaultValue")
            out["params"].append({"name": name or pname, "in": where, "type": _type_label(inner_type, java),
                                  "required": "yes" if required else "no",
                                  "default": _attr(args, "defaultValue"), "constraints": ", ".join(checks)})

        if "PathVariable" in pann or "PathParam" in pann:
            param("path", _first_string(pann.get("PathVariable") or pann.get("PathParam", "")), "")
        elif "RequestParam" in pann:
            where = "query" if verb in ("GET", "DELETE") else "query or form"
            if _base(inner_type) in ("MultipartFile", "Part") or "List<MultipartFile>" in inner_type:
                where = "multipart"
            if _base(inner_type) in _MAPS:
                out["params"].append({"name": "(any)", "in": where, "type": "all request parameters as a map",
                                      "required": "no", "default": "", "constraints": ""})
            else:
                param(where, _first_string(pann["RequestParam"]), pann["RequestParam"])
        elif "QueryParam" in pann:
            param("query", _first_string(pann["QueryParam"]), pann.get("DefaultValue", ""))
        elif "FormParam" in pann:
            param("form", _first_string(pann["FormParam"]), "")
        elif "RequestHeader" in pann or "HeaderParam" in pann:
            param("header", _first_string(pann.get("RequestHeader") or pann.get("HeaderParam", "")),
                  pann.get("RequestHeader", ""))
        elif "CookieValue" in pann or "CookieParam" in pann:
            param("cookie", _first_string(pann.get("CookieValue") or pann.get("CookieParam", "")), "")
        elif "RequestPart" in pann:
            param("multipart", _first_string(pann["RequestPart"]), pann["RequestPart"])
        elif "RequestBody" in pann or (not pann.keys() - {"Valid", "Validated"} and endpoint["kind"] == "REST"
                                       and _base(ptype) in java.classes and verb in ("POST", "PUT", "PATCH")
                                       and not _FRAMEWORK.match(_base(ptype))):
            out["body_type"] = ptype
            out["body_in"] = "JSON body" if "RequestBody" in pann or "Consumes" not in ann else "body"
            out["body"] = schema(ptype, java)
            if "Valid" in pann or "Validated" in pann:
                out["validation"].append(f"the body is validated (@{'Valid' if 'Valid' in pann else 'Validated'})"
                                         " before the handler runs")
        elif "ModelAttribute" in pann or (not pann.keys() - {"Valid", "Validated"} and _base(ptype) in java.classes
                                          and not java.classes[_base(ptype)]["constants"]
                                          and not _FRAMEWORK.match(_base(ptype))):
            out["body_type"] = ptype
            out["body_in"] = "form fields" if verb != "GET" else "query parameters"
            out["body"] = schema(ptype, java, json_names=False)
            if "Valid" in pann or "Validated" in pann:
                out["validation"].append(f"the form object is validated (@{'Valid' if 'Valid' in pann else 'Validated'})")
        elif _base(ptype) in ("MultipartFile",):
            param("multipart", pname, "")
        elif _base(ptype) in ("BindingResult", "Errors"):
            out["validation"].append("validation errors are handed to the handler (BindingResult), not thrown")
    body_text = _text(method, src)
    for m in re.finditer(r"\.getParameter(?:Values)?\(\s*\"([^\"]+)\"\s*\)", body_text):
        if not any(p["name"] == m.group(1) for p in out["params"]):
            out["params"].append({"name": m.group(1), "in": "query or form", "type": "string",
                                  "required": "not enforced", "default": "", "constraints": "read with getParameter"})
    rtype = _text(method.child_by_field_name("type"), src) if method.child_by_field_name("type") else ""
    if endpoint["kind"] == "REST":
        out["response_type"] = rtype
        if _base(rtype) in ("void", "Void"):
            out["response"] = [("(body)", "empty", "")]
        elif _base(rtype) == "Response":                   # JAX-RS: the entity is built in the body
            ents = re.findall(r"\.entity\(\s*(\w+)", body_text)
            out["response"] = [("(body)", "built in the method (javax.ws.rs Response)" +
                                (f"; entity from `{ents[0]}`" if ents else ""), "")]
        else:
            out["response"] = schema(rtype, java)
    else:
        literals = [next(g for g in m.groups() if g) for m in re.finditer(
            r"return\s+\"([^\"]+)\"\s*;|new\s+ModelAndView\(\s*\"([^\"]+)\"|setViewName\(\s*\"([^\"]+)\"\s*\)",
            body_text)]
        out["redirects"] = sorted({v for v in literals if v.startswith(("redirect:", "forward:"))})
        views = sorted({v for v in literals if not v.startswith(("redirect:", "forward:"))})
        if views:
            out["view"] = ", ".join(views)
        try:
            from .ui_mock_data import controller_model
            model = controller_model(workspace_dir, endpoint["source"], java.mock_classes())
        except Exception:                                 # noqa: BLE001 — the contract is still useful without it
            model = {}
        out["model"] = [(k, _type_label(v, java) if v else "type not resolved", v) for k, v in sorted(model.items())]
        out["model_fields"] = [row for k, v in sorted(model.items()) if v and _base(re.sub(r"^new\s+", "", v))
                               not in _SCALARS for row in schema(v, java, k)
                               if row[0] != k]
    out["statuses"] = _statuses(body_text, ann)
    for exc in dict.fromkeys(re.findall(r"throw\s+new\s+(\w+)\s*\(", body_text)):
        out["errors"].append((exc, java.exception_statuses(exc) or "no handler found in the code"))
    throws = method.child_by_field_name("throws") or next((c for c in method.children if c.type == "throws"), None)
    if throws is not None:
        for exc in re.findall(r"\b([A-Z]\w*(?:Exception|Error))\b", _text(throws, src)):
            if not any(e == exc for e, _ in out["errors"]):
                status = java.exception_statuses(exc)
                if status:
                    out["errors"].append((exc, status))
    return out


def _safe_contract(workspace_dir: str, endpoint: dict, java: _Java) -> dict:
    """The contract, or the endpoint alone with a note when its code could not be read."""
    try:
        return contract(workspace_dir, endpoint, java)
    except Exception as exc:                                   # noqa: BLE001 — never fails the scan
        out = _empty_contract(endpoint)
        out["validation"].append(f"the handler's code could not be read ({type(exc).__name__})")
        return out


def _mock_classes(self):
    if not hasattr(self, "_mock"):
        from .ui_mock_data import index_classes
        self._mock = index_classes(str(self.root))
    return self._mock


_Java.mock_classes = _mock_classes


# ── the scan ────────────────────────────────────────────────────────────────

def _ui_files(root: Path) -> tuple[list[Path], list[Path]]:
    templates, scripts = [], []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _skip(rel):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        suffix = path.suffix.lower()
        if suffix in _TEMPLATE_SUFFIXES and "/src/test/" not in "/" + rel:
            templates.append(path)
        elif suffix in _SCRIPT_SUFFIXES or suffix == ".vue":
            if suffix in (".ts", ".tsx") and path.name.endswith(".d.ts"):
                continue
            scripts.append(path)
    return templates, scripts


def _view_files(endpoints: list[dict], template_rels: list[str]) -> dict[str, list[dict]]:
    """template file → the page endpoints whose view it is."""
    out: dict[str, list[dict]] = {}
    stems = {rel: re.sub(r"\.\w+$", "", rel) for rel in template_rels}
    for e in endpoints:
        for view in (e.get("view") or "").split(","):
            view = view.strip().strip("/")
            if not view or view.startswith(("redirect:", "forward:")):
                continue
            for rel, stem in stems.items():
                if stem == view or stem.endswith("/" + view):
                    out.setdefault(rel, []).append(e)
    return out


def _script_matches(ref: str, script_rels: list[str]) -> list[str]:
    url = normalize(ref)
    path = url.path.strip("/")
    if not path:
        return []
    hits = [rel for rel in script_rels if rel == path or rel.endswith("/" + path)]
    if not hits:                                       # js/main (RequireJS data-main) or a different static root
        name = path.rsplit("/", 1)[-1]
        hits = [rel for rel in script_rels if rel.rsplit("/", 1)[-1] == name]
    return hits


def _framework_paths(root: Path) -> dict[str, str]:
    """Paths the server framework handles, not application code: the servlet container's
    form login and the Spring Security login / logout the configuration switches on."""
    paths = {"/j_security_check": "the servlet container's form login (j_security_check) — no application handler"}
    for path in sorted(root.rglob("*.java")):
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(Path(rel).parts) or _TEST_PATH.search(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "formLogin" in text or "loginProcessingUrl" in text:
            login = re.search(r"loginProcessingUrl\(\s*\"([^\"]+)\"", text)
            paths[login.group(1) if login else "/login"] = \
                f"Spring Security form login, configured in `{rel}` — no application handler"
        if re.search(r"\.logout\(", text):
            logout = re.search(r"logoutUrl\(\s*\"([^\"]+)\"", text)
            paths[logout.group(1) if logout else "/logout"] = \
                f"Spring Security logout, configured in `{rel}` — no application handler"
    return paths


def scan(workspace_dir: str, inventory: dict) -> dict:
    """Every UI control that reaches the backend, with the contract of what it calls."""
    root = Path(workspace_dir)
    result = {"screens": [], "contracts": [], "unmatched": [], "uncalled": [], "pages": []}
    endpoints = inventory.get("endpoints", [])
    templates, scripts_paths = _ui_files(root) if root.is_dir() else ([], [])
    template_rels = [p.relative_to(root).as_posix() for p in templates]
    script_rels = [p.relative_to(root).as_posix() for p in scripts_paths]
    served_by = _view_files(endpoints, template_rels)

    readers: dict[str, _TemplateReader] = {}
    for path, rel in zip(templates, template_rels):
        reader = _TemplateReader(rel)
        try:
            reader.feed(path.read_text(encoding="utf-8", errors="replace"))
            reader.close()
        except Exception:                                     # noqa: BLE001 — malformed markup: use what was read
            pass
        readers[rel] = reader

    # Which pages include each script, and the inline handlers that name functions.
    included_by: dict[str, list[str]] = {}
    for rel, reader in readers.items():
        for ref in reader.scripts:
            for s in _script_matches(ref, script_rels):
                included_by.setdefault(s, []).append(rel)
        stem = re.sub(r"\.(?:component\.)?html?$", "", rel)
        for s in script_rels:                                  # x.component.html ↔ x.component.ts
            if re.sub(r"\.(?:component\.)?[jt]sx?$", "", s) == stem and s not in included_by.get(s, []):
                included_by.setdefault(s, []).append(rel)

    def inline_handlers(pages: list[str]) -> dict[str, list]:
        out: dict[str, list] = {}
        for page in pages:
            for fn, event, label, line, _ in readers[page].handlers:
                out.setdefault(fn, []).append((label, event, f"inline {event} handler in {page}:{line} → {fn}()"))
        return out

    elements: list[Element] = []
    for rel in template_rels:
        elements += readers[rel].elements

    site_calls: dict[tuple, Call] = {}        # (file, call node span) -> the HTTP call it ends in

    def remote_sites(sc: _Script, node, depth: int = 0) -> list[tuple]:
        """Where an exported function enclosing `node` is called from other modules, with the
        triggers found there: [(script, call-site node, [(label, event, via)])]."""
        if depth > 3:
            return []
        name = next((sc.name_of(f) for f in sc.enclosing(node) if sc.name_of(f)), "")
        exported = {e for e, local in sc.exports.items() if local == name} if name else set()
        if not exported:
            return []
        found = []
        for other in scripts.values():
            if other is sc:
                continue
            for local, (module, imported) in other.imports.items():
                if resolve(other.rel, module) != sc.rel:
                    continue
                if imported in exported:
                    names = {local}
                elif imported == "*":
                    names = {f"{local}.{e}" for e in exported}
                else:
                    continue
                for site in other.call_nodes:
                    if _text(site.child_by_field_name("function"), other.src) not in names:
                        continue
                    trig = other.triggers_for(site, inline_handlers(included_by.get(other.rel, [])))
                    if trig:
                        found.append((other, site, [(l, e, f"{v} → {name}() in {Path(sc.rel).name}")
                                                    for l, e, v in trig]))
                    else:
                        found += [(o, n, [(l, e, f"{v} → {name}() in {Path(sc.rel).name}") for l, e, v in t])
                                  for o, n, t in remote_sites(other, site, depth + 1)]
        return found

    def add_elements(rel: str, call: Call, triggers: list, line: int, sends: list, holder: "_Script | None" = None):
        for label, event, via in triggers[:6]:
            at = holder.control_lines.get((label, event), line) if holder is not None else line
            kind = call.kind if call.kind != "script" else (
                "button" if event in ("click", "dblclick") else "form" if event == "submit" else
                "input" if event in ("change", "keyup", "keydown", "keypress", "input", "blur") else
                "timer" if event.startswith(("every", "on a timer")) else "script")
            if kind == "navigation":
                kind = "link" if event == "click" else "script"
            if kind == "button" and re.match(r"^a\b", label):
                kind = "link"
            if label == "page":
                kind, label = "page load", Path(rel).name
            elif label == "timer":
                label = f"timer in {Path(rel).name}"
            elements.append(Element(rel, at, kind, label or f"code in {Path(rel).name}",
                                    event or "—", call.verb, call.url, list(sends), via=via,
                                    client_type=call.client_type))

    def script_elements(rel: str, sc: _Script, pages: list[str]):
        inline = inline_handlers(pages)
        for call in sc.calls:
            site_calls[(rel, call.node.start_byte, call.node.end_byte)] = call
            triggers = [(call.element, "page load" if call.kind == "grid" else "", call.kind)] if call.element else []
            if call.kind in ("grid", "panel") or not call.element:
                bound = sc.triggers_of(call, inline)
                if call.kind in ("grid", "panel") and bound:
                    triggers = [(call.element or b[0], b[1] if b[1] != "page load" or call.kind != "grid"
                                 else "page load", b[2]) for b in bound[:1]]
                elif not call.element:
                    triggers = bound
            if not triggers:
                # A service function (`export const fetchJobs = …`): the controls are where it is called.
                sites = remote_sites(sc, call.node)
                for other, site, trig in sites:
                    site_calls[(other.rel, site.start_byte, site.end_byte)] = call
                    sends = list(call.sends)
                    args = [c for c in site.child_by_field_name("arguments").children if c.is_named]
                    if not sends and call.param_arg is not None and call.param_arg < len(args):
                        sends = _sent_names(args[call.param_arg], other.src, other.consts)
                    add_elements(other.rel, call, trig, other.line(site), sends, other)
                if sites:
                    continue
                fn = next((sc.name_of(f) for f in sc.enclosing(call.node) if sc.name_of(f)), "")
                triggers = [("", "", f"called from {fn}()" if fn else "trigger not found in the code")]
            add_elements(rel, call, triggers, call.line, call.sends, sc)

    # Scripts: read once for their imports, exports, constants and HTTP clients, then again
    # with what they import resolved — a URL constant or an axios instance from another module.
    sources: list[tuple] = []
    for path, rel in zip(scripts_paths, script_rels):
        try:
            code = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        grammar = _SCRIPT_SUFFIXES.get(path.suffix.lower())
        first = 1
        if path.suffix.lower() == ".vue":
            m = re.search(r"<script[^>]*>(.*?)</script>", code, re.S)
            if not m:
                continue
            lang = re.search(r"<script[^>]*\blang=['\"](ts|tsx)['\"]", code)
            grammar = "typescript" if lang else "javascript"
            first = code[:m.start(1)].count("\n") + 1
            tpl = re.search(r"<template[^>]*>(.*)</template>", code, re.S)
            if tpl:
                reader = _TemplateReader(rel)
                try:
                    reader.feed(tpl.group(1))
                except Exception:                             # noqa: BLE001
                    pass
                readers[rel] = reader
                for el in reader.elements:
                    el.line += code[:tpl.start(1)].count("\n")
                elements += reader.elements
                included_by.setdefault(rel, []).append(rel)
            code = m.group(1)
        if grammar == "javascript" and path.suffix.lower() == ".jsx" or (
                grammar == "javascript" and re.search(r"<[A-Z]\w*[\s/>]|return\s*\(\s*<", code)):
            grammar = "tsx" if "tsx" in _PARSERS else grammar
        if grammar in _PARSERS:
            sources.append((rel, code, grammar, first))

    def resolve(importer: str, module: str) -> str | None:
        """The script a module specifier names: './x' relative to the importer, '@/x' from its src/."""
        if module.startswith("."):
            base = Path(importer).parent / module
        elif module.startswith(("@/", "~/")):
            parts = Path(importer).parts
            if "src" not in parts:
                return None
            base = Path(*parts[:len(parts) - list(reversed(parts)).index("src")]) / module[2:]
        else:
            return None
        norm = Path(re.sub(r"/\./", "/", base.as_posix()))
        stack = []
        for part in norm.parts:
            if part == "..":
                if stack:
                    stack.pop()
            elif part != ".":
                stack.append(part)
        target = "/".join(stack)
        for candidate in [target] + [target + ext for ext in _SCRIPT_SUFFIXES] + \
                [f"{target}/index{ext}" for ext in _SCRIPT_SUFFIXES]:
            if candidate in known:
                return candidate
        return None

    known = {rel for rel, *_ in sources}
    first_pass: dict[str, _Script] = {}
    for rel, code, grammar, first in sources:
        try:
            first_pass[rel] = _Script(rel, code, grammar, first)
        except Exception:                                      # noqa: BLE001
            continue
    shared_axios = next((sc.instances["axios"] for sc in first_pass.values() if sc.instances.get("axios")), "")
    scripts: dict[str, _Script] = {}
    for rel, code, grammar, first in sources:
        pre = first_pass.get(rel)
        if pre is None:
            continue
        consts, numbers, instances = {}, {}, ({"axios": shared_axios} if shared_axios else {})
        for local, (module, imported) in pre.imports.items():
            target = first_pass.get(resolve(rel, module) or "")
            if target is None:
                continue
            name = target.exports.get(imported, imported)
            if name in target.consts:
                consts[local] = target.consts[name]
            if name in target.numbers:
                numbers[local] = target.numbers[name]
            if name in target.instances:
                instances[local] = target.instances[name]
        try:
            scripts[rel] = _Script(rel, code, grammar, first, consts, instances, numbers) \
                if (consts or numbers or instances) else pre
        except Exception:                                      # noqa: BLE001
            scripts[rel] = pre
    for rel, sc in scripts.items():
        try:                                                   # one unreadable script never stops the scan
            if sc.calls:
                script_elements(rel, sc, included_by.get(rel, []))
        except Exception:                                      # noqa: BLE001
            continue

    # React grids: a table rendered from state that a call's result filled shows that call's response.
    for rel, sc in scripts.items():
        for table in sc.tables:
            state_root = table["source"].split(".")[0]
            for target, state, value in sc.feeds:
                call = site_calls.get((rel, target.start_byte, target.end_byte))
                if call is None or state != state_root:
                    continue
                parts = value.split(".")[1:] if "." in value else []
                if parts[:1] == ["data"]:
                    parts = parts[1:]                          # an axios response's body
                path = ".".join(parts + table["source"].split(".")[1:])
                prefix = f"{path}[]" if path else "[]"
                columns = [(header, ", ".join(f"{prefix}.{f}" for f in cells) if cells else "")
                           for header, cells in zip(table["headers"] + [""] * len(table["cells"]), table["cells"])]
                elements.append(Element(rel, sc.line(table["node"]), "grid",
                                        f"table #{table['id']}" if table["id"] else "table",
                                        "shows the response", call.verb, call.url, [],
                                        data=table["source"], columns=columns,
                                        via=f"rows from `{table['source']}`, set from the response of the call at "
                                            f"line {sc.line(target)}"))

    for rel, reader in readers.items():
        for line, code in reader.inline:
            if "javascript" not in _PARSERS:
                break
            try:
                sc = _Script(rel, code, "javascript", line)
                if sc.calls:
                    script_elements(rel, sc, [rel])
            except Exception:                                  # noqa: BLE001
                continue

    # Match every call to its handler.
    java: _Java | None = None
    framework: dict | None = None
    contracts: dict[str, dict] = {}
    by_key = {f"{e['verb']} {e['path']} {e['handler']}": e for e in endpoints}
    for el in elements:
        if el.url is None:
            continue
        found, reason = match(el.url, el.verb or "GET", endpoints)
        el.endpoints = [f"{e['verb']} {e['path']} {e['handler']}" for e in found]
        el.reason = reason
        if not found:
            framework = _framework_paths(root) if framework is None else framework
            el.reason = framework.get(el.url.path, reason)
        for e in found:
            key = f"{e['verb']} {e['path']} {e['handler']}"
            if key not in contracts:
                java = java or _Java(workspace_dir)
                contracts[key] = _safe_contract(workspace_dir, e, java)
    # Every endpoint gets its contract, whether or not a UI control calls it.
    for e in endpoints:
        key = f"{e['verb']} {e['path']} {e['handler']}"
        if key not in contracts:
            java = java or _Java(workspace_dir)
            contracts[key] = _safe_contract(workspace_dir, e, java)

    elements = [el for el in elements if el.url is not None or el.data or el.columns]
    elements.sort(key=lambda el: (el.file, el.line, el.kind, el.label))
    dedup, seen = [], set()
    for el in elements:
        key = (el.file, el.line, el.kind, el.label, el.event, el.verb, el.url.path if el.url else "")
        if key not in seen:
            seen.add(key)
            dedup.append(el)
    for i, el in enumerate(dedup, 1):
        el.id = f"UI-{i:03d}"

    screens: dict[str, dict] = {}
    for el in dedup:
        pages = included_by.get(el.file, []) if Path(el.file).suffix.lower() in _SCRIPT_SUFFIXES else []
        screen = screens.setdefault(el.file, {
            "file": el.file,
            "served_by": [f"{e['verb']} {e['path']} ({e['handler']})" for e in served_by.get(el.file, [])],
            "used_by": sorted(set(p for p in pages if p != el.file)),
            "elements": []})
        screen["elements"].append(_element_json(el))
        if el.url is not None and not el.endpoints:
            result["unmatched"].append({"id": el.id, "element": el.label, "call": f"{el.verb} {el.url.raw}",
                                        "reason": el.reason, "source": f"{el.file}:{el.line}"})
    result["screens"] = [screens[k] for k in sorted(screens)]
    order = {f"{e['verb']} {e['path']} {e['handler']}": i for i, e in enumerate(endpoints)}
    for el in dedup:
        for k in el.endpoints:
            contracts[k].setdefault("called_by", []).append(el.id)
    result["contracts"] = [contracts[k] for k in sorted(contracts, key=lambda k: (order.get(k, len(order)), k))]
    counts: dict[str, int] = {}
    for el in dedup:
        counts[el.file] = counts.get(el.file, 0) + 1
    result["pages"] = [{"file": rel, "served_by": [f"{e['verb']} {e['path']} ({e['handler']})"
                                                    for e in served_by.get(rel, [])],
                        "elements": counts.get(rel, 0)} for rel in template_rels]
    called = {k for el in dedup for k in el.endpoints} | {f"{e['verb']} {e['path']} {e['handler']}"
                                                          for eps in served_by.values() for e in eps}
    result["uncalled"] = [f"{e['verb']} {e['path']} ({e['handler']})" for k, e in by_key.items()
                          if e["kind"] == "REST" and k not in called]
    return result


def _element_json(el: Element) -> dict:
    return {"id": el.id, "kind": el.kind, "label": el.label, "event": el.event, "verb": el.verb,
            "url": el.url.raw if el.url else "", "path": el.url.path if el.url else "",
            "query": el.url.query if el.url else [], "sends": el.sends, "data": el.data,
            "columns": el.columns, "fields": el.fields, "via": el.via, "client_type": el.client_type,
            "endpoints": el.endpoints, "reason": el.reason, "source": f"{el.file}:{el.line}"}


# ── markdown ────────────────────────────────────────────────────────────────

def _handler_cell(e: dict) -> str:
    if e["endpoints"]:
        return "; ".join(f"`{k.rsplit(' ', 1)[-1]}` (`{' '.join(k.split(' ')[:2])}`)" for k in e["endpoints"])
    if e["url"]:
        return f"none found — {e['reason']}"
    return "the page's own handler (server-rendered)"


def to_markdown(result: dict, covered: dict[str, str] | None = None) -> str:
    """`covered`: {template file: page} described element by element in the UI Pages section — their form
    fields and grid columns are referred to there, not printed twice."""
    screens = result.get("screens") or []
    if not screens and not result.get("pages"):
        return ""
    count = sum(len(s["elements"]) for s in screens)
    lines = [HEADING, "",
             "_Read from the templates, scripts and controller code by the pipeline — not generated by an agent. "
             "Each UI control that reaches the server is tied to the handler that serves it; the handler's request "
             "and response contract is read from its signature and body. `{}` marks a part of a URL built at run "
             "time. A call that could not be tied to a handler is listed at the end with the reason._", "",
             f"**{count} UI element(s) on {len(screens)} screen(s); every handler's contract is under Endpoint "
             f"Contracts.**", ""]
    for screen in screens:
        page = (covered or {}).get(screen["file"])
        lines += screen_markdown(screen, details=page is None)
        if page is not None and any(e["fields"] or e["columns"] for e in screen["elements"]):
            lines += [f"Form fields and grid columns of this screen: UI Pages and Interactive Components → page "
                      f"`{page}`.", ""]
    if result.get("pages"):
        lines += [f"### Web pages and templates ({len(result['pages'])})", "",
                  "| Template | Rendered by | UI elements |", "|---|---|---|"]
        lines += [f"| `{_cell(p['file'])}` | "
                  + ("; ".join(f"`{_cell(x)}`" for x in p["served_by"]) or "no handler names it as its view")
                  + f" | {p['elements']} |" for p in result["pages"]]
        lines.append("")
    if result.get("unmatched"):
        lines += ["### Calls not tied to a handler", "",
                  "| Id | UI element | Call as written | Reason | Source |", "|---|---|---|---|---|"]
        lines += [f"| {u['id']} | {_cell(u['element'])} | `{_cell(u['call'])}` | {_cell(u['reason'])} | "
                  f"`{u['source']}` |" for u in result["unmatched"]]
        lines.append("")
    if result.get("uncalled"):
        lines += ["### REST endpoints no UI code calls", "",
                  "_Called by other clients, or by UI code whose URL the scan could not resolve._", ""]
        lines += [f"- `{_cell(u)}`" for u in result["uncalled"]]
        lines.append("")
    return "\n".join(lines).rstrip()


def screen_markdown(screen: dict, details: bool = True) -> list[str]:
    """One screen: its controls, form fields and grid columns."""
    lines: list[str] = []
    lines.append(f"### Screen `{screen['file']}`")
    lines.append("")
    if screen["served_by"]:
        lines.append("Rendered by: " + "; ".join(f"`{x}`" for x in screen["served_by"]))
    if screen["used_by"]:
        lines.append("Script loaded by: " + ", ".join(f"`{x}`" for x in screen["used_by"]))
    if screen["served_by"] or screen["used_by"]:
        lines.append("")
    lines += ["| Id | UI element | Event | Calls | Sends | Backend handler | Source |",
              "|---|---|---|---|---|---|---|"]
    for e in screen["elements"]:
        call = f"{e['verb']} `{_cell(e['path'] or e['url'])}`" if e["url"] else (
            f"— shows `{_cell(e['data'])}`" if e["data"] else "—")
        sends = ", ".join(f"`{_cell(x)}`" for x in dict.fromkeys(e["sends"] + [f"{q} (query)" for q in e["query"]]))
        label = _cell(e["label"]) + (f" ({e['kind']})" if e["kind"] not in e["label"] else "")
        via = f" — _{_cell(e['via'])}_" if e["via"] else ""
        lines.append(f"| {e['id']} | {label} | {_cell(e['event'])}{via} | {call} | {sends or '—'} | "
                     f"{_cell(_handler_cell(e))} | `{e['source']}` |")
    lines.append("")
    for e in screen["elements"]:
        if not details:
            break
        if e["fields"]:
            lines += [f"**{e['id']} form fields** (as the UI sends them)", "",
                      "| Field | Input | Client-side checks |", "|---|---|---|"]
            lines += [f"| `{_cell(n)}` | {_cell(t)} | {_cell(c) or '—'} |" for n, t, c in e["fields"]]
            lines.append("")
        if e["columns"]:
            lines += [f"**{e['id']} grid columns** (from `{_cell(e['data'])}`)", "",
                      "| Column | Value shown |", "|---|---|"]
            lines += [f"| {_cell(h) or '—'} | `{_cell(v)}` |" if v else f"| {_cell(h) or '—'} | — |"
                      for h, v in e["columns"]]
            lines.append("")
        if e["client_type"]:
            lines += [f"**{e['id']}** declares the response as `{_cell(e['client_type'])}` on the client.", ""]
    return lines


def _rows(rows: list) -> list[str]:
    return [f"| `{_cell(p)}` | {_cell(t)} | {_cell(c) or '—'} |" for p, t, c in rows] + [""]


def contract_markdown(c: dict) -> list[str]:
    """One endpoint's contract: request parameters, body schema, response schema, statuses, errors."""
    lines: list[str] = []
    lines += [f"### `{c['endpoint']}` — `{c['handler']}`", "",
              f"Source `{c['source']}` · {'REST (JSON)' if c['kind'] == 'REST' else 'page'}"
              + (f" · consumes `{c['consumes']}`" if c["consumes"] else "")
              + (f" · produces `{c['produces']}`" if c["produces"] else "")
              + (f" · access {c['access']}" if c["access"] else ""), ""]
    if c.get("called_by"):
        lines += ["Called from the UI by: " + ", ".join(dict.fromkeys(c["called_by"])) + ".", ""]
    if not (c["params"] or c["body"]):
        lines += ["**Request** — no parameters or body.", ""]
    if c["params"]:
        lines += ["**Request parameters**", "", "| Name | In | Type | Required | Default | Constraints |",
                  "|---|---|---|---|---|---|"]
        lines += [f"| `{_cell(p['name'])}` | {p['in']} | {_cell(p['type'])} | {p['required']} | "
                  f"{_cell(p['default']) or '—'} | {_cell(p['constraints']) or '—'} |" for p in c["params"]]
        lines.append("")
    if c["body"]:
        lines += [f"**Request {c['body_in']}** — `{_cell(_base(c['body_type']))}`", "",
                  "| Field | Type | Constraints |", "|---|---|---|"]
        lines += _rows(c["body"])
    if c["validation"]:
        lines += ["Validation: " + "; ".join(c["validation"]) + ".", ""]
    if c["kind"] == "REST":
        lines += [f"**Response** — `{_cell(c['response_type'] or 'not declared')}`", "",
                  "| Field | Type | Constraints |", "|---|---|---|"]
        lines += _rows(c["response"])
    else:
        lines.append(f"**Response** — view `{_cell(c['view'] or 'not a literal in the code')}`"
                     + (f"; redirects: {', '.join(f'`{r}`' for r in c['redirects'])}" if c["redirects"] else ""))
        lines.append("")
        if c["model"]:
            lines += ["| Model attribute | Type |", "|---|---|"]
            lines += [f"| `{_cell(k)}` | {_cell(t)} |" for k, t, _ in c["model"]]
            lines.append("")
        if c.get("model_fields"):
            lines += ["**Model fields** (what the page can show)", "", "| Field | Type | Constraints |",
                      "|---|---|---|"]
            lines += _rows(c["model_fields"])
    if c["statuses"]:
        lines += ["HTTP statuses set in the code: " + ", ".join(f"`{s}`" for s in c["statuses"]) + ".", ""]
    if c["errors"]:
        lines += ["| Exception thrown | Becomes |", "|---|---|"]
        lines += [f"| `{e}` | {_cell(s)} |" for e, s in c["errors"]]
        lines.append("")
    return lines


def contracts_markdown(result: dict) -> str:
    """Every HTTP endpoint's contract, in the order of the Interface & Job Inventory."""
    contracts = result.get("contracts") or []
    if not contracts:
        return ""
    lines = [CONTRACTS_HEADING, "",
             "_Read from each handler's signature and body by the pipeline — not generated by an agent. Every "
             "endpoint of the Interface & Job Inventory is here: request parameters, the request body or form "
             "object and the response, each broken down to every field with its type and constraints, the HTTP "
             "statuses the code sets, the exceptions it throws with the status they become, and the access rule._",
             "", f"**{len(contracts)} endpoint(s).**", ""]
    for c in contracts:
        lines += contract_markdown(c)
    return "\n".join(lines).rstrip()


def batches(result: dict, max_elements: int, max_chars: int) -> list[list[dict]]:
    """The screens in order, cut into batches a writer can describe in full: at most
    `max_elements` controls and about `max_chars` of input each. A screen with more
    controls than a batch holds is split into parts."""
    parts: list[dict] = []
    for screen in result.get("screens", []):
        els = screen["elements"]
        chunks = [els[i:i + max(max_elements, 1)] for i in range(0, len(els), max(max_elements, 1))] or [[]]
        for n, chunk in enumerate(chunks, 1):
            parts.append(dict(screen, elements=chunk, part=f"part {n} of {len(chunks)}" if len(chunks) > 1 else ""))
    out: list[list[dict]] = []
    size = count = 0
    for part in parts:
        length = len("\n".join(screen_markdown(part)))
        if out and (count + len(part["elements"]) > max_elements or size + length > max_chars):
            out.append([])
            size = count = 0
        if not out:
            out.append([])
        out[-1].append(part)
        size += length
        count += len(part["elements"])
    return out


def batch_request(batch: list[dict], result: dict) -> str:
    """A writer's input for one batch: its screens, the contracts of the handlers they
    call and the calls among them that were not tied to a handler."""
    ids = {e["id"] for screen in batch for e in screen["elements"]}
    keys = {k for screen in batch for e in screen["elements"] for k in e["endpoints"]}
    lines = ["## Screens of this batch", ""]
    for screen in batch:
        screen_lines = screen_markdown(screen)
        if screen.get("part"):
            screen_lines[0] += f" ({screen['part']})"
        lines += screen_lines
    called = [c for c in result.get("contracts", [])
              if f"{c['endpoint']} {c['handler']}" in keys]
    lines += ["## Contracts of the handlers these controls call", ""]
    for c in called:
        lines += contract_markdown(c)
    if not called:
        lines += ["None of these controls calls a handler found in the code.", ""]
    unmatched = [u for u in result.get("unmatched", []) if u["id"] in ids]
    if unmatched:
        lines += ["## Calls not tied to a handler", "", "| Id | Call as written | Reason |", "|---|---|---|"]
        lines += [f"| {u['id']} | `{_cell(u['call'])}` | {_cell(u['reason'])} |" for u in unmatched]
    return "\n".join(lines).rstrip()


def batch_ids(batch: list[dict]) -> list[str]:
    return [e["id"] for screen in batch for e in screen["elements"]]


def batch_names(batch: list[dict]) -> set[str]:
    """Words that find a batch's evidence: its files' names and its handlers' classes and methods."""
    names = set()
    for screen in batch:
        names.add(Path(screen["file"]).name)
        for e in screen["elements"]:
            for k in e["endpoints"]:
                names.update(k.rsplit(" ", 1)[-1].split("."))
    return {n for n in names if len(n) > 3}


def fallback(element: dict) -> str:
    """A computed line for an element the writer did not describe — so none is missing."""
    call = f"{element['verb']} `{element['path'] or element['url']}`" if element["url"] else (
        f"shows `{element['data']}` rendered by the page's handler" if element["data"] else "no call")
    handler = "; ".join(f"`{k.rsplit(' ', 1)[-1]}` (`{' '.join(k.split(' ')[:2])}`)" for k in element["endpoints"]) \
        or (f"no handler — {element['reason']}" if element["url"] else "")
    sends = ", ".join(f"`{x}`" for x in element["sends"])
    return (f"- **{element['id']}** — {element['label']} ({element['kind']}), on {element['event']}: {call}"
            + (f", sending {sends}" if sends else "") + (f" → {handler}" if handler else "")
            + ". _Computed from the code; the writer did not describe this control — its contract is under "
              "Endpoint Contracts._")


_SCHEMA_FIRST = {"field", "parameter", "name", "request parameter", "response field", "attribute", "property"}


def _schema_header(line: str) -> bool:
    """`| Field | Type | … |`: a table of fields with their types (a contract's schema)."""
    if not line.startswith("|"):
        return False
    cells = [c.strip().lower() for c in line.strip().strip("|").split("|")]
    return bool(cells) and cells[0] in _SCHEMA_FIRST and any(c in ("type", "data type") for c in cells[1:])


def strip_schema_tables(markdown: str) -> tuple[str, int]:
    """The section without field / type tables: every endpoint's fields are printed once, under Endpoint
    Contracts. Returns the text and how many tables were taken out."""
    out, removed, skipping = [], 0, False
    for line in markdown.split("\n"):
        if skipping:
            if line.lstrip().startswith("|"):
                continue
            skipping = False
        if _schema_header(line.strip()):
            skipping, removed = True, removed + 1
            while out and not out[-1].strip():
                out.pop()
            out.append("")
            out.append("Fields: see Endpoint Contracts.")
            continue
        out.append(line)
    return "\n".join(out), removed


SECTION_HEADING = "## UI Interaction Contracts"
_BLOCK_START = re.compile(r"^\s*[-*+]\s+(?:\*\*)?(UI-\d{3,})\b")
_SCREEN_HEADING = re.compile(r"^#{2,4}\s+(.*)$")


def parse_answer(text: str, result: dict) -> tuple[dict[str, str], dict[str, str]]:
    """A writer's answer → ({screen file: its introduction}, {element id: its bullet block}).
    The first block for an id wins; text under a heading before the first bullet is
    that screen's introduction (the heading names the screen's file)."""
    files = [screen["file"] for screen in result.get("screens", [])]
    intros: dict[str, str] = {}
    blocks: dict[str, str] = {}
    current_file, current_id, buf = "", "", []

    def flush():
        body = "\n".join(buf).strip()
        if current_id and body and current_id not in blocks:
            blocks[current_id] = body
        elif not current_id and current_file and body and current_file not in intros:
            intros[current_file] = body

    for line in (text or "").splitlines():
        heading = _SCREEN_HEADING.match(line)
        start = _BLOCK_START.match(line)
        if heading:
            flush()
            title = heading.group(1)
            current_file = next((f for f in files if f in title), "") or next(
                (f for f in files if Path(f).name in title), "")
            current_id, buf = "", []
        elif start:
            flush()
            current_id, buf = start.group(1), [line.rstrip()]
        else:
            buf.append(line.rstrip())
    flush()
    return intros, blocks


def assemble(result: dict, intros: dict[str, str], blocks: dict[str, str],
             fill: bool = True) -> tuple[str, list[str]]:
    """The UI Interaction Contracts section, built by the pipeline: every screen in
    order, every element in order, each with the writer's block — or, with `fill`,
    the computed line when the writer gave none. Returns (section, filled ids)."""
    lines = [SECTION_HEADING, "",
             "_Written by the Enterprise Architect agent, screen by screen, from the computed contracts and the "
             "evidence, and checked against them. A control the agent did not describe is given here from the "
             "computed contracts._", ""]
    filled: list[str] = []
    for screen in result.get("screens", []):
        lines += [f"### Screen `{screen['file']}`", ""]
        if intros.get(screen["file"]):
            lines += [intros[screen["file"]], ""]
        for e in screen["elements"]:
            if blocks.get(e["id"]):
                lines.append(blocks[e["id"]])
            elif fill:
                lines.append(fallback(e))
                filled.append(e["id"])
        lines.append("")
    return "\n".join(lines).rstrip(), filled


def calls(result: dict) -> set[tuple[str, str]]:
    """(method, path) of every call the UI makes and every handler it reaches."""
    out = {(e["verb"], e["path"]) for s in result.get("screens", []) for e in s["elements"] if e["path"]}
    out |= {tuple(c["endpoint"].split(" ", 1)) for c in result.get("contracts", [])}
    return out


def ids(result: dict) -> list[str]:
    return [e["id"] for s in result.get("screens", []) for e in s["elements"]]


def uncovered(result: dict, document: str) -> list[str]:
    """UI element ids the Architect's specification does not mention."""
    mentioned = set(ID_RE.findall(document or ""))
    return [i for i in ids(result) if i not in mentioned]


def dumps(result: dict) -> str:
    return json.dumps(result)
