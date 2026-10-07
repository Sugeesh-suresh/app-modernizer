"""
UI pages and every interactive component on them, read from the code — no model.

For each server-rendered page (Thymeleaf, JSP or plain HTML template) this lists
every control a user can act on — links, buttons, forms and their inputs,
selects, text areas, grids, elements with an inline handler or a Bootstrap
toggle, and the elements the page's scripts bind to — with:

- **Element id**: the HTML `id`, or the locator a developer would use when there
  is none (`name`, `th:field`, class, …).
- **Action**: what using it does — navigates, submits a form, runs a script
  handler, opens a dialog, or only feeds a form.
- **Interaction / state**: when it is shown (`th:if`/`th:unless`/`sec:authorize`/
  `c:if`, repeated per row by `th:each`), its states (`disabled`, `th:disabled`,
  `th:classappend`, …), its client-side checks, and what its script handler does
  on the page (updates an element, shows or hides one, asks for confirmation,
  shows a message, stores a value, reloads).
- **Target navigation**: the page it leads to (the template the handler of the
  link or form renders, a redirect after a submit, a `location.href` in its
  handler), or that it stays on the page.
- **API called**: the handler each call reaches, from `ui_contracts` (the same
  matching and `UI-nnn` ids as the UI-to-Backend Contracts).
- **Data fields**: for every call, the request parameters and body fields with
  types and constraints, and the response fields (or, for a page, the model it
  renders) — from the handler's contract.

Components of a fragment or layout are listed on each page that includes it, at
the place it is included. A script binding whose element is not in the page's
markup (built at run time) is listed under the page. Script effects are text
patterns over the handler's code (jQuery and DOM APIs); single-page
applications (React, Angular, Vue) are covered by the UI-to-Backend Contracts.
"""
import html.parser
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import ui_contracts as uc

HEADING = "## UI Pages and Interactive Components (computed)"
MAX_INCLUDE_DEPTH = 4
MAX_EFFECTS = 12

_INTERACTIVE = {"a", "button", "input", "select", "textarea", "form", "form:form", "form:input", "form:select",
                "form:textarea", "form:checkbox", "form:radiobutton", "form:password", "summary"}
_FIELD = {"input", "select", "textarea", "form:input", "form:select", "form:textarea", "form:checkbox",
          "form:radiobutton", "form:password"}
_EVENT_ATTR = re.compile(r"^(?:on(\w+)|th:on(\w+)|data-th-on(\w+))$")
_STATE_ATTRS = ("disabled", "readonly", "required", "checked", "selected", "multiple", "hidden")
_CHECKS = ("required", "maxlength", "minlength", "min", "max", "pattern", "step", "accept")
_INCLUDE = re.compile(r"^(?:th|data-th)[:-](?:replace|insert|include|substituteby)$|^layout:decorate$|"
                      r"^data-layout-decorate$")
_JSP_INCLUDE = re.compile(r"<%@\s*include\s+file\s*=\s*\"([^\"]+)\"|<jsp:include\s+page\s*=\s*\"([^\"]+)\"")


@dataclass
class Component:
    file: str
    line: int
    tag: str
    attrs: dict
    text: str = ""
    form: "Component | None" = None
    conditions: list = field(default_factory=list)
    fragment: str = ""                 # the th:fragment it sits in
    origin: str = ""                   # the fragment / layout file it came from, on an including page
    calls: list = field(default_factory=list)       # ui_contracts elements (dicts) tied to it
    handlers: list = field(default_factory=list)    # (via, effects, functions)
    reads: list = field(default_factory=list)       # "script.js:12"
    selectors: list = field(default_factory=list)   # the script selectors that matched it
    label_text: str = ""                            # its <label>
    options: list = field(default_factory=list)     # a select's fixed options: [value, text]
    read_by: list = field(default_factory=list)     # names of the script functions that read its value
    ref: str = ""

    @property
    def kind(self) -> str:
        t, ty = self.tag.split(":")[-1], self.attrs.get("type", "").lower()
        if t == "a":
            return "link"
        if t == "table":
            return "grid"
        if t in ("form",):
            return "form"
        if t == "button" or (t == "input" and ty in ("submit", "button", "image", "reset")):
            return "button"
        if t == "input" and ty in ("checkbox", "radio"):
            return ty
        if t in ("input", "password"):
            return "input"
        if t in ("select", "textarea", "checkbox", "radiobutton"):
            return {"checkbox": "checkbox", "radiobutton": "radio"}.get(t, t)
        return t

    def name(self) -> str:
        a = self.attrs
        tf = a.get("th:field") or a.get("data-th-field") or ""
        return a.get("name") or a.get("path") or (re.sub(r"^[*$]\{\s*|\s*\}$", "", tf) if tf else "")

    def caption(self) -> str:
        a = self.attrs
        if self.kind in ("input", "checkbox", "radio", "select", "textarea"):
            return uc._short(self.label_text, 50) or a.get("aria-label") or a.get("title") or a.get("placeholder") \
                or a.get("th:placeholder") or ""
        for key in ("th:text", "th:utext", "data-th-text"):
            if a.get(key):
                return a[key]
        text = uc._short(self.text, 50)
        return text or a.get("value") or a.get("aria-label") or a.get("title") or ""

    def locator(self) -> str:
        a = self.attrs
        if a.get("id"):
            return f"`#{a['id']}`"
        bits = []
        if self.name():
            bits.append(f"name=`{self.name()}`")
        if a.get("th:field"):
            bits.append(f"th:field=`{a['th:field']}`")
        if a.get("class") and not bits:
            bits.append("class=`" + ".".join(a["class"].split()) + "`")
        return "— (" + ", ".join(bits) + ")" if bits else "— (no id)"

    def label(self) -> str:
        cap = self.caption()
        return f"{self.kind} \"{cap}\"" if cap else self.kind


class _Reader(html.parser.HTMLParser):
    """Every interactive element of a template, with the conditions around it and the includes."""

    def __init__(self, rel: str):
        super().__init__(convert_charrefs=True)
        self.rel = rel
        self.components: list[Component] = []
        self.includes: list[tuple[int, str, str]] = []      # (line, target, fragment selector)
        self.scripts: list[str] = []
        self.inline: list[tuple[int, str]] = []
        self._stack: list[tuple[str, list, str, bool]] = []  # (tag, conditions added here, fragment, opens a switch)
        self._open: list[Component] = []
        self._forms: list[Component] = []
        self._script: dict | None = None
        self._switch: list[str] = []
        self._labels: list[dict] = []                         # open <label>s
        self._option: Component | None = None                 # the select whose <option> is open
        self.label_for: dict[str, str] = {}                   # element id -> its label's text

    def _conditions(self) -> list[str]:
        return [c for _, conds, _, _ in self._stack for c in conds]

    def _fragment(self) -> str:
        return next((f for _, _, f, _ in reversed(self._stack) if f), "")

    def handle_starttag(self, tag, attrs_list):
        a = {k.lower(): (v or "") for k, v in attrs_list}
        tag = tag.lower()
        line = self.getpos()[0]
        if tag == "script":
            src = a.get("th:src") or a.get("src") or a.get("data-th-src")
            if src:
                self.scripts.append(src)
            self._script = {"line": line, "code": [], "src": bool(src)}
        for key, value in a.items():
            if _INCLUDE.match(key) and value:
                m = re.match(r"\s*~?\{?\s*([^:}\s]*)\s*(?:::\s*([\w-]+))?", value)
                if m and m.group(1):
                    self.includes.append((line, m.group(1), m.group(2) or ""))
        conds = []
        for key in ("th:if", "data-th-if"):
            if a.get(key):
                conds.append(f"shown when `{a[key]}`")
        for key in ("th:unless", "data-th-unless"):
            if a.get(key):
                conds.append(f"hidden when `{a[key]}`")
        for key in ("sec:authorize", "sec:authorize-url"):
            if a.get(key):
                conds.append(f"only for `{a[key]}`")
        if tag in ("c:if", "c:when") and a.get("test"):
            conds.append(f"shown when `{a['test']}`")
        if a.get("th:switch"):
            self._switch.append(a["th:switch"])
        if a.get("th:case") and self._switch:
            conds.append(f"shown when `{self._switch[-1]}` is `{a['th:case']}`")
        each = a.get("th:each") or a.get("data-th-each") or (a.get("items") if tag == "c:foreach" else "")
        if each:
            conds.append(f"one per item of `{uc._expr_root(each) or each}`")
        fragment = (a.get("th:fragment") or a.get("data-th-fragment") or a.get("layout:fragment") or "")
        fragment = re.split(r"[\s(]", fragment.strip())[0] if fragment else ""

        interactive = tag in _INTERACTIVE or any(_EVENT_ATTR.match(k) for k in a) or \
            a.get("data-bs-toggle") or a.get("data-toggle") or a.get("role") in ("button", "tab", "link")
        if tag == "input" and a.get("type", "").lower() == "hidden":
            interactive = False
        if tag == "table":
            interactive = True                     # a grid: kept only if a row repeats (see endtag)
        comp = None
        if interactive:
            comp = Component(self.rel, line, tag, a, form=self._forms[-1] if self._forms and tag in _FIELD
                             or (self._forms and tag in ("button", "input")) else None,
                             conditions=self._conditions() + conds, fragment=fragment or self._fragment())
            self.components.append(comp)
            if tag in ("form", "form:form"):
                self._forms.append(comp)
            if self._labels and tag in _FIELD:
                self._labels[-1]["fields"].append(comp)
        if tag == "label":
            self._labels.append({"for": a.get("for", ""), "text": [], "fields": []})
        if tag == "option" and not (a.get("th:each") or a.get("data-th-each")):
            select = next((c for c in reversed(self._open) if c.kind == "select"), None)
            if select is not None:
                select.options.append([a.get("value"), ""])
                self._option = select
        void = tag in uc._TemplateReader._VOID
        if not void:
            self._stack.append((tag, conds, fragment, bool(a.get("th:switch"))))
            if comp is not None:
                self._open.append(comp)
        if tag == "tr" and each:
            table = next((c for c in reversed(self._open) if c.tag == "table"), None)
            if table is not None:
                table.attrs.setdefault("__rows", uc._expr_root(each) or each)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in uc._TemplateReader._VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "script" and self._script is not None:
            if not self._script["src"] and self._script["code"]:
                self.inline.append((self._script["line"], "".join(self._script["code"])))
            self._script = None
        if tag in ("form", "form:form") and self._forms:
            self._forms.pop()
        if tag in ("option", "select"):
            if self._option is not None and self._option.options:
                opt = self._option.options[-1]
                opt[1] = re.sub(r"\s+", " ", opt[1]).strip()
                if opt[0] is None:
                    opt[0] = opt[1]
            self._option = None
        if tag == "label" and self._labels:
            lab = self._labels.pop()
            text = re.sub(r"\s+", " ", "".join(lab["text"])).strip()
            if text:
                if lab["for"]:
                    self.label_for[lab["for"]] = text
                for f in lab["fields"]:
                    f.label_text = f.label_text or text
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i].tag == tag:
                c = self._open.pop(i)
                if c.tag == "table" and "__rows" not in c.attrs:
                    self.components.remove(c)              # a layout table, not a data grid
                break
        while self._stack:
            t, _, _, switch = self._stack.pop()
            if switch and self._switch:
                self._switch.pop()
            if t == tag:
                break

    def handle_data(self, data):
        if self._script is not None:
            self._script["code"].append(data)
            return
        for lab in self._labels:
            lab["text"].append(data)
        if self._option is not None and self._option.options:
            self._option.options[-1][1] += data
        for c in self._open:
            if c.tag.split(":")[-1] not in ("table", "form", "select", "textarea"):
                c.text += data


