"""
UI Pages: every page of the repository's UI, page by page, with all of its HTML
elements, every interactive element, and the trace of each interaction to the
backend — the "UI_PAGES.md" deliverable (document id `ui_pages`).

It brings together, per page, what the pipeline already computes —
`ui_pages` (each server-rendered page's interactive components: the action a
user takes, what happens on the UI, the API that action calls) and
`ui_contracts` (every control's request, matched to its handler and contract)
— and adds the page's full element inventory, the kind of call each
interaction makes, the handler's request and response fields printed in place,
the control's purpose and the evidence that traces it further down.

No model is involved in what is listed. The pages, the elements and the calls
come from the code:

- pages: the templates and static pages the UI scan read (`ui_contracts.scan`,
  "pages"), and the front-end components a router names or that hold screens of
  their own (React / Vue / Angular). Fragments and layouts are listed once, at
  the end, and each page names the ones it includes;
- elements: every element of the page's markup that a user sees or uses
  (headings, forms, fields, buttons, links, tables, images, dialogs …), read
  from the template, JSP or JSX itself, with the attributes that decide its
  behaviour (validation, visibility, access, the action it is wired to);
- interactions: the UI scan's controls (`UI-nnn`) — what triggers each one,
  the request it makes (Ajax / fetch / form submission / navigation / page
  load), the endpoint URL, the handler that serves it, that handler's computed
  contract (parameters, body, response, errors, access rule) — and, when given,
  the Enterprise Architect's description of its purpose and the evidence that
  traces it further down (services, repositories, tables).

Pages are ordered by route (the URL a user opens), then pages with no route by
file; the order is the same as the UI Screens document's, so both can be read
side by side.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from .dependency_graph import EXCLUDED_DIRS

TITLE = "UI Pages: Elements, Interactions & Backend Traces"
MAX_FILE_BYTES = 1_000_000

_TEMPLATE_SUFFIXES = (".html", ".htm", ".jsp", ".jspx", ".jspf", ".xhtml", ".ftl", ".vm", ".vue")
_COMPONENT_SUFFIXES = (".jsx", ".tsx", ".vue", ".js", ".ts")
_FRAGMENT_PATH = re.compile(r"(?:^|/)(?:fragments?|layouts?|partials?|includes?|common|shared|mail|emails?|tags)/",
                            re.I)
_PAGE_DIRS = re.compile(r"(?:^|/)(?:pages|views|screens|routes|containers)/", re.I)

#: Elements listed in a page's inventory: what a user sees or uses.
_INTERACTIVE = {"a", "button", "input", "select", "textarea", "form", "details", "summary", "option"}
_SHOWN = {"h1", "h2", "h3", "h4", "h5", "h6", "table", "img", "nav", "dialog", "iframe", "label", "fieldset",
          "legend", "ul", "ol", "video", "audio", "canvas", "svg", "header", "footer", "main", "section", "aside",
          "th", "title"}
#: Attributes that decide what an element does, shows or accepts.
_NOTED_ATTRS = re.compile(
    r"^(?:type|name|value|href|src|action|method|required|disabled|readonly|checked|multiple|min|max|minlength|"
    r"maxlength|pattern|step|accept|placeholder|for|role|target|"
    r"on\w+|data-(?:bs-|)(?:toggle|target|dismiss|url|action|id)|"
    r"th:(?:href|src|action|if|unless|each|field|object|disabled|onclick|value|text|replace|insert|include)|"
    r"data-th-\w+|sec:authorize|layout:\w+|"
    r"v-(?:if|show|for|model|on:\w+|bind:\w+)|@\w+|:\w+|"
    r"ng-(?:click|submit|change|model|if|show|repeat|href)|\(\w+\)|\[\w+\]|\*ng\w+|formcontrolname|routerlink|"
    r"onclick|onsubmit|onchange|to|key)$", re.I)
_TEXT_TAGS = {"a", "button", "label", "h1", "h2", "h3", "h4", "h5", "h6", "option", "summary", "legend", "th",
              "title", "textarea"}


def _cell(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).replace("|", "\\|").strip()


def _short(text: str, n: int = 60) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _read(path: Path) -> str:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ── element inventory ───────────────────────────────────────────────────────

class _Markup(HTMLParser):
    """Every listed element of an HTML-like template, with its line and text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self.open: list[dict] = []
        self.labels: dict[str, str] = {}
        self.forms = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        if tag in ("form", "form:form", "h:form"):
            self.forms += 1
        if tag not in _INTERACTIVE and tag not in _SHOWN and not _handler_attrs(a):
            return
        row = {"tag": tag, "attrs": a, "line": self.getpos()[0], "text": "", "in_form": self.forms > 0}
        self.rows.append(row)
        if tag in _TEXT_TAGS:
            self.open.append(row)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.open and self.open[-1]["tag"] == tag.lower() and tag.lower() in _TEXT_TAGS:
            self.open.pop()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("form", "form:form", "h:form") and self.forms:
            self.forms -= 1
        for i in range(len(self.open) - 1, -1, -1):
            if self.open[i]["tag"] == tag:
                row = self.open.pop(i)
                if tag == "label" and row["attrs"].get("for"):
                    self.labels[row["attrs"]["for"]] = row["text"]
                break

    def handle_data(self, data):
        for row in self.open:
            if len(row["text"]) < 120:
                row["text"] = (row["text"] + " " + data).strip()