# ── script effects ──────────────────────────────────────────────────────────

_SEL = r"(?:\$\w*|jQuery)\(\s*([^()]*?)\s*\)"
_EFFECTS = [
    (re.compile(_SEL + r"\s*\.\s*(text|html|val|append|prepend|replaceWith)\s*\((?!\s*\))"),
     lambda m: (f"sets the value of {_sel(m.group(1))}" if m.group(2) == "val"
                else f"updates the content of {_sel(m.group(1))}")),
    (re.compile(_SEL + r"\s*\.\s*(empty|remove)\s*\("),
     lambda m: f"{'clears' if m.group(2) == 'empty' else 'removes'} {_sel(m.group(1))}"),
    (re.compile(_SEL + r"\s*\.\s*(show|fadeIn|slideDown)\s*\("), lambda m: f"shows {_sel(m.group(1))}"),
    (re.compile(_SEL + r"\s*\.\s*(hide|fadeOut|slideUp)\s*\("), lambda m: f"hides {_sel(m.group(1))}"),
    (re.compile(_SEL + r"\s*\.\s*(toggle|slideToggle)\s*\("), lambda m: f"shows or hides {_sel(m.group(1))}"),
    (re.compile(_SEL + r"\s*\.\s*(addClass|removeClass|toggleClass)\s*\(\s*['\"]([^'\"]+)"),
     lambda m: f"{ {'addClass': 'adds', 'removeClass': 'removes', 'toggleClass': 'toggles'}[m.group(2)]} class "
               f"`{m.group(3)}` on {_sel(m.group(1))}"),
    (re.compile(_SEL + r"\s*\.\s*(?:prop|attr)\s*\(\s*['\"](disabled|checked|readonly|hidden|selected)['\"]\s*,"
                r"\s*([^)]+)\)"), lambda m: f"sets `{m.group(2)}` = `{m.group(3).strip()}` on {_sel(m.group(1))}"),
    (re.compile(_SEL + r"\s*\.\s*modal\s*\(\s*['\"](show|hide|toggle)"),
     lambda m: f"{ {'show': 'opens', 'hide': 'closes', 'toggle': 'opens or closes'}[m.group(2)]} dialog "
               f"{_sel(m.group(1))}"),
    (re.compile(r"getElementById\(\s*['\"]([\w-]+)['\"]\s*\)\s*\.\s*(textContent|innerHTML|innerText|value|checked|"
                r"disabled|hidden)\s*=(?!=)"),
     lambda m: (f"sets the value of `#{m.group(1)}`" if m.group(2) == "value" else
                f"updates the content of `#{m.group(1)}`" if m.group(2) in ("textContent", "innerHTML", "innerText")
                else f"sets `{m.group(2)}` on `#{m.group(1)}`")),
    (re.compile(r"getElementById\(\s*['\"]([\w-]+)['\"]\s*\)\s*\.\s*style\.display\s*=\s*['\"](\w*)['\"]"),
     lambda m: f"{'hides' if m.group(2) == 'none' else 'shows'} `#{m.group(1)}`"),
    (re.compile(r"classList\.(add|remove|toggle)\(\s*['\"]([^'\"]+)"),
     lambda m: f"{ {'add': 'adds', 'remove': 'removes', 'toggle': 'toggles'}[m.group(1)]} class `{m.group(2)}`"),
    (re.compile(r"\bconfirm\(\s*(['\"`])(.*?)\1"), lambda m: f"asks for confirmation: \"{m.group(2)}\""),
    (re.compile(r"\balert\(\s*([^;\n]*?)\)\s*;?\s*$", re.M), lambda m: f"shows a message: `{m.group(1).strip()}`"),
    (re.compile(r"(?:window\.)?location(?:\.href)?\s*=(?!=)\s*([^;\n]+)"),
     lambda m: f"navigates to `{m.group(1).strip()}`"),
    (re.compile(r"location\.(?:assign|replace)\(\s*([^)]+)\)"), lambda m: f"navigates to `{m.group(1).strip()}`"),
    (re.compile(r"window\.open\(\s*([^,)]+)"), lambda m: f"opens `{m.group(1).strip()}` in a new window"),
    (re.compile(r"location\.reload\(\s*\)"), lambda m: "reloads the page"),
    (re.compile(_SEL + r"\s*\.\s*submit\s*\(\s*\)"), lambda m: f"submits {_sel(m.group(1))}"),
    (re.compile(r"new\s+Handsontable\s*\(\s*(?:document\.getElementById\(\s*['\"]([\w-]+)['\"]\s*\)|"
                r"(?:\$\w*|jQuery)\(\s*['\"]#([\w-]+)['\"]\s*\)\s*\[\s*0\s*\])"),
     lambda m: f"fills grid `#{m.group(1) or m.group(2)}` with the response"),
    (re.compile(_SEL + r"\s*\.\s*(?:DataTable|dataTable|handsontable|jqGrid|bootstrapTable|kendoGrid)\s*\("),
     lambda m: f"fills grid {_sel(m.group(1))} with the response"),
    (re.compile(r"\b(\w+)\s*\.\s*(?:loadData|setData)\s*\("), lambda m: f"reloads grid `{m.group(1)}` with new data"),
    (re.compile(r"\b(\w+)\s*\.\s*updateSettings\s*\(\s*\{[^}]*\b(?:columns|colHeaders)\b"),
     lambda m: f"changes the columns of grid `{m.group(1)}`"),
    (re.compile(r"getPlugin\(\s*['\"]hiddenColumns['\"]\s*\)\s*\.\s*(hideColumns?|showColumns?)"),
     lambda m: f"{'hides' if m.group(1).startswith('hide') else 'shows'} grid columns"),
    (re.compile(r"getPlugin\(\s*['\"](?:filters|search)['\"]\s*\)|\.search\s*\.\s*query\s*\("),
     lambda m: "filters or highlights the grid rows in the browser"),
    (re.compile(r"\.column\(\s*[^)]*\)\s*\.\s*visible\s*\("), lambda m: "shows or hides grid columns"),
    (re.compile(r"(localStorage|sessionStorage)\.setItem\(\s*['\"]([^'\"]+)"),
     lambda m: f"stores `{m.group(2)}` in {m.group(1)}"),
    (re.compile(r"\.preventDefault\(\s*\)"), lambda m: "stops the browser's default action"),
    (re.compile(r"\breturn\s+false\b"), lambda m: "can cancel the action (returns false)"),
]
_READS = [re.compile(r"(?:\$\w*|jQuery)\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\.\s*(?:val\(\s*\)|is\(\s*['\"]:checked)"),
          re.compile(r"getElementById\(\s*['\"]([\w-]+)['\"]\s*\)\s*\.\s*value\b(?!\s*=[^=])")]


def _sel(raw: str) -> str:
    raw = raw.strip()
    if raw in ("this", "e.target", "event.target", "e.currentTarget"):
        return "the element itself"
    lit = re.fullmatch(r"(['\"`])(.*)\1", raw)
    return f"`{lit.group(2)}`" if lit else f"`{raw}`"


def _effects(text: str, first_line: int, rel: str) -> list[str]:
    found = []
    for pattern, describe in _EFFECTS:
        for m in pattern.finditer(text):
            found.append((text.count("\n", 0, m.start()) + first_line, describe(m)))
    out = []
    for line, what in sorted(found):
        item = f"{what} (`{Path(rel).name}:{line}`)"
        if item not in out:
            out.append(item)
    return out[:MAX_EFFECTS]


def _node_text(sc, node) -> str:
    return sc.src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _grid_names(sc) -> dict[str, str]:
    """`hot` → `#jobGrid` for `var hot = new Handsontable(document.getElementById('jobGrid'), …)`."""
    text = sc.src.decode("utf-8", "replace")
    out = {}
    for m in re.finditer(r"\b(\w+)\s*=\s*new\s+Handsontable\s*\(\s*(?:document\.getElementById\(\s*['\"]([\w-]+)['\"]"
                         r"\s*\)|(?:\$\w*|jQuery)\(\s*['\"]#([\w-]+)['\"]\s*\)\s*\[\s*0\s*\])", text):
        out[m.group(1)] = "#" + (m.group(2) or m.group(3))
    for m in re.finditer(r"\b(\w+)\s*=\s*(?:\$\w*|jQuery)\(\s*['\"](#[\w-]+)['\"]\s*\)\s*\.\s*(?:DataTable|dataTable)\s*\(", text):
        out[m.group(1)] = m.group(2)
    return out