_JSX_TAG = re.compile(r"<([a-z][a-z0-9-]*)\b((?:[^<>{}]|\{(?:[^{}]|\{[^{}]*\})*\})*?)(/?)>", re.S)
_JSX_ATTR = re.compile(r"([\w:@.-]+)(?:\s*=\s*(\"[^\"]*\"|'[^']*'|\{(?:[^{}]|\{[^{}]*\})*\}))?")


def _jsx_rows(text: str) -> tuple[list[dict], dict[str, str]]:
    """Listed elements of JSX/TSX markup (lower-case tags are HTML elements)."""
    rows, labels = [], {}
    for m in _JSX_TAG.finditer(text):
        tag = m.group(1)
        attrs = {}
        for am in _JSX_ATTR.finditer(m.group(2)):
            key, value = am.group(1), am.group(2) or ""
            if key in ("/",):
                continue
            attrs[key.lower() if not key.startswith("on") else key] = value.strip("\"'")
        attrs = {("class" if k == "classname" else "for" if k == "htmlfor" else k): v for k, v in attrs.items()}
        if tag not in _INTERACTIVE and tag not in _SHOWN and not _handler_attrs(attrs):
            continue
        body = ""
        if not m.group(3) and tag in _TEXT_TAGS:
            close = text.find(f"</{tag}>", m.end())
            if close != -1:
                inner = text[m.end():close]
                body = re.sub(r"</[\w.-]+>", " ", _JSX_TAG.sub(" ", inner))
                body = re.sub(r"\{[^{}]*\}", lambda x: x.group(0) if len(x.group(0)) < 40 else "{…}", body)
        row = {"tag": tag, "attrs": attrs, "line": text.count("\n", 0, m.start()) + 1, "text": _short(body, 120),
               "in_form": None}
        rows.append(row)
        if tag == "label" and attrs.get("for"):
            labels[attrs["for"]] = row["text"]
    return rows, labels


def _handler_attrs(attrs: dict) -> list[str]:
    return [k for k in attrs if re.match(r"^(?:on[a-z]+|on[A-Z]\w*|th:on\w+|data-th-on\w+|@\w+|v-on:\w+|"
                                         r"ng-(?:click|submit|change)|\(\w+\))$", k)]