def _handler_effects(sc, fn) -> tuple[list[str], list[str]]:
    """What a handler function does on the page, with the functions it calls one hop down."""
    texts = [(fn, _node_text(sc, fn))]
    names = []
    for name in dict.fromkeys(re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", texts[0][1])):
        for other in sc.functions.get(name, []):
            if other is not fn and (other.start_byte, other.end_byte) != (fn.start_byte, fn.end_byte):
                texts.append((other, _node_text(sc, other)))
                names.append(name)
    effects = []
    joined = "\n".join(t for _, t in texts)
    grids = _grid_names(sc)
    local = re.search(r"\.filter\s*\(", joined) and not re.search(
        r"\$\s*\.\s*(?:ajax|get|post|getJSON)|\bfetch\s*\(|axios|XMLHttpRequest", joined)
    for node, text in texts:
        for e in _effects(text, sc.line(node), sc.rel):
            m = re.match(r"(reloads grid|changes the columns of grid) `(\w+)`(.*)$", e)
            if m and m.group(2) in grids:
                e = f"{m.group(1)} `{grids[m.group(2)]}`{m.group(3)}"
            if local and e.startswith("reloads grid"):
                e = e.replace("reloads grid", "filters the rows already loaded and re-shows grid", 1) \
                    .replace(" with new data", "")
            if e not in effects:
                effects.append(e)
    return effects[:MAX_EFFECTS], names


def _simple(selector: str) -> list[tuple[str, str, list, dict]]:
    """`form#a.b[name=q]` → [(tag, id, classes, attrs)], one per comma-separated selector (last compound)."""
    out = []
    for part in selector.split(","):
        last = re.split(r"[\s>+~]+", part.strip())[-1] if part.strip() else ""
        last = re.sub(r":[\w-]+(?:\([^)]*\))?", "", last)
        if not last:
            continue
        tag = re.match(r"^[a-zA-Z][\w-]*", last)
        ident = re.search(r"#([\w-]+)", last)
        attrs = dict((k.lower(), v.strip("'\"")) for k, v in re.findall(r"\[([\w-]+)\s*=\s*([^\]]+)\]", last))
        out.append((tag.group(0).lower() if tag else "", ident.group(1) if ident else "",
                    re.findall(r"\.([\w-]+)", last), attrs))
    return out


def _matches(selector: str, comp: Component) -> bool:
    a = comp.attrs
    classes = set(a.get("class", "").split())
    for tag, ident, cls, attrs in _simple(selector):
        if not (ident or cls or attrs):
            continue                       # a bare tag (`input`, `button`) names no element in particular
        if tag and comp.tag.split(":")[-1] != tag:
            continue
        if ident and a.get("id") != ident:
            continue
        if cls and not set(cls) <= classes:
            continue
        if attrs and any(a.get(k) != v and not (k == "name" and comp.name() == v) for k, v in attrs.items()):
            continue
        return True
    return False


# ── assembling a page ───────────────────────────────────────────────────────

@dataclass
class _Page:
    rel: str
    components: list
    scripts: list
    loaded_by: list
    includes: list
    orphans: list = field(default_factory=list)       # (selector, event, via, effects)
    page_calls: list = field(default_factory=list)    # ui_contracts elements run on load / by a timer
    contracts: dict = field(default_factory=dict)
    served: dict = field(default_factory=dict)
    endpoints: list = field(default_factory=list)
    files: list = field(default_factory=list)          # the template files its elements come from


def _template_index(rels: list[str]) -> dict[str, str]:
    """`fragments/header` (as an include names it) → its template file."""
    index = {}
    for rel in rels:
        m = re.search(r"(?:^|/)(?:templates|WEB-INF/(?:jsp|views|pages)|webapp)/(.+?)\.\w+$", rel)
        if m:
            index.setdefault(m.group(1), rel)
        index.setdefault(re.sub(r"\.\w+$", "", rel), rel)
    return index


def _resolve(target: str, index: dict[str, str], rels: list[str]) -> str | None:
    target = target.strip().lstrip("/")
    target = re.sub(r"\.(html?|jspf?)$", "", target)
    if target in index:
        return index[target]
    hits = [r for r in rels if re.sub(r"\.\w+$", "", r).endswith("/" + target)]
    return hits[0] if hits else None


def _expanded(rel: str, readers: dict, index: dict, rels: list, depth: int = 0, fragment: str = "",
              origin: str = "") -> list[Component]:
    """A template's components with those of the fragments and layouts it includes, in place."""
    reader = readers.get(rel)
    if reader is None or depth > MAX_INCLUDE_DEPTH:
        return []
    own = [c for c in reader.components if not fragment or c.fragment == fragment]
    out: list[Component] = []
    includes = sorted(reader.includes)
    copies: dict[int, Component] = {}
    for c in own:
        while includes and includes[0][0] < c.line:
            out += _include(includes.pop(0), rel, readers, index, rels, depth, origin)
        if origin:                                     # a fragment's elements, once per including page
            copy = Component(c.file, c.line, c.tag, c.attrs, c.text, copies.get(id(c.form)) if c.form else None,
                             list(c.conditions), c.fragment, origin, label_text=c.label_text,
                             options=c.options)
            copies[id(c)] = copy
            c = copy
        out.append(c)
    for inc in includes:
        out += _include(inc, rel, readers, index, rels, depth, origin)
    return out


def _include(inc, rel, readers, index, rels, depth, origin) -> list[Component]:
    _, target, frag = inc
    if not target:
        return []
    found = _resolve(target, index, rels)
    if not found or found == rel:
        return []
    return _expanded(found, readers, index, rels, depth + 1, frag, origin or found)


def scan(workspace_dir: str, inventory: dict, ui_result: dict) -> list[_Page]:
    root = Path(workspace_dir)
    if not root.is_dir():
        return []
    templates, script_paths = uc._ui_files(root)
    rels = [p.relative_to(root).as_posix() for p in templates]
    script_rels = [p.relative_to(root).as_posix() for p in script_paths]
    readers: dict[str, _Reader] = {}
    texts: dict[str, str] = {}
    for path, rel in zip(templates, rels):
        if path.suffix.lower() not in (".html", ".htm", ".jsp", ".jspf", ".xhtml"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        texts[rel] = text
        reader = _Reader(rel)
        try:
            reader.feed(text)
            reader.close()
        except Exception:                                    # noqa: BLE001 — malformed markup: use what was read
            pass
        for c in reader.components:
            if c.attrs.get("id") in reader.label_for and not c.label_text:
                c.label_text = reader.label_for[c.attrs["id"]]
        for m in _JSP_INCLUDE.finditer(text):
            reader.includes.append((text.count("\n", 0, m.start()) + 1, m.group(1) or m.group(2), ""))
        readers[rel] = reader
    index = _template_index(list(readers))
    endpoints = inventory.get("endpoints", [])
    served = uc._view_files(endpoints, list(readers))
    included = {(_resolve(t, index, list(readers)) or "") for r in readers.values() for _, t, _ in r.includes}

    def is_page(rel: str) -> bool:
        if served.get(rel):
            return True
        if rel in included:
            return False
        text = texts.get(rel, "")
        return bool(readers[rel].components) and bool(re.search(r"<html|<!doctype|layout:decorat", text, re.I)) \
            and not re.search(r"(?:^|/)(?:fragments?|layouts?|partials?|includes?)/", rel)

    contracts = {f"{c['endpoint']} {c['handler']}": c for c in ui_result.get("contracts", [])}
    elements = [dict(e, file=e["source"].rsplit(":", 1)[0], line=int(e["source"].rsplit(":", 1)[1]))
                for s in ui_result.get("screens", []) for e in s["elements"]]
    scripts_cache: dict[str, object] = {}

    def script(rel: str):
        if rel not in scripts_cache:
            path = root / rel
            grammar = uc._SCRIPT_SUFFIXES.get(path.suffix.lower())
            try:
                scripts_cache[rel] = uc._Script(rel, path.read_text(encoding="utf-8", errors="replace"), grammar) \
                    if grammar in uc._PARSERS else None
            except Exception:                                # noqa: BLE001
                scripts_cache[rel] = None
        return scripts_cache[rel]

    pages = []
    for rel in sorted(readers):
        if not is_page(rel):
            continue
        comps = _expanded(rel, readers, index, list(readers))
        files = {rel} | {c.file for c in comps}
        script_files = []
        for f in sorted(files):
            for ref in readers[f].scripts:
                script_files += [s for s in uc._script_matches(ref, script_rels) if s not in script_files]
        page = _Page(rel, comps, script_files, served.get(rel, []),
                     sorted({c.origin for c in comps if c.origin}))
        _tie_calls(page, files, elements)
        _tie_scripts(page, files, readers, script, elements)
        for k, c in enumerate(page.components, 1):
            c.ref = f"C{k}"
        page.contracts, page.served, page.endpoints = contracts, served, endpoints
        page.files = sorted(files)
        pages.append(page)
    # A shared script's binding whose element is on another page that loads it is not missing.
    found_on = {(h["how"], sel) for p in pages for c in p.components for h in c.handlers for sel in c.selectors}
    for p in pages:
        p.orphans = [o for o in p.orphans if (o[2], o[0]) not in found_on]
    return pages


def _tie_calls(page: _Page, files: set, elements: list[dict]) -> None:
    """Calls the template itself makes (forms, links, formaction buttons, grids), by file and line."""
    by_place: dict[tuple, list] = {}
    for c in page.components:
        by_place.setdefault((c.file, c.line), []).append(c)
    for e in elements:
        if e["file"] not in files or e["kind"] not in ("form", "link", "button", "grid", "select"):
            continue
        if e["via"]:
            continue                                       # a script binding: tied by selector or handler below
        hits = by_place.get((e["file"], e["line"]), [])
        want = {"form": ("form",), "link": ("link",), "button": ("button",), "grid": ("grid",),
                "select": ("select",)}[e["kind"]]
        target = next((c for c in hits if c.kind in want), None)
        if target is None and e["kind"] == "select":     # server-filled options: the select above them
            above = [c for c in page.components if c.file == e["file"] and c.kind == "select"
                     and c.line <= e["line"]]
            target = above[-1] if above else None
        if target is not None and e not in target.calls:
            target.calls.append(e)


_LIBRARY_SCRIPT = re.compile(
    r"(?:^|/|[-_.])(?:jquery|bootstrap|handsontable|chosen|select2|datatables?|moment|lodash|underscore|knockout|"
    r"angular|react|react-dom|vue|d3|chartjs|popper|toastr|sweetalert2?|fullcalendar|ckeditor|tinymce|"
    r"codemirror|summernote|dropzone|backbone|requirejs|require|handlebars|mustache|kendo|ext-all|dojo|"
    r"mootools|highcharts|echarts|leaflet|pdfjs|jszip|filesaver|bootbox|daterangepicker|bootstrap-datepicker|"
    r"flatpickr|pikaday|swiper|tippy|clipboard|polyfills?|modernizr|html5shiv|font-?awesome)(?:[-_.]|$)", re.I)

_BIND = re.compile(
    r"(?:\$\w*|jQuery)\(\s*(['\"])([^'\"]+)\1\s*\)\s*\.\s*(?:(on|bind|live|one)\s*\(\s*(['\"])([\w.: ]+)\4|"
    r"(click|dblclick|change|submit|keyup|keydown|keypress|input|blur|focus)\s*\()"
    r"|getElementById\(\s*['\"]([\w-]+)['\"]\s*\)\s*\.\s*(?:addEventListener\(\s*['\"](\w+)['\"]|on(\w+)\s*=(?!=))"
    r"|querySelector\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\.\s*(?:addEventListener\(\s*['\"](\w+)['\"]|on(\w+)\s*=(?!=))"
    r"|\b([A-Za-z_$][\w$]*)\s*\.\s*on(click|change|submit|keyup|keydown|input)\s*=(?!=)")
#: Effects that are not something a user sees.
_SILENT = ("stops the browser's default action", "can cancel the action")


def is_library(rel: str) -> bool:
    """A third-party script (plugin, framework) whose bindings are not the application's behaviour."""
    return bool(_LIBRARY_SCRIPT.search(Path(rel).name)) or bool(uc._VENDORED.search(rel))


def _span_nodes(sc) -> dict:
    nodes, stack = {}, [sc.tree.root_node]
    while stack:
        n = stack.pop()
        nodes[(n.start_byte, n.end_byte)] = n
        stack.extend(n.children)
    return nodes


def _callback_at(sc, offset: int):
    """The handler function of the binding call that starts at byte `offset` (its last argument)."""
    node = sc.tree.root_node.descendant_for_byte_range(offset, offset)
    while node is not None and node.type != "call_expression":
        node = node.parent
    # The binding call is the outermost call that still starts on this selector: climb `.on(...)` chains.
    while node is not None and node.parent is not None and node.parent.type in ("member_expression",
                                                                                 "call_expression"):
        node = node.parent
    if node is not None and node.type == "member_expression":
        node = node.parent
    if node is None:
        return None
    args = node.child_by_field_name("arguments") if node.type == "call_expression" else None
    if node.type == "assignment_expression":
        value = node.child_by_field_name("right")
    elif args is not None:
        named = [c for c in args.children if c.is_named]
        value = named[-1] if named else None
    else:
        value = None
    if value is None:
        return None
    if value.type in ("function_expression", "arrow_function", "function"):
        return value
    name = uc._text(value.child_by_field_name("property") if value.type == "member_expression" else value, sc.src)
    found = sc.functions.get(name, [])
    return found[0] if found else None


_CHECKED = re.compile(r"(?:\$\w*|jQuery)\(\s*['\"]#([\w-]+)['\"]\s*\)\s*\.\s*(?:is\(\s*['\"]:checked['\"]\s*\)|"
                      r"prop\(\s*['\"]checked['\"]\s*\))|getElementById\(\s*['\"]([\w-]+)['\"]\s*\)\s*\.\s*checked")


def _readable_condition(cond: str, texts: str) -> str:
    """`only when (showValues)` → `only when `#showValues` is checked`, following the variable to its value."""
    m = re.match(r"only when (not )?\(?\s*(!?)\s*([A-Za-z_$][\w$.]*)\s*\)?$", cond)
    if not m:
        return cond.replace("only when (", "only when ").rstrip(")") if cond.startswith("only when (") and \
            cond.count("(") == 1 else cond
    negate = bool(m.group(1)) != bool(m.group(2))
    name = m.group(3)
    value = re.search(r"\b" + re.escape(name.split(".")[-1]) + r"\s*=(?!=)\s*([^;\n]+)", texts)
    expr = value.group(1).strip() if value else ""
    checked = _CHECKED.search(expr)
    if checked:
        return f"only when `#{checked.group(1) or checked.group(2)}` is {'not ' if negate else ''}checked"
    return f"only when {'not ' if negate else ''}`{name}`" + (f" (= `{expr}`)" if expr else "")


def _grid_columns(sc, fns: list) -> list[dict]:
    """The columns a grid is given in these functions — Handsontable / DataTables `columns: [{data, title}]`,
    `colHeaders`, or cells built as `'<td>' + row.x` — with the condition a column is added under."""
    out: list[dict] = []
    for fn in fns:
        headers: list[str] = []
        stack = [fn]
        objects = []
        while stack:
            n = stack.pop()
            stack.extend(n.children)
            if n.type == "pair":
                key = uc._text(n.child_by_field_name("key"), sc.src).strip("'\"")
                value = n.child_by_field_name("value")
                if key == "colHeaders" and value is not None and value.type == "array":
                    headers = [uc._text(c, sc.src).strip("'\"`") for c in value.children if c.type == "string"]
            if n.type == "object":
                objects.append(n)
        for obj in sorted(objects, key=lambda o: o.start_byte):
            pairs = {uc._text(p.child_by_field_name("key"), sc.src).strip("'\""): p.child_by_field_name("value")
                     for p in obj.children if p.type == "pair"}
            data = pairs.get("data")
            if data is None or data.type != "string":
                continue
            title = next((uc._text(pairs[k], sc.src).strip("'\"`") for k in ("title", "header", "name", "label")
                          if pairs.get(k) is not None and pairs[k].type == "string"), "")
            cond, node = "", obj
            while node is not None and node is not fn:
                parent = node.parent
                if parent is not None and parent.type == "if_statement":
                    test = uc._text(parent.child_by_field_name("condition"), sc.src).strip()
                    alt = parent.child_by_field_name("alternative")
                    inside_alt = alt is not None and alt.start_byte <= obj.start_byte < alt.end_byte
                    cond = f"only when not {test}" if inside_alt else f"only when {test}"
                    break
                if parent is not None and parent.type == "ternary_expression":
                    test = uc._text(parent.child_by_field_name("condition"), sc.src).strip()
                    cons = parent.child_by_field_name("consequence")
                    inside = cons is not None and cons.start_byte <= obj.start_byte < cons.end_byte
                    cond = f"only when {test}" if inside else f"only when not ({test})"
                    break
                node = parent
            out.append({"title": title, "field": uc._text(data, sc.src).strip("'\"`"), "condition": cond,
                        "at": f"{Path(sc.rel).name}:{sc.line(obj)}"})
        for i, col in enumerate(c for c in out if not c["title"]):
            if i < len(headers):
                col["title"] = headers[i]
        text = uc._text(fn, sc.src)
        for m in re.finditer(r"['\"]<td[^>]*>['\"]\s*\+\s*[A-Za-z_$][\w$]*\s*\.\s*(\w+)", text):
            out.append({"title": "", "field": m.group(1), "condition": "",
                        "at": f"{Path(sc.rel).name}:{sc.line(fn) + text.count(chr(10), 0, m.start())}"})
    texts = "\n".join(uc._text(fn, sc.src) for fn in fns)
    for col in out:
        col["condition"] = _readable_condition(col["condition"], texts)
    seen, unique = set(), []
    for col in out:
        if (col["field"], col["condition"]) not in seen:
            seen.add((col["field"], col["condition"]))
            unique.append(col)
    return unique


def _branch(sc, node, stop) -> dict | None:
    """The `if` / `switch` / ternary branch `node` sits in, below `stop`: {"test", "case", "negate"}."""
    while node is not None and node is not stop:
        parent = node.parent
        if parent is None:
            return None
        if parent.type == "switch_case":
            value = parent.child_by_field_name("value")
            sw = parent.parent.parent if parent.parent is not None else None
            test = uc._text(sw.child_by_field_name("value"), sc.src).strip("() ") if sw is not None and \
                sw.child_by_field_name("value") is not None else ""
            return {"test": test, "case": uc._text(value, sc.src).strip("'\"`") if value is not None else None,
                    "negate": False}
        if parent.type == "switch_default":
            return {"test": "", "case": None, "negate": True}
        if parent.type == "if_statement" and node is not parent.child_by_field_name("condition"):
            alt = parent.child_by_field_name("alternative")
            inside_alt = alt is not None and alt.start_byte <= node.start_byte < alt.end_byte
            return {"test": uc._text(parent.child_by_field_name("condition"), sc.src).strip("() "), "case": None,
                    "negate": inside_alt}
        node = parent
    return None


def _array_of(sc, value):
    """An array literal, or the array a variable of the script is given."""
    if value is None:
        return None
    if value.type == "array":
        return value
    if value.type == "identifier":
        name = uc._text(value, sc.src)
        stack = [sc.tree.root_node]
        while stack:
            n = stack.pop()
            stack.extend(n.children)
            if n.type == "variable_declarator" and uc._text(n.child_by_field_name("name"), sc.src) == name:
                v = n.child_by_field_name("value")
                if v is not None and v.type == "array":
                    return v
    return None


def _column_sets(sc, fns: list) -> list[dict]:
    """Each set of columns a handler gives a grid (`updateSettings({columns: …})`, a `columns:` option) with the
    branch that picks it — how a view selector switches what the grid shows, without calling the server."""
    out = []
    for fn in fns:
        stack = [fn]
        while stack:
            n = stack.pop()
            stack.extend(n.children)
            if n.type != "object":
                continue
            pairs = {uc._text(p.child_by_field_name("key"), sc.src).strip("'\""): p.child_by_field_name("value")
                     for p in n.children if p.type == "pair"}
            if "columns" not in pairs and "colHeaders" not in pairs:
                continue
            cols = []
            arr = _array_of(sc, pairs.get("columns"))
            for obj in (arr.children if arr is not None else []):
                if obj.type != "object":
                    continue
                kv = {uc._text(p.child_by_field_name("key"), sc.src).strip("'\""): p.child_by_field_name("value")
                      for p in obj.children if p.type == "pair"}
                if kv.get("data") is not None and kv["data"].type == "string":
                    title = next((uc._text(kv[k], sc.src).strip("'\"`") for k in ("title", "header", "name", "label")
                                  if kv.get(k) is not None and kv[k].type == "string"), "")
                    cols.append({"title": title, "field": uc._text(kv["data"], sc.src).strip("'\"`")})
            headers = _array_of(sc, pairs.get("colHeaders"))
            titles = [uc._text(h, sc.src).strip("'\"`") for h in (headers.children if headers is not None else [])
                      if h.type == "string"]
            for i, t in enumerate(titles):
                if i < len(cols) and not cols[i]["title"]:
                    cols[i]["title"] = t
                elif i >= len(cols):
                    cols.append({"title": t, "field": ""})
            if cols:
                out.append({"branch": _branch(sc, n, fn), "columns": cols, "at": f"{Path(sc.rel).name}:{sc.line(n)}"})
    return out


def _handler(sc, fn, event: str, how: str) -> dict:
    effects, called = _handler_effects(sc, fn) if fn is not None else ([], [])
    spans = []
    if fn is not None:
        spans.append((sc.rel, sc.line(fn), fn.end_point[0] + sc.first_line))
        for name in called:
            for other in sc.functions.get(name, []):
                spans.append((sc.rel, sc.line(other), other.end_point[0] + sc.first_line))
    reached = [fn] + [o for n in called for o in sc.functions.get(n, [])] if fn is not None else []
    own = [n for n, nodes in sc.functions.items() for x in nodes if fn is not None and
           (x.start_byte, x.end_byte) == (fn.start_byte, fn.end_byte)]
    return {"event": event, "how": how, "effects": effects, "spans": spans, "resolved": fn is not None,
            "functions": own + list(called),
            "columns": _grid_columns(sc, reached), "sets": _column_sets(sc, reached) if reached else []}


def _add_handler(c: Component, h: dict, calls: list) -> None:
    if any(x["event"] == h["event"] and x["how"] == h["how"] for x in c.handlers):
        return
    h["calls"] = list({id(e): e for e in calls}.values())            # the calls this handler makes
    c.handlers.append(h)
    for e in calls:
        if e not in c.calls:
            c.calls.append(e)


def _calls_in(spans: list, elements: list[dict]) -> list[dict]:
    return [e for e in elements for rel, a, b in spans if e["file"] == rel and a <= e["line"] <= b
            and e["kind"] not in ("page load", "timer", "grid") and e.get("url")]


def _tie_scripts(page: _Page, files: set, readers: dict, script, elements: list[dict]) -> None:
    """Script handlers bound to the page's elements, what they do, and the calls they make."""
    sources = [(s, script(s)) for s in page.scripts if not is_library(s)]
    for f in sorted(files):
        for line, code in readers[f].inline:
            try:
                sources.append((f, uc._Script(f, code, "javascript", line) if "javascript" in uc._PARSERS else None))
            except Exception:                                # noqa: BLE001
                continue
    rels = {s for s, _ in sources}
    for e in elements:                                        # page-level calls: page load and timers
        if e["file"] in rels | files and e["kind"] in ("page load", "timer"):
            page.page_calls.append(e)
    ids = {c.attrs["id"] for c in page.components if c.attrs.get("id")}
    for rel, sc in sources:
        if sc is None:
            continue
        nodes = _span_nodes(sc)
        name = Path(rel).name
        # Bindings the syntax walk resolved.
        for key, triggers in sc.triggers.items():
            fn = nodes.get(key)
            if fn is None:
                continue
            for selector, event, via in triggers:
                if selector in ("page", "timer", "document", ""):
                    continue
                h = _handler(sc, fn, event, f"{via} in `{name}`")
                targets = [c for c in page.components if _matches(selector, c)]
                calls = [e for e in elements if e["file"] == rel and e["label"] == selector
                         and (e["event"] == event or not event)] + _calls_in(h["spans"], elements)
                if not targets:
                    page.orphans.append((selector, event, h["how"], h["effects"], calls))
                for c in targets:
                    _add_handler(c, h, calls)
                    c.selectors.append(selector)
        # Bindings the walk could not resolve (handler on an object, another jQuery alias, a global id).
        text = sc.src.decode("utf-8", "replace")
        for m in _BIND.finditer(text):
            g = m.groups()
            if g[1]:
                selector, event = g[1], (g[4] or g[5] or "").split(".")[0].split()[0] if (g[4] or g[5]) else ""
            elif g[6]:
                selector, event = "#" + g[6], g[7] or g[8]
            elif g[9]:
                selector, event = g[9], g[10] or g[11]
            else:
                if g[12] not in ids:
                    continue
                selector, event = "#" + g[12], g[13]
            line = text.count("\n", 0, m.start()) + sc.first_line
            targets = [c for c in page.components if _matches(selector, c)]
            if not targets or not event:
                continue
            if all(any(h["event"] == event and h["resolved"] for h in c.handlers) for c in targets):
                continue
            fn = _callback_at(sc, len(text[:m.end()].encode("utf-8")) - 1)
            h = _handler(sc, fn, event, f"bound at `{name}:{line}`")
            if fn is None:
                h["effects"] = ["handler not resolved in the code"]
            calls = _calls_in(h["spans"], elements)
            for c in targets:
                if not any(x["event"] == event and x["resolved"] for x in c.handlers):
                    _add_handler(c, h, calls)
        for pattern in _READS:
            for m in pattern.finditer(text):
                sel = m.group(1) if pattern is _READS[0] else f"#{m.group(1)}"
                line = text.count("\n", 0, m.start()) + sc.first_line
                reader = min(((n, x) for n, xs in sc.functions.items() for x in xs
                              if sc.line(x) <= line <= x.end_point[0] + sc.first_line),
                             key=lambda nx: nx[1].end_byte - nx[1].start_byte, default=(None, None))[0]
                for c in page.components:
                    if _matches(sel, c):
                        spot = f"{name}:{line}"
                        if spot not in c.reads:
                            c.reads.append(spot)
                        if reader and reader not in c.read_by:
                            c.read_by.append(reader)
    # Inline handlers (onclick="search()"): the named function in the page's scripts.
    for c in page.components:
        for key, value in c.attrs.items():
            m = _EVENT_ATTR.match(key)
            if not m or not value:
                continue
            event = next(g for g in m.groups() if g)
            effects = _effects(value, c.line, c.file)
            spans, columns, sets, fnames = [], [], [], []
            names = [n for n in uc._HANDLER_CALL.findall(value) if n not in uc._JS_KEYWORDS]
            for rel, sc in sources:
                if sc is None:
                    continue
                for n in names:
                    for fn in sc.functions.get(n, []):
                        h = _handler(sc, fn, event, "")
                        effects += [x for x in h["effects"] if x not in effects]
                        spans += h["spans"]
                        columns += h["columns"]
                        sets += h["sets"]
                        fnames += h["functions"]
            calls = [e for e in elements if (lambda s: s and s.group(1) == c.file and int(s.group(2)) == c.line)(
                re.search(r"inline \w+ handler in (\S+):(\d+)", e.get("via", "")))] + _calls_in(spans, elements)
            _add_handler(c, {"event": event, "how": f"inline `{value.strip()}`", "effects": effects[:MAX_EFFECTS],
                             "spans": spans, "resolved": True, "columns": columns, "sets": sets,
                             "functions": fnames}, calls)
    # Where an element with no behaviour found is named in the page's scripts.
    for c in page.components:
        if c.handlers or c.calls or c.reads or not c.attrs.get("id") or c.kind not in ("button", "link", "checkbox", "radio",
                                                                             "select", "input", "textarea"):
            continue
        ident = re.compile(r"['\"#]" + re.escape(c.attrs["id"]) + r"\b")
        for rel, sc in sources:
            if sc is None:
                continue
            text = sc.src.decode("utf-8", "replace")
            for m in ident.finditer(text):
                spot = f"{Path(rel).name}:{text.count(chr(10), 0, m.start()) + sc.first_line}"
                if spot not in c.reads and len(c.reads) < 5:
                    c.reads.append(spot)


# ── describing a component ──────────────────────────────────────────────────

def _endpoint_text(key: str) -> str:
    verb, path, handler = key.split(" ", 2)
    return f"`{verb} {path}` → `{handler}`"


def _targets_of_page_endpoint(page: _Page, key: str) -> list[str]:
    verb, path, handler = key.split(" ", 2)
    return [rel for rel, eps in page.served.items()
            if any(e["verb"] == verb and e["path"] == path and e["handler"] == handler for e in eps)]


def _short_template(rel: str) -> str:
    m = re.search(r"(?:templates|WEB-INF/(?:jsp|views|pages)|webapp)/(.+)$", rel)
    return m.group(1) if m else rel


def _page_of(page: _Page, path: str) -> list[str]:
    found, _ = uc.match(uc.normalize(path), "GET", page.endpoints)
    return [t for e in found for t in _targets_of_page_endpoint(page, f"{e['verb']} {e['path']} {e['handler']}")]


def _js_url(expr: str) -> str:
    """`'/orders/' + id` → `/orders/{}`: literal parts kept, anything else unknown."""
    parts = []
    for part in re.split(r"\s*\+\s*", expr.strip()):
        lit = re.fullmatch(r"(['\"`])(.*)\1", part)
        parts.append(lit.group(2) if lit else "{}")
    return "".join(parts)


_EVENT_ACTION = {"click": "click", "dblclick": "double-click", "change": "change the value",
                 "keyup": "type text", "keydown": "type text", "keypress": "type text", "input": "type text",
                 "submit": "submit", "blur": "leave the field", "focus": "enter the field",
                 "focusout": "leave the field", "mouseover": "hover", "mouseenter": "hover",
                 "mouseleave": "move the pointer away"}
#: Events that are the element's own primary action (a checkbox's change is checking it).
_PRIMARY_EVENTS = {"link": {"click"}, "button": {"click"}, "summary": {"click"}, "form": {"submit"},
                   "checkbox": {"change", "click", "input"}, "radio": {"change", "click", "input"},
                   "select": {"change", "input"}, "input": {"input", "keyup", "keydown", "keypress"},
                   "textarea": {"input", "keyup", "keydown", "keypress"}}


def _primary_action(c: Component) -> str:
    kind, a = c.kind, c.attrs
    if kind == "input":
        return {"date": "pick a date", "file": "choose a file", "number": "type a number", "email": "type an email",
                "password": "type a password", "range": "move the slider", "color": "pick a colour"}.get(
            a.get("type", "text").lower(), "type text")
    return {"link": "click", "button": "click", "checkbox": "check / uncheck", "radio": "select",
            "select": "choose an option", "textarea": "type text", "form": "submit", "grid": "view rows",
            "summary": "click (expand / collapse)"}.get(kind, "")


def _call_outcomes(page: _Page, calls: list[dict]) -> list[str]:
    out = []
    for e in calls:
        for key in e["endpoints"]:
            con = page.contracts.get(key)
            if con is None:
                continue
            if con["kind"] != "REST":
                views = [f"`{_short_template(t)}`" for t in _targets_of_page_endpoint(page, key)]
                redirects = []
                for r in con["redirects"]:
                    path = r.split(":", 1)[1]
                    target = _page_of(page, path)
                    redirects.append(f"redirects to `{path}`" + (
                        " and loads page " + ", ".join(f"`{_short_template(t)}`" for t in target) if target else ""))
                if views and redirects:
                    out.append("; or ".join(redirects) + ", or shows page " + " or ".join(views)
                               + " again (e.g. with validation errors)")
                elif views:
                    out.append("loads page " + ", ".join(views)
                               + (" with the results" if e["kind"] == "form" and e["verb"] == "GET" else ""))
                elif redirects:
                    out += redirects
                else:
                    out.append(f"loads the view `{con['view'] or 'named at run time'}`")
            elif e["kind"] == "link":
                out.append(f"opens the response of `{con['endpoint']}` (a file or data, not a page)")
            else:
                out.append("calls the server and stays on this page")
        if not e["endpoints"] and e.get("url"):
            out.append(f"requests `{e['path'] or e['url']}` — {e.get('reason') or 'no handler found in the code'}")
    return out


def _effect_outcomes(page: _Page, effects: list[str], out: list[str]) -> list[str]:
    effects = [x for x in effects if not x.startswith(_SILENT)]
    asks = [x for x in effects if x.startswith("asks for confirmation")]
    out = asks + out
    for x in effects:
        if x in asks:
            continue
        m = re.match(r"navigates to `(.+?)` \((`[^`]+`)\)$", x)
        if m:
            pages = [f"`{_short_template(t)}`" for t in _page_of(page, _js_url(m.group(1)))]
            if pages and all(any(p in o for o in out if o.startswith("loads page")) for p in pages):
                continue                                    # the call already says so
            out.append(("loads page " + ", ".join(pages) + f" (`{m.group(1)}`, {m.group(2)})") if pages else x)
            continue
        out.append(x)
    return out


def _api_text(page: _Page, calls: list[dict]) -> str:
    out = []
    for e in calls:
        for key in e["endpoints"]:
            src = page.contracts.get(key, {}).get("source", "")
            out.append(_endpoint_text(key) + (f" (`{Path(src.rsplit(':', 1)[0]).name}:{src.rsplit(':', 1)[1]}`)"
                                              if ":" in src else "") + f" — {e['id']}")
        if not e["endpoints"] and e.get("url"):
            out.append(f"`{e['verb']} {e['path'] or e['url']}` — no handler found in the code ({e['id']})")
    return "; ".join(dict.fromkeys(out))


def _actions(page: _Page, c: Component) -> list[dict]:
    """One row per thing a user can do with the element: what happens on the UI and the API that action calls."""
    a, kind = c.attrs, c.kind
    own = [e for e in c.calls if not e.get("via") and e.get("url")]          # links, forms, formaction buttons
    primary_events = _PRIMARY_EVENTS.get(kind, set())
    primary_handlers = [h for h in c.handlers if h["event"] in primary_events]
    other = [h for h in c.handlers if h["event"] not in primary_events]
    rows = []

    # The element's primary action.
    out, calls, via_form = [], list(own), None
    for h in primary_handlers:
        calls += [e for e in h.get("calls", []) if e not in calls]
    toggle = a.get("data-bs-toggle") or a.get("data-toggle")
    if toggle:
        target = a.get("data-bs-target") or a.get("data-target") or a.get("href") or ""
        out.append(f"opens {toggle} `{target}` on this page" if target else f"opens a {toggle} on this page")
    if kind == "button" and c.form is not None and a.get("type", "submit").lower() == "submit" and not own:
        via_form = c.form
        out.append(f"submits form {c.form.ref}")
        out += _call_outcomes(page, [e for e in c.form.calls if e.get("url")])
    if kind == "grid":
        rows_of = a.get("__rows") or next((e.get("data") for e in c.calls if e.get("data")), "")
        out.append(f"shows one row per item of `{rows_of}`, rendered with the page")
    out += _call_outcomes(page, calls)
    out = _effect_outcomes(page, [x for h in primary_handlers for x in h["effects"]], out)
    if kind == "link" and not calls and not toggle:
        href = a.get("th:href") or a.get("href") or ""
        if href.startswith("#") and len(href) > 1:
            out.append(f"scrolls to `{href}` on this page")
        elif href and uc.normalize(href).external:
            out.append(f"opens external page `{href}`")
    if kind == "select":
        filled = next((e.get("data") for e in c.calls if e.get("data") and not e.get("url")), "")
        if filled:
            out.append(f"its options come from `{filled}`, rendered with the page")
    if kind in ("input", "select", "textarea", "checkbox", "radio") and not calls:
        if c.form is not None and c.name():
            out.append(f"nothing is sent yet — the value goes as `{c.name()}` when form {c.form.ref} is submitted")
        if c.reads and not primary_handlers:
            out.append(_used_by(page, c))
    if a.get("target") == "_blank" and out:
        out[0] += " (in a new tab)"
    if not out:
        if c.reads:
            out.append("no behaviour recognised; its id is used in " + ", ".join(f"`{r}`" for r in c.reads)
                       + " — check there")
        elif primary_handlers:
            out.append("a handler runs; it changes nothing on the page that the scan recognises")
        else:
            out.append("no behaviour found in the code")
    action = _primary_action(c) or (_EVENT_ACTION.get(primary_handlers[0]["event"], primary_handlers[0]["event"])
                                    if primary_handlers else "—")
    client = bool([x for h in primary_handlers for x in h["effects"] if not x.startswith(_SILENT)])
    option_rows = _option_rows(page, c, primary_handlers, calls) if kind == "select" else []
    if option_rows:
        rows += option_rows
    else:
        rows.append({"action": action, "outcomes": list(dict.fromkeys(out)), "calls": calls, "via_form": via_form,
                     "columns": [col for h in primary_handlers for col in h.get("columns", [])], "client": client,
                     "toggle": bool(toggle)})

    # Pressing Enter in a form's text field submits the form.
    if kind == "input" and c.form is not None and a.get("type", "text").lower() not in (
            "checkbox", "radio", "file", "range", "color"):
        form_calls = [e for e in c.form.calls if e.get("url")]
        rows.append({"action": "press Enter", "calls": [], "via_form": c.form, "columns": [], "client": False,
                     "outcomes": [f"the same result as {c.form.ref}" if form_calls else ""]})

    # Every other event a script listens for, one row each.
    by_action: dict[str, list] = {}
    for h in other:
        by_action.setdefault(_EVENT_ACTION.get(h["event"], h["event"]), []).append(h)
    for action, handlers in by_action.items():
        calls = []
        for h in handlers:
            calls += [e for e in h.get("calls", []) if e not in calls]
        out = _effect_outcomes(page, [x for h in handlers for x in h["effects"]], _call_outcomes(page, calls))
        rows.append({"action": action, "calls": calls, "via_form": None,
                     "client": bool([x for h in handlers for x in h["effects"] if not x.startswith(_SILENT)]),
                     "columns": [col for h in handlers for col in h.get("columns", [])],
                     "outcomes": list(dict.fromkeys(out)) or ["a handler runs; it changes nothing on the page that "
                                                              "the scan recognises"]})
    for row in rows:
        _label(page, row)
    return rows


def _used_by(page: _Page, c: Component) -> str:
    """`the value is used by `filterJobs()` (`job_list.js:39`) when C1 type text, C3 check / uncheck`."""
    where = ", ".join(f"`{r}`" for r in c.reads)
    spots = [(r.rsplit(":", 1)[0], int(r.rsplit(":", 1)[1])) for r in c.reads if r.rsplit(":", 1)[-1].isdigit()]
    runs = []
    for other in page.components:
        for h in other.handlers:
            inside = any(Path(rel).name == f and a <= line <= b for f, line in spots for rel, a, b in h["spans"])
            if inside or set(h.get("functions", [])) & set(c.read_by):
                action = _EVENT_ACTION.get(h["event"], h["event"])
                if h["event"] in _PRIMARY_EVENTS.get(other.kind, set()):
                    action = _primary_action(other) or action
                runs.append(f"{other.ref} {action}")
    if not c.read_by and not runs:
        return f"the value is read by the script at {where}"
    names = ", ".join(f"`{n}()`" for n in c.read_by) or "the script"
    return f"the value is used by {names} ({where})" + (" when " + ", ".join(dict.fromkeys(runs)) if runs else "")


def _option_rows(page: _Page, c: Component, handlers: list, calls: list) -> list[dict]:
    """A select whose handler switches the grid between column sets by the chosen value: one row per option."""
    sets = [st for h in handlers for st in h.get("sets", []) if st["branch"]]
    if not sets or not c.options:
        return []

    def picks(st, value) -> bool:
        b = st["branch"]
        if b["case"] is not None:
            return b["case"] == value
        return not b["negate"] and bool(re.search(r"(['\"`])" + re.escape(value) + r"\1", b["test"]))

    matched = {v: next((st for st in sets if picks(st, v)), None) for v, _ in c.options}
    others = [st for st in sets if not any(st is m for m in matched.values())
              and (st["branch"]["negate"] or st["branch"]["case"] is None and not re.search(r"['\"`]", st["branch"]["test"]))]
    rows = []
    grid = next((m.group(1) for h in handlers for x in h["effects"]
                 for m in [re.search(r"grid `([^`]+)`", x)] if m), "the grid")
    for value, text in c.options:
        st = matched[value] or (others[0] if len(others) == 1 else None)
        label = text or value
        if st is None:
            rows.append({"action": f"choose \"{label}\"", "calls": calls, "via_form": None, "columns": [],
                         "client": False, "outcomes": ["no view of its own found in the code"]})
            continue
        rows.append({"action": f"choose \"{label}\"", "calls": calls, "via_form": None, "client": True,
                     "columns": [dict(col, condition="", at=st["at"]) for col in st["columns"]],
                     "outcomes": [f"switches `{grid}` to the \"{label}\" columns: "
                                  + ", ".join(col["title"] or f"`{col['field']}`" for col in st["columns"])
                                  + f" (`{st['at']}`)"]})
    return rows


def _label(page: _Page, row: dict) -> None:
    """Say first what kind of thing the action does, then the detail."""
    calls = [e for e in (row["via_form"].calls if row["via_form"] is not None else row["calls"]) if e.get("url")]
    kinds = {(page.contracts.get(k) or {}).get("kind") for e in calls for k in e["endpoints"]}
    outs = row["outcomes"]
    navigates = any(o.startswith(("loads page", "navigates to", "redirects to")) or " → page " in o for o in outs)
    if row["via_form"] is not None:
        label = f"Submits form {row['via_form'].ref}"
        outs = [o for o in outs if not o.startswith("submits form")]
    elif kinds - {"REST", None}:
        label = "Loads a page"
    elif "REST" in kinds:
        label = "Calls the server; stays on this page"
    elif any(not e["endpoints"] for e in calls):
        label = "Requests a URL the code does not serve"
    elif navigates:
        label = "Loads a page"
    elif row.get("toggle"):
        label = "Opens a dialog or panel (no server call)"
    elif any(o.startswith("scrolls to") for o in outs):
        label = "Moves within this page (no server call)"
    elif any(o.startswith("opens external page") for o in outs):
        label = "Opens an external page"
    elif row.get("client"):
        label = "Changes this page only (no server call)"
    elif any("goes as `" in o for o in outs):
        label = "Nothing happens yet"
    elif any(o.startswith("shows one row per item") for o in outs):
        label = "Display only"
    elif any(o.startswith(("the value is read by the script", "the value is used by")) for o in outs):
        label = "No action of its own"
    else:
        label = ""
    details = [o.replace("nothing is sent yet — ", "") for o in outs
               if o and o != "calls the server and stays on this page"]
    if label == "Loads a page":
        details = [d[len("loads page "):] if d.startswith("loads page ") else d for d in details]
    elif label.startswith("Moves within this page"):
        details = [d.replace(" on this page", "") for d in details]
    asks = [d for d in details if d.startswith("asks for confirmation")]
    details = [d for d in details if d not in asks] + [f"first {d}" for d in asks]
    row["outcomes"] = [f"{label}: " + "; ".join(details) if label and details else label or "; ".join(details)]
    row["no_call"] = not calls


def _row_api(page: _Page, row: dict) -> str:
    if row["via_form"] is not None:
        api = _api_text(page, [e for e in row["via_form"].calls if e.get("url")])
        return f"via form {row['via_form'].ref}: {api}" if api else "none"
    api = _api_text(page, row["calls"])
    if api:
        return api
    return "none — handled in the browser" if row.get("client") or row.get("toggle") else "none"


def _conditions(c: Component) -> list[str]:
    a, out = c.attrs, list(c.conditions)
    for k in _STATE_ATTRS:
        if k in a and k not in ("required",):
            out.append(k if not a[k] or a[k] == k else f"{k}={a[k]}")
        for p in (f"th:{k}", f"data-th-{k}"):
            if a.get(p):
                out.append(f"{k} when `{a[p]}`")
    for p in ("th:classappend", "th:class", "th:styleappend"):
        if a.get(p) and re.search(r"\$\{|\*\{|\?", a[p]):
            out.append(f"styled by `{a[p]}`")
    checks = [k if not a[k] else f"{k}={a[k]}" for k in _CHECKS if k in a]
    ty = a.get("type", "").lower()
    if ty in ("email", "number", "date", "url", "tel", "file", "datetime-local") and c.kind == "input":
        checks.insert(0, f"type={ty}")
    if checks:
        out.append("client checks: " + ", ".join(checks))
    return list(dict.fromkeys(out))


def _cell(text: str) -> str:
    return uc._cell(text)


def _field_rows(rows: list) -> list[str]:
    return [f"| `{_cell(p)}` | {_cell(t)} | {_cell(k) or '—'} |" for p, t, k in rows]


def _response_field(page: _Page, calls: list[dict], field: str) -> str:
    """`name` → `[].name`: the response field of the action's call that a grid column shows."""
    paths = []
    for e in calls:
        for key in e["endpoints"]:
            con = page.contracts.get(key) or {}
            if con.get("kind") == "REST":
                paths += [p for p, _, _ in con.get("response", []) if p == field or p.endswith("." + field)]
    if paths:
        return f"`{min(paths, key=len)}`"
    return f"`{field}`" + (" (not in the response contract)" if calls else "")


def _ref(key: str) -> str:
    verb, path, _ = key.split(" ", 2)
    return f"Endpoint Contracts → `{verb} {path}`"


def _detail(page: _Page, c: Component, printed: dict | None = None) -> list[str]:
    """Under the table: where the element comes from, when it is shown, its script handlers, its form
    fields or grid columns, and the calls its actions make — each call's request and response fields are
    printed once, under Endpoint Contracts, and referred to here."""
    lines: list[str] = []
    rows = _actions(page, c)
    if c.origin:
        lines.append(f"- From: `{_short_template(c.origin)}` (included in this page)")
    conds = _conditions(c)
    if conds:
        lines.append("- Shown / enabled: " + "; ".join(conds))
    for h in c.handlers:
        lines.append(f"- Script on {h['event']}: {h['how']}")
    when: dict[int, list] = {}
    for row in rows:
        for e in row["calls"]:
            when.setdefault(id(e), []).append(row["action"])
    for e in c.calls:
        for key in e["endpoints"]:
            sends = list(dict.fromkeys(e.get("sends", []) + [f"{q} (query)" for q in e.get("query", [])]))
            lines.append(f"- Calls {_endpoint_text(key)} ({e['id']})"
                         + (" when the user: " + ", ".join(dict.fromkeys(when[id(e)])) if when.get(id(e)) else "")
                         + ("; sends " + ", ".join(f"`{x}`" for x in sends) if sends else "")
                         + f". Request and response fields: {_ref(key)}.")
    if c.kind == "form" and c.calls and c.calls[0].get("fields"):
        lines += ["", "| Form field | Input | Client-side checks |", "|---|---|---|"]
        lines += [f"| `{_cell(n)}` | {_cell(t)} | {_cell(k) or '—'} |" for n, t, k in c.calls[0]["fields"]]
        keys = [k for e in c.calls for k in e["endpoints"]]
        if keys:
            lines += ["", "Server-side types and constraints of these fields: "
                      + "; ".join(dict.fromkeys(_ref(k) for k in keys)) + "."]
    if c.kind == "grid" and c.calls and c.calls[0].get("columns"):
        lines += ["", "| Column | Value shown |", "|---|---|"]
        lines += [f"| {_cell(h) or '—'} | {('`' + _cell(v) + '`') if v else '—'} |" for h, v in c.calls[0]["columns"]]
    printed = {} if printed is None else printed
    for row in rows:
        if not row.get("columns"):
            continue
        source = row["calls"] or [e for e in page.page_calls if e.get("url")]   # columns of data already loaded
        table = [f"| {_cell(col['title']) or '—'} | {_response_field(page, source, col['field']) if col['field'] else '—'} | "
                 f"{_cell(col['condition']) or 'always'} (`{col['at']}`) |" for col in row["columns"]]
        key = "\n".join(table)
        if key in printed:
            lines += ["", f"Grid columns after {row['action']}: the same as {printed[key]}."]
            continue
        printed[key] = f"{c.ref} {row['action']}"
        lines += ["", f"Grid columns after {row['action']}:", "", "| Column | Response field | Shown |",
                  "|---|---|---|"] + table
    return lines


def covered(pages: list[_Page]) -> dict[str, str]:
    """{template file: the page section that describes its elements} — for the UI-to-Backend Contracts,
    which then refers to that section instead of printing the same form fields and grid columns again."""
    out: dict[str, str] = {}
    for p in pages:
        for f in p.files:
            out.setdefault(f, _short_template(p.rel))
    return out


def to_markdown(pages: list[_Page]) -> str:
    if not pages:
        return ""
    total = sum(len(p.components) for p in pages)
    lines = [HEADING, "",
             "_Read from the templates, their fragments and layouts, the application's scripts they load and the "
             "controller code by the pipeline — not generated by an agent. Every interactive element of every page "
             "is listed, including those that never call the server, with one row per action a user can take on it "
             "(`C6a`, `C6b`… when there are several). **User action**: the action. **What happens on the UI**: what "
             "that action does — the page that loads, the dialog that opens, the elements the script updates or "
             "shows, the message shown — read from the code. **API called by this action**: the endpoint and "
             "controller method that this action — and only this action — calls (`UI-nnn` as in the UI-to-Backend "
             "Contracts), or none. Request and response fields are printed once, under Endpoint Contracts; the "
             "details below each table refer to them. Third-party plugin scripts are not read as the page's "
             "behaviour._", "",
             f"**{total} interactive element(s) on {len(pages)} page(s).**", ""]
    for page in pages:
        lines += [f"### Page `{_short_template(page.rel)}`", "", f"- Template: `{page.rel}`"]
        for e in page.loaded_by:
            key = f"{e['verb']} {e['path']} {e['handler']}"
            con = page.contracts.get(key, {})
            params = ", ".join(f"`{p['name']}`" for p in con.get("params", []))
            model = ", ".join(f"`{k}`" for k, _, _ in con.get("model", []))
            lines.append(f"- Rendered by: {_endpoint_text(key)}" + (f"; parameters {params}" if params else "")
                         + (f"; page data {model}" if model else "") + f" — fields: {_ref(key)}")
        if not page.loaded_by:
            lines.append("- Rendered by: no handler names this template as its view")
        if page.includes:
            lines.append("- Fragments and layouts: " + ", ".join(f"`{_short_template(i)}`" for i in page.includes))
        if page.scripts:
            lines.append("- Scripts: " + ", ".join(f"`{s}`" + (" (third-party, not read)" if is_library(s) else "")
                                                   for s in page.scripts))
        for e in page.page_calls:
            target = "; ".join(_endpoint_text(k) for k in e["endpoints"]) or \
                f"`{e['verb']} {e['path'] or e['url']}` — no handler found"
            lines.append(f"- {e['event'].capitalize() if e['event'] else 'On load'}: {target} ({e['id']})")
        lines.append("")
        if page.components:
            lines += ["| # | Element id | Element | User action | What happens on the UI | API called by this action |",
                      "|---|---|---|---|---|---|"]
            for c in page.components:
                rows = _actions(page, c)
                for n, row in enumerate(rows):
                    ref = c.ref + ("abcdefghijklmnopqrstuvwxyz"[n] if len(rows) > 1 and n < 26 else "")
                    lines.append(f"| {ref} | {c.locator()} | {_cell(c.label())} | {_cell(row['action'])} | "
                                 f"{_cell('; '.join(row['outcomes']))} | {_cell(_row_api(page, row))} |")
            lines.append("")
        else:
            lines += ["No interactive elements in the markup.", ""]
        printed: dict = {}
        details = [(c, _detail(page, c, printed)) for c in page.components]
        details = [(c, d) for c, d in details if d]
        if details:
            lines += ["#### Element details and data fields", ""]
            for c, block in details:
                ident = c.locator().strip("`") if c.attrs.get("id") else c.locator()
                lines += [f"**{c.ref} · {ident} · {_cell(c.label())}**", ""] + block + [""]
        if page.orphans:
            lines += ["#### Script handlers whose element is not in this page's markup", "",
                      "_Bound by an application script this page loads to a selector no element of any page "
                      "matches — the element is probably built at run time._", "",
                      "| Selector | Event | Bound by | What happens on the UI | API called |", "|---|---|---|---|---|"]
            for sel, event, via, effects, calls in page.orphans:
                api = "; ".join(_endpoint_text(k) + f" ({e['id']})" for e in calls for k in e["endpoints"]) or "none"
                shown = [x for x in effects if not x.startswith(_SILENT)]
                lines.append(f"| `{_cell(sel)}` | {event} | {_cell(via)} | {_cell('; '.join(shown)) or '—'} | "
                             f"{_cell(api)} |")
            lines.append("")
    return "\n".join(lines).rstrip()