def _markup_of(text: str, suffix: str) -> str:
    if suffix == ".vue":
        m = re.search(r"<template[^>]*>(.*)</template>", text, re.S | re.I)
        return m.group(1) if m else ""
    if suffix in (".jsp", ".jspx", ".jspf"):
        # Scriptlets and comments carry no markup; their line breaks are kept so lines stay true.
        return re.sub(r"<%.*?%>", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return text


def inventory(workspace_dir: str, rel: str) -> tuple[list[dict], dict[str, str]]:
    """(elements of the page in source order, {element id: label text})."""
    path = Path(workspace_dir) / rel
    text = _read(path)
    if not text:
        return [], {}
    suffix = path.suffix.lower()
    if suffix in (".jsx", ".tsx", ".js", ".ts"):
        return _jsx_rows(text)
    parser = _Markup()
    try:
        parser.feed(_markup_of(text, suffix))
        parser.close()
    except Exception:                                     # noqa: BLE001 — a page we cannot parse is listed empty
        pass
    return parser.rows, parser.labels


def _identity(a: dict) -> str:
    parts = []
    if a.get("id"):
        parts.append(f"#{a['id']}")
    for key in ("name", "th:field", "formcontrolname", "v-model", "ng-model"):
        if a.get(key):
            parts.append(f"{key}={a[key]}")
            break
    if not parts and a.get("class"):
        parts.append("." + a["class"].split()[0])
    return " ".join(parts)


def _element_name(row: dict) -> str:
    a = row["attrs"]
    if row["tag"] == "input":
        return f"input[{a.get('type') or 'text'}]"
    if row["tag"] == "button":
        return f"button[{a['type']}]" if a.get("type") else ("button[submit]" if row.get("in_form") else "button")
    return row["tag"]


def _label(row: dict, labels: dict[str, str]) -> str:
    a = row["attrs"]
    for text in (row["text"], labels.get(a.get("id", ""), ""), a.get("aria-label", ""), a.get("title", ""),
                 a.get("placeholder", ""), a.get("alt", ""), a.get("value", "") if row["tag"] == "input" else ""):
        if text and text.strip():
            return _short(text, 60)
    return ""


def _attributes(row: dict) -> str:
    skip = {"id", "class", "name", "style"}
    out = []
    for k, v in row["attrs"].items():
        if k in skip or not _NOTED_ATTRS.match(k):
            continue
        if k == "type" and row["tag"] in ("input", "button"):
            continue
        out.append(f"{k}" + (f"=\"{_short(v, 50)}\"" if v != "" else ""))
    return ", ".join(out)


def _client_side(row: dict) -> str:
    """What an element does in the browser when no backend call is tied to it."""
    a, tag = row["attrs"], row["tag"]
    handlers = _handler_attrs(a)
    if handlers:
        k = handlers[0]
        return f"runs `{_short(a[k], 50)}` on {re.sub(r'^(?:on|th:on|data-th-on|@|v-on:|ng-)|[()]', '', k)}"
    toggle = a.get("data-bs-toggle") or a.get("data-toggle")
    if toggle:
        target = a.get("data-bs-target") or a.get("data-target") or a.get("href", "")
        return f"opens {toggle} `{target}` (in the browser, no request)"
    if a.get("data-bs-dismiss") or a.get("data-dismiss"):
        return "closes the dialog (in the browser, no request)"
    if tag == "a":
        href = a.get("th:href") or a.get("href") or a.get("to") or a.get("routerlink") or a.get("ng-href", "")
        if href.startswith("#") or not href:
            return "in-page link (no request)" if href else ""
        if href.startswith(("mailto:", "tel:")):
            return f"opens `{_short(href, 50)}`"
        return f"navigates to `{_short(href, 60)}`"
    if tag == "button" and (a.get("type") or "submit") == "submit" and row.get("in_form") is not False:
        return "submits its form"
    if tag in ("input", "select", "textarea"):
        return "value sent with its form" if (a.get("name") or a.get("th:field")) else "input (read by script)"
    return ""


# ── pages ───────────────────────────────────────────────────────────────────

_ROUTE_JSX = re.compile(r"<Route\b[^>]*?\bpath\s*=\s*[\"'{]+([^\"'}]+)[\"'}]+[^>]*?"
                        r"(?:element\s*=\s*\{\s*<\s*([A-Z]\w*)|component\s*=\s*\{\s*([A-Z]\w*))", re.S)
_ROUTE_OBJ = re.compile(r"\bpath\s*:\s*[\"']([^\"']*)[\"'][^{}]*?\b(?:component|element)\s*:\s*<?\s*"
                        r"(?:\(\)\s*=>\s*import\(\s*[\"']([^\"']+)[\"']\s*\)|([A-Z]\w*))", re.S)
_IMPORT = re.compile(r"import\s+(?:\{?\s*([A-Z]\w*)[^;]*?)\s+from\s+[\"']([^\"']+)[\"']")


def _resolve(workspace: Path, base: str, spec: str) -> str:
    if not spec.startswith("."):
        return ""
    target = (PurePosixPath(base).parent / spec)
    parts = []
    for p in target.parts:
        if p == "..":
            if parts:
                parts.pop()
        elif p != ".":
            parts.append(p)
    stem = "/".join(parts)
    for cand in [stem] + [stem + s for s in (".jsx", ".tsx", ".js", ".ts", ".vue")] + \
                [f"{stem}/index{s}" for s in (".jsx", ".tsx", ".js", ".ts", ".vue")]:
        if (workspace / cand).is_file():
            return cand
    return ""


def _walk(workspace: Path):
    import os
    for dirpath, dirnames, filenames in os.walk(workspace, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            path = Path(dirpath, name)
            if not path.is_symlink():
                yield path.relative_to(workspace).as_posix()


def routes(workspace_dir: str, files: list[str] | None = None) -> dict[str, list[str]]:
    """{component file: [route paths]} from React Router / Vue Router / Angular route tables."""
    workspace = Path(workspace_dir)
    files = files if files is not None else list(_walk(workspace))
    by_stem: dict[str, str] = {}
    for f in files:
        if f.endswith(_COMPONENT_SUFFIXES):
            by_stem.setdefault(PurePosixPath(f).stem, f)
    out: dict[str, list[str]] = {}
    for rel in files:
        if not rel.endswith(_COMPONENT_SUFFIXES) or "/test" in rel or ".spec." in rel or ".test." in rel:
            continue
        text = _read(workspace / rel)
        if "path" not in text or ("Route" not in text and "routes" not in text.lower()):
            continue
        imports = {name: spec for name, spec in _IMPORT.findall(text)}
        found = [(m.group(1), m.group(2) or m.group(3), "") for m in _ROUTE_JSX.finditer(text)]
        found += [(m.group(1), m.group(3) or "", m.group(2) or "") for m in _ROUTE_OBJ.finditer(text)]
        for path, comp, lazy in found:
            target = _resolve(workspace, rel, lazy) if lazy else _resolve(workspace, rel, imports.get(comp, ""))
            if not target and comp:
                target = by_stem.get(comp, "")
            if target:
                route = "/" + path.strip().lstrip("/") if path.strip() not in ("", "*", "**") else path.strip() or "/"
                if route not in out.setdefault(target, []):
                    out[target].append(route)
    return out


def _is_fragment(rel: str, text: str) -> bool:
    if _FRAGMENT_PATH.search(rel):
        return True
    if rel.endswith(".jspf"):
        return True
    if rel.endswith((".html", ".htm", ".xhtml")):
        if "layout:fragment" in text and not re.search(r"layout:decorat", text):
            return True                                   # a layout
        if not re.search(r"<html|<!doctype|<body|layout:decorat", text, re.I):
            return True                                   # a fragment file
    return False


def _includes(text: str, fragments: list[str]) -> list[str]:
    """Fragment and layout files a page includes (Thymeleaf, layout dialect, JSP, Freemarker, Vue/React imports)."""
    names = set()
    for m in re.finditer(r"(?:th:(?:replace|insert|include)|data-th-(?:replace|insert|include)|layout:decorate|"
                         r"layout:decorator)\s*=\s*[\"']~?\{?\s*([\w/.-]+)", text):
        names.add(m.group(1))
    for m in re.finditer(r"<jsp:include\s+page\s*=\s*[\"']([^\"']+)|<%@\s*include\s+file\s*=\s*[\"']([^\"']+)|"
                         r"<c:import\s+url\s*=\s*[\"']([^\"']+)|<#include\s+[\"']([^\"']+)", text):
        names.add(next(g for g in m.groups() if g))
    out = []
    for f in fragments:
        stem = re.sub(r"\.\w+$", "", f)
        for n in names:
            n2 = re.sub(r"\.\w+$", "", n.lstrip("/"))
            if n2 and (stem.endswith("/" + n2) or stem == n2):
                out.append(f)
                break
    return out


def _route_key(page: dict) -> tuple:
    if not page["routes"]:
        return (1, page["file"])
    first = page["routes"][0].split(" ", 1)[-1]
    return (0, first.lower(), page["file"])


def build(workspace_dir: str, ui_result: dict | None) -> list[dict]:
    """The pages, in order, each with its inventory and its interactions."""
    ui_result = ui_result or {}
    workspace = Path(workspace_dir)
    screens = {s["file"]: s for s in ui_result.get("screens", [])}
    templates = [p["file"] for p in ui_result.get("pages", [])]
    served = {p["file"]: p.get("served_by", []) for p in ui_result.get("pages", [])}
    files = list(_walk(workspace)) if workspace_dir else []
    route_map = routes(workspace_dir, files) if workspace_dir else {}

    candidates: dict[str, dict] = {}
    for rel in templates:
        text = _read(workspace / rel)
        candidates[rel] = {"file": rel, "kind": _kind(rel), "routes": list(served.get(rel, [])), "text": text}
    for rel, s in screens.items():
        if rel in candidates or s.get("used_by"):
            continue
        if rel.endswith(_COMPONENT_SUFFIXES) or rel.endswith(_TEMPLATE_SUFFIXES):
            candidates[rel] = {"file": rel, "kind": _kind(rel), "routes": [], "text": _read(workspace / rel)}
    for rel, paths in route_map.items():
        candidates.setdefault(rel, {"file": rel, "kind": _kind(rel), "routes": [], "text": _read(workspace / rel)})
        candidates[rel]["routes"] += [f"route {p}" for p in paths if f"route {p}" not in candidates[rel]["routes"]]
    if workspace_dir:
        for rel in files:
            if rel in candidates or not rel.endswith((".jsx", ".tsx", ".vue")) or not _PAGE_DIRS.search(rel):
                continue
            if re.search(r"\.(?:test|spec|stories)\.", rel):
                continue
            candidates[rel] = {"file": rel, "kind": _kind(rel), "routes": [], "text": _read(workspace / rel)}

    fragments = sorted(r for r, c in candidates.items() if _is_fragment(r, c["text"]))
    # Script files a page loads: their controls belong to that page, when the page holds the element they bind.
    scripts_of: dict[str, list[str]] = {}
    for rel, s in screens.items():
        for page in s.get("used_by", []):
            scripts_of.setdefault(page, []).append(rel)

    pages = []
    for rel, c in candidates.items():
        rows, labels = inventory(workspace_dir, rel) if workspace_dir else ([], {})
        own = list(screens.get(rel, {}).get("elements", []))
        script_elements = []
        for script in scripts_of.get(rel, []):
            sharers = [p for p in screens[script].get("used_by", [])]
            for e in screens[script]["elements"]:
                if len(sharers) > 1 and not _on_page(e, c["text"]) and any(
                        _on_page(e, candidates.get(p, {}).get("text", "")) for p in sharers if p != rel):
                    continue                              # bound to an element another page holds
                script_elements.append({**e, "from_script": script})
        pages.append({
            "file": rel, "kind": c["kind"], "routes": c["routes"], "title": _title(rows, rel),
            "fragment": rel in fragments, "includes": _includes(c["text"], [f for f in fragments if f != rel]),
            "scripts": scripts_of.get(rel, []), "elements": rows, "labels": labels,
            "interactions": own + script_elements,
        })
    pages.sort(key=lambda p: (p["fragment"], *_route_key(p)))
    n = 0
    for p in pages:
        if not p["fragment"]:
            n += 1
            p["id"] = f"PG-{n:02d}"
    k = 0
    for p in pages:
        if p["fragment"]:
            k += 1
            p["id"] = f"FR-{k:02d}"
    return pages


def _on_page(element: dict, text: str) -> bool:
    label = element.get("label", "")
    m = re.search(r"#([\w-]+)", label)
    if m:
        return bool(re.search(rf"\bid\s*=\s*[\"']{re.escape(m.group(1))}[\"']", text))
    m = re.search(r"\.([\w-]+)", label)
    if m:
        return m.group(1) in text
    return True


def _kind(rel: str) -> str:
    suffix = PurePosixPath(rel).suffix.lower()
    return {".jsp": "JSP page", ".jspx": "JSP page", ".jspf": "JSP fragment", ".ftl": "FreeMarker template",
            ".vm": "Velocity template", ".xhtml": "JSF / Facelets page", ".vue": "Vue component",
            ".jsx": "React component", ".tsx": "React component", ".js": "script", ".ts": "script"}.get(
        suffix, "server template" if "/templates/" in rel else "HTML page")


def _title(rows: list[dict], rel: str) -> str:
    for tag in ("title", "h1", "h2"):
        for r in rows:
            if r["tag"] == tag and r["text"] and "{" not in r["text"] and not any(
                    k in r["attrs"] for k in ("th:text", "th:utext", "data-th-text", "v-text", "v-html")):
                return _short(r["text"], 70)
    stem = PurePosixPath(rel).stem
    return re.sub(r"[_-]+", " ", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem)).strip().capitalize()


# ── document ────────────────────────────────────────────────────────────────

def call_type(e: dict) -> str:
    client = e.get("client", "")
    kind, event = e.get("kind", ""), e.get("event", "")
    if client:
        if client == "fetch" or client.endswith(".fetch"):
            return f"Ajax — `fetch` ({'on page load' if kind == 'page load' else 'asynchronous request'})"
        if re.search(r"(?:^|\.)(?:ajax|get|post|getJSON|load|put|delete|patch|request)$", client) and \
                re.match(r"^(?:\$|jQuery)", client):
            return f"Ajax — jQuery `{client}`"
        if "axios" in client or re.match(r"^(?:api|client|http|instance|request)\b", client):
            return f"Ajax — HTTP client `{client}`"
        if "XMLHttpRequest" in client or client.endswith(".open"):
            return "Ajax — `XMLHttpRequest`"
        return f"Ajax — `{client}`"
    if kind == "grid" and e.get("url"):
        return "Display — filled in the browser from the response of the request"
    if kind == "data model":
        return "Ajax — Backbone model/collection sync"
    if kind == "form" or "submits the form" in event:
        return "HTML form submission (full page request)"
    if kind == "link" or "navigation" in event:
        return "Navigation (browser loads the page)"
    if e.get("data") or event.startswith("page load (server"):
        return "Server-rendered — the page's handler supplies the data, no request from the element"
    if e.get("url"):
        return "HTTP request from script"
    return "In the browser only — no request"


def _contract_by_key(ui_result: dict) -> dict[str, dict]:
    return {c["endpoint"]: c for c in ui_result.get("contracts", [])}


def _fields(rows, limit=25) -> str:
    items = []
    for r in rows[:limit]:
        if isinstance(r, dict):
            items.append(f"`{r.get('name')}` ({r.get('in', '')} {r.get('type', '')}"
                         + (", required" if str(r.get("required")).lower() in ("yes", "true") else "")
                         + (f", {r['constraints']}" if r.get("constraints") else "") + ")")
        else:
            name, typ, *rest = list(r) + ["", ""]
            items.append(f"`{name}` ({typ}" + (f", {rest[0]}" if rest and rest[0] else "") + ")")
    more = f" … and {len(rows) - limit} more (see openapi.yaml)" if len(rows) > limit else ""
    return "; ".join(items) + more


def computed_purpose(e: dict) -> str:
    target = f"`{e['verb']} {e['path'] or e['url']}`" if e.get("url") else ""
    handler = ", ".join(f"`{k.rsplit(' ', 1)[-1]}`" for k in e.get("endpoints", []))
    kind = e.get("kind", "")
    if kind == "page load":
        what = f"Loads data for the page when it opens, from {target}" if target else "Runs when the page opens"
    elif kind == "timer":
        what = f"Refreshes data {e['event']} from {target}" if target else f"Runs {e['event']}"
    elif kind == "form":
        what = f"Submits the form{' fields ' + ', '.join(f'`{f[0]}`' for f in e.get('fields', [])[:8]) if e.get('fields') else ''} to {target}"
    elif kind == "link":
        what = f"Takes the user to {target}" if target else "Navigation link"
    elif kind == "grid":
        what = f"Shows a table of `{e['data']}`" if e.get("data") else f"Shows a table filled from {target}" \
            if target else "Shows a table"
    elif kind == "select" and not target:
        what = f"Offers a choice from `{e['data']}`" if e.get("data") else "Offers a choice"
    else:
        what = f"On {e.get('event', 'use')}, calls {target}" if target else f"Reacts to {e.get('event', 'use')}"
    if e.get("sends") and kind != "form":
        what += f", sending {', '.join(f'`{s}`' for s in e['sends'][:8])}"
    if handler:
        what += f"; served by {handler}"
    elif e.get("url") and e.get("reason"):
        what += f" — {e['reason']}"
    return what + "."


def _purpose_text(block: str) -> str:
    """The writer's bullet for a control, without its leading id."""
    text = re.sub(r"^\s*[-*+]\s+(?:\*\*)?UI-\d{3,}(?:\*\*)?\s*[—:–-]?\s*", "", block.strip())
    return text.strip()


def _evidence_for(e: dict, evidence_lines: list[str], limit: int = 6) -> list[str]:
    keys = [e["id"]]
    for k in e.get("endpoints", []):
        handler = k.rsplit(" ", 1)[-1]
        if "." in handler:
            keys.append(handler)
    out = []
    for line in evidence_lines:
        if any(re.search(rf"(?<![\w-]){re.escape(k)}(?![\w-])", line) for k in keys):
            out.append(line.strip())
            if len(out) >= limit:
                break
    return out


def _anchor(text: str) -> str:
    return re.sub(r"[^\w\- ]", "", text.lower()).strip().replace(" ", "-")


def component_sections(markdown: str) -> dict[str, str]:
    """{template file: its section of `ui_pages.to_markdown`} — the interactive-components
    table and element details of each server-rendered page, without the page heading."""
    out: dict[str, str] = {}
    for part in re.split(r"(?m)^### Page ", markdown or "")[1:]:
        m = re.search(r"(?m)^- Template: `([^`]+)`", part)
        if not m:
            continue
        body = part.split("\n", 1)[1] if "\n" in part else ""
        body = "\n".join(l for l in body.splitlines()
                         if not re.match(r"- (?:Template|Rendered by|Fragments and layouts|Scripts):", l))
        body = re.sub(r"Endpoint Contracts → (`[^`]+`)", r"the backend trace of \1 below", body)
        out[m.group(1)] = re.sub(r"(?m)^(#{4,5}) ", lambda h: "#" + h.group(1) + " ", body).strip()
    return out


def to_markdown(pages: list[dict], ui_result: dict | None, descriptions: dict[str, str] | None = None,
                evidence_text: str | dict = "", screenshots: dict[str, list[str]] | None = None,
                project: str = "", components_md: str = "", intros: dict[str, str] | None = None) -> str:
    """The UI_PAGES.md document. `descriptions`: {UI id: the writer's description};
    `intros`: {screen file: the writer's introduction}; `screenshots`: {page file: [SCR ids]}
    from the UI Screens document; `components_md`: `ui_pages.to_markdown`'s output."""
    ui_result = ui_result or {}
    descriptions = descriptions or {}
    screenshots = screenshots or {}
    sections = component_sections(components_md)
    intros = intros or {}
    contracts = _contract_by_key(ui_result)
    if isinstance(evidence_text, dict):          # {EV id: item text}, as evidence_pack.items gives it
        ev_lines = [f"- {_short(text, 400)} ({ev})" for ev, text in evidence_text.items()]
    else:
        ev_lines = [l for l in (evidence_text or "").splitlines() if re.match(r"\s*[-*]\s", l) and "EV-" in l]
    main_pages = [p for p in pages if not p["fragment"]]
    frags = [p for p in pages if p["fragment"]]
    n_el = sum(len(p["elements"]) for p in pages)
    n_int = sum(len(p["interactions"]) for p in pages)
    ajax = sum(1 for p in pages for e in p["interactions"] if call_type(e).startswith("Ajax"))
    unmatched = ui_result.get("unmatched", [])
    lines = [f"# {TITLE}" + (f" — {project}" if project else ""), "",
             "_Computed from the repository's templates, components and scripts, page by page in route order. "
             "Every element is listed from the page source with its line; every interaction is traced from the "
             "control through the request it makes to the handler that serves it and that handler's contract. "
             "Purposes are the Enterprise Architect's descriptions where given, otherwise computed from the code "
             "(marked). Nothing here is a recommendation._", "",
             "## Summary", "",
             "| Pages | Shared fragments / layouts | HTML elements listed | Interactive elements traced | "
             "Ajax calls | Calls no handler serves | REST endpoints no UI calls |",
             "|---|---|---|---|---|---|---|",
             f"| {len(main_pages)} | {len(frags)} | {n_el} | {n_int} | {ajax} | {len(unmatched)} | "
             f"{len(ui_result.get('uncalled', []))} |", "",
             "## Page Index", "",
             "| # | Page | Route(s) | Source | Elements | Interactions | Screenshots |", "|---|---|---|---|---|---|---|"]
    for p in pages:
        shots = ", ".join(screenshots.get(p["file"], [])) or "—"
        lines.append(f"| {p['id']} | [{_cell(p['title'])}](#{_anchor(p['id'] + ' ' + p['title'])}) | "
                     f"{_cell('; '.join(p['routes'])) or '—'} | `{p['file']}` | {len(p['elements'])} | "
                     f"{len(p['interactions'])} | {shots} |")
    if not pages:
        lines += ["", "No UI pages were found in this repository."]
        return "\n".join(lines) + "\n"

    for group, title in ((main_pages, "Pages"), (frags, "Shared Fragments & Layouts")):
        if not group:
            continue
        lines += ["", f"## {title}"]
        for p in group:
            lines += _page(p, contracts, descriptions, ev_lines, screenshots, pages, sections.get(p["file"], ""),
                           intros)

    if unmatched:
        lines += ["", "## Calls No Handler Serves", "", "| Element | Call | Reason | Source |", "|---|---|---|---|"]
        for u in unmatched:
            lines.append(f"| {u['id']} {_cell(u['element'])} | `{_cell(u['call'])}` | {_cell(u['reason'])} | "
                         f"`{u['source']}` |")
    if ui_result.get("uncalled"):
        lines += ["", "## REST Endpoints No UI Control Calls", "",
                  "_Called by nothing in this repository's UI — another client, a job, or dead code "
                  "(see TECH_DEBT_AND_DEAD_CODE.md)._", ""]
        lines += [f"- `{u}`" for u in ui_result["uncalled"]]
    return "\n".join(lines).rstrip() + "\n"


def _page(p, contracts, descriptions, ev_lines, screenshots, pages, components="", intros=None) -> list[str]:
    by_file = {q["file"]: q for q in pages}
    out = ["", f"### {p['id']} {p['title']}", ""]
    intro = next((intros[f] for f in [p["file"], *p["scripts"]] if (intros or {}).get(f)), "")
    if intro:
        out += [f"_Purpose of the page:_ {_short(intro, 600)}", ""]
    out.append(f"- **Source:** `{p['file']}` ({p['kind']})")
    out.append(f"- **Route(s):** {'; '.join(f'`{r}`' for r in p['routes']) if p['routes'] else 'none found in the code'}")
    if p["includes"]:
        out.append("- **Includes:** " + ", ".join(
            f"{by_file[f]['id']} `{f}`" if f in by_file else f"`{f}`" for f in p["includes"]))
    if p["fragment"]:
        users = [q for q in pages if p["file"] in q["includes"]]
        if users:
            out.append("- **Included by:** " + ", ".join(f"{q['id']} `{q['file']}`" for q in users))
    if p["scripts"]:
        out.append("- **Scripts:** " + ", ".join(f"`{s}`" for s in p["scripts"]))
    if screenshots.get(p["file"]):
        out.append(f"- **Screenshots:** {', '.join(screenshots[p['file']])} (UI_SCREENS.md)")

    # The page's elements, in source order.
    tied = _tie(p)
    out += ["", f"#### HTML elements ({len(p['elements'])})", ""]
    if p["elements"]:
        counts: dict[str, int] = {}
        for r in p["elements"]:
            counts[_element_name(r)] = counts.get(_element_name(r), 0) + 1
        out.append("_By type:_ " + ", ".join(f"{k} × {v}" for k, v in sorted(counts.items())))
        out += ["", "| Line | Element | Id / name | Label / text | Behaviour attributes | Interaction |",
                "|---|---|---|---|---|---|"]
        for r in p["elements"]:
            ui_id = tied.get(id(r)) or _match_id(r, p["interactions"])
            action = f"{ui_id} (traced below)" if ui_id else _client_side(r)
            out.append(f"| {r['line']} | `{_element_name(r)}` | {_cell(_identity(r['attrs'])) or '—'} | "
                       f"{_cell(_label(r, p['labels'])) or '—'} | {_cell(_attributes(r)) or '—'} | "
                       f"{_cell(action) or '—'} |")
    else:
        out.append("No markup elements in this file (its screen is drawn by script, or it could not be read).")

    if components:
        out += ["", "#### Interactive components and what each action does", "", components]
    out += ["", f"#### Backend traces ({len(p['interactions'])})", ""]
    if not p["interactions"]:
        out.append("No control on this page makes a request or shows server data.")
        return out
    out += ["| Id | Element | Trigger | Call type | Request | Backend handler |", "|---|---|---|---|---|---|"]
    for e in p["interactions"]:
        req = f"`{e['verb']} {e['url']}`" if e.get("url") else "—"
        handler = "; ".join(f"`{k.rsplit(' ', 1)[-1]}`" for k in e.get("endpoints", [])) or (
            f"none — {e['reason']}" if e.get("url") and e.get("reason") else "—")
        out.append(f"| {e['id']} | {_cell(e['kind'])} {_cell(e['label'])} | {_cell(e['event'])} | "
                   f"{_cell(call_type(e))} | {_cell(req)} | {_cell(handler)} |")
    for e in p["interactions"]:
        out += _trace(e, contracts, descriptions, ev_lines)
    return out


_TAGS_OF_KIND = {"form": {"form"}, "select": {"select"}, "grid": {"table", "tbody", "ul", "ol"},
                 "link": {"a", "button"}, "button": {"button", "a", "input"}, "input": {"input", "select", "textarea"}}


def _tie(page: dict) -> dict[int, str]:
    """{id(inventory row): UI id} for controls defined in the page's own markup: the row of a fitting
    tag on the control's line, or within two lines of it."""
    out: dict[int, str] = {}
    for e in page["interactions"]:
        file, _, line = e.get("source", "").rpartition(":")
        if file != page["file"] or not line.isdigit():
            continue
        tags = _TAGS_OF_KIND.get(e["kind"], set())
        best = None
        for r in page["elements"]:
            d = abs(r["line"] - int(line))
            if d <= 2 and (not tags or r["tag"] in tags) and id(r) not in out and (best is None or d < best[0]):
                best = (d, r)
        if best:
            out[id(best[1])] = e["id"]
    return out


def _match_id(row: dict, interactions: list[dict]) -> str:
    """A control a script binds to this element by its id or class."""
    a = row["attrs"]
    for e in interactions:
        label = e.get("label", "")
        if a.get("id") and re.search(rf"#{re.escape(a['id'])}(?![\w-])", label):
            return e["id"]
    classes = (a.get("class") or "").split()
    for e in interactions:
        label = e.get("label", "")
        if e.get("from_script") and any(re.search(rf"\.{re.escape(c)}(?![\w-])", label) for c in classes):
            return e["id"]
    return ""


def _trace(e, contracts, descriptions, ev_lines) -> list[str]:
    out = ["", f"##### {e['id']} — {_cell(e['kind'])} {_cell(e['label'])}", ""]
    purpose = _purpose_text(descriptions.get(e["id"], ""))
    out.append(f"- **Purpose:** {purpose}" if purpose else f"- **Purpose:** {computed_purpose(e)} _(computed)_")
    out.append(f"- **Action:** {e['event']}" + (f" — {e['via']}" if e.get("via") else ""))
    if e.get("from_script"):
        out.append(f"- **Wired in:** `{e['source']}` (script `{e['from_script']}`)")
    else:
        out.append(f"- **Defined at:** `{e['source']}`")
    out.append(f"- **Call type:** {call_type(e)}")
    if e.get("url"):
        out.append(f"- **Endpoint URL:** `{e['verb']} {e['url']}`" + (
            f" (path `{e['path']}`)" if e.get("path") and e["path"] != e["url"] else ""))
    if e.get("fields"):
        out.append("- **Form fields:** " + "; ".join(
            f"`{f[0]}` ({f[1]}" + (f", {f[2]}" if len(f) > 2 and f[2] else "") + ")" for f in e["fields"]))
    if e.get("sends"):
        out.append("- **Sends:** " + ", ".join(f"`{s}`" for s in e["sends"]))
    if e.get("data"):
        out.append(f"- **Shows server data:** `{e['data']}`")
    if e.get("columns"):
        out.append("- **Columns:** " + ", ".join(_cell(c[0]) + (f" (`{_cell(c[1])}`)" if c[1] else "")
                                                for c in e["columns"][:20] if c[0] or c[1]))
    if e.get("client_type"):
        out.append(f"- **Response type declared on the client:** `{e['client_type']}`")
    if not e.get("endpoints"):
        if e.get("url"):
            out.append(f"- **Backend:** no handler in this repository serves this request — {e.get('reason') or 'unmatched'}")
    for key in e.get("endpoints", []):
        endpoint = " ".join(key.split(" ")[:2])
        c = contracts.get(endpoint)
        out.append(f"- **Backend handler:** `{key.rsplit(' ', 1)[-1]}` serving `{endpoint}`"
                   + (f" (`{c['source']}`, {c['kind']})" if c else ""))
        if not c:
            continue
        if c.get("params"):
            out.append(f"  - Parameters: {_fields(c['params'])}")
        if c.get("body"):
            out.append(f"  - Request body ({c.get('body_type') or c.get('body_in') or 'body'}): {_fields(c['body'])}")
        if c.get("response"):
            out.append(f"  - Response `{c.get('response_type', '')}`: {_fields(c['response'])}")
        elif c.get("response_type"):
            out.append(f"  - Response: `{c['response_type']}`")
        if c.get("view"):
            out.append(f"  - Renders view `{c['view']}`" + (
                f" with model {', '.join(f'`{m[0] if isinstance(m, (list, tuple)) else m}`' for m in c.get('model', [])[:10])}"
                if c.get("model") else ""))
        if c.get("redirects"):
            out.append(f"  - Redirects: {', '.join(f'`{r}`' for r in c['redirects'])}")
        if c.get("validation"):
            out.append(f"  - Validation: {_cell('; '.join(map(str, c['validation'][:10])))}")
        if c.get("statuses"):
            out.append(f"  - Statuses: {_cell(', '.join(map(str, c['statuses'])))}")
        if c.get("errors"):
            out.append(f"  - Errors: {_cell('; '.join(map(str, c['errors'][:10])))}")
        if c.get("access"):
            out.append(f"  - Access rule: `{_cell(c['access'])}`")
    trace = _evidence_for(e, ev_lines)
    if trace:
        out.append("- **Traced downstream (evidence):**")
        out += [f"  {l if l.startswith(('-', '*')) else '- ' + l}" for l in trace]
    return out


def screenshot_index(manifest: dict | None) -> dict[str, list[str]]:
    """{page file: [SCR ids]} from the UI Screens manifest."""
    out: dict[str, list[str]] = {}
    for s in (manifest or {}).get("screens", []):
        out.setdefault(s["template"], []).append(s["id"])
    return out


def page_order(pages: list[dict]) -> dict[str, str]:
    """{page file: "PG-nn Title"} for the UI Screens document's headings and order."""
    return {p["file"]: f"{p['id']} {p['title']}" for p in pages}
