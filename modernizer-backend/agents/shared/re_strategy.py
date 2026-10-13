"""
Reverse-engineering strategies: how the evidence about a repository is gathered.

Stack discovery used to gather evidence one technology stack at a time. For a
large full-stack monolith that splits every user journey across several packs
— the screen in one, the service in another, the table in a third — and leaves
the code no journey reaches indistinguishable from the code every journey uses.
A *layered* reading follows the system the way a request moves through it:

- **UI top-down** — every screen and control, traced downstream through the
  API, the services and the data access to the database reads and writes it
  causes (after the API pass, the backend part is a link to the endpoint's trace:
  each handler is read once, however many screens call it);
- **Data bottom-up** — every table, view, procedure and trigger, traced upwards
  to every component and flow that reads or changes it, and how its rows change;
- **API & business logic** — every endpoint, job and listener, with the business
  rules, validations and integrations in its path, marking which ones the UI
  reaches and which none of the flows reach.

What no pass reaches — endpoints no screen calls, tables no code touches,
classes nothing references — together with the debt the passes observe, is the
tech-debt and dead-code deliverable a person reviews.

This module is model-free: it works out which layers a repository has (from the
confirmed stacks and the computed facts), offers the strategies that fit with a
recommendation and its reasons, and cuts each pass into batches an agent can read
in full. The agents' instructions are the `layer-*` skills.
"""
from __future__ import annotations

from . import fswalk
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import ui_contracts
from .dependency_graph import EXCLUDED_DIRS

#: stack kind (stack_detector.KIND_ORDER) -> architectural layer
LAYER_OF_KIND = {"web-tier": "ui", "frontend": "ui", "service": "api", "application": "api", "language": "api",
                 "server": "api", "database": "db", "search": "db", "messaging": "integration",
                 "identity": "integration"}
LAYER_LABELS = {"ui": "UI layer", "api": "API / service layer", "db": "Data layer", "integration": "Integrations"}


@dataclass(frozen=True)
class Pass:
    id: str
    label: str
    skill: str
    direction: str
    summary: str


PASSES: dict[str, Pass] = {
    "ui": Pass("ui", "UI layer — top-down flow trace", "layer-ui-trace", "top-down",
               "Every screen and control, traced through the client code to the endpoint it calls, and from "
               "there through the services and data access to the reads and writes it causes — the backend part "
               "linked to the API pass's endpoint traces when that pass ran first."),
    "db": Pass("db", "Data layer — bottom-up trace", "layer-data-trace", "bottom-up",
               "Every table, view, procedure and trigger, traced up to the components and flows that read or "
               "change it, and how its rows change over their life."),
    "api": Pass("api", "API & business logic", "layer-api-logic", "middle-out",
                "Every endpoint, job and listener with the business rules, validations, state changes and "
                "integrations in its path; which ones the UI reaches and which nothing reaches."),
}


@dataclass
class Strategy:
    id: str
    name: str
    passes: tuple[str, ...]           # () = stack by stack
    summary: str
    best_for: str
    standards: str
    available: bool = True
    recommended: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "passes": list(self.passes),
                "pass_labels": [PASSES[p].label for p in self.passes], "summary": self.summary,
                "best_for": self.best_for, "standards": self.standards, "available": self.available,
                "recommended": self.recommended, "reasons": self.reasons}


STACK_BY_STACK = "stack-by-stack"
STRATEGY_IDS = ("layered-trace", "api-first", "data-first", STACK_BY_STACK)


# ─────────────────────────────────────────────────────────────────────────────
# Layers
# ─────────────────────────────────────────────────────────────────────────────

def detect_layers(stacks: list[dict], signals: dict | None = None) -> dict[str, dict]:
    """{layer: {"present", "stacks": [ids], "signals": {...}}} from the confirmed
    stacks and, when given, the computed counts (screens, endpoints, tables...)."""
    signals = signals or {}
    layers = {k: {"present": False, "stacks": [], "signals": {}} for k in LAYER_LABELS}
    for s in stacks:
        layer = LAYER_OF_KIND.get(s.get("kind", ""), "api" if s.get("kind") == "other" else "")
        if layer:
            layers[layer]["stacks"].append(s["pattern"])
            layers[layer]["present"] = True
    for layer, keys in (("ui", ("screens", "controls", "ui_files")), ("api", ("endpoints", "soap", "jobs", "listeners")),
                        ("db", ("tables", "entities", "routines"))):
        found = {k: signals[k] for k in keys if signals.get(k)}
        layers[layer]["signals"] = found
        if found:
            layers[layer]["present"] = True
    return layers


def signals_for(workspace_dir: str, inventory: dict | None = None, ui_result: dict | None = None,
                database: dict | None = None) -> dict:
    """Counts behind the recommendation, from the computed facts already at hand."""
    out = {}
    if ui_result:
        out["screens"] = len(ui_result.get("screens", []))
        out["controls"] = len(ui_contracts.ids(ui_result))
    if inventory:
        out["endpoints"] = len(inventory.get("endpoints", []))
        out["soap"] = len(inventory.get("soap", []))
        out["jobs"] = len(inventory.get("jobs", []))
        out["listeners"] = len(inventory.get("listeners", []))
    if database:
        out["tables"] = sum(1 for o in database.get("objects", []) if o["kind"].startswith(("TABLE", "VIEW")))
        out["entities"] = len(database.get("entities", []))
        out["routines"] = sum(1 for o in database.get("objects", [])
                              if o["kind"] in ("PROCEDURE", "FUNCTION", "PACKAGE", "PACKAGE BODY", "TRIGGER"))
    root = Path(workspace_dir)
    if root.is_dir():
        ui_suffixes = {".jsp", ".jspf", ".html", ".htm", ".vue", ".jsx", ".tsx", ".hbs"}
        out["ui_files"] = sum(1 for p in fswalk.files(root) if p.is_file() and p.suffix.lower() in ui_suffixes
                              and not EXCLUDED_DIRS & set(p.relative_to(root).parts))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Strategies
# ─────────────────────────────────────────────────────────────────────────────

def _describe(layers: dict) -> str:
    present = [LAYER_LABELS[k] + (f" ({', '.join(v['stacks'])})" if v["stacks"] else "")
               for k, v in layers.items() if v["present"]]
    return ", ".join(present) or "no clear layers"


def options(stacks: list[dict], signals: dict | None = None) -> list[dict]:
    """The strategies offered for this repository, the recommended one first."""
    layers = detect_layers(stacks, signals)
    ui, api, db = (layers[k]["present"] for k in ("ui", "api", "db"))
    sig = signals or {}
    found = _describe(layers)
    out = [
        Strategy("layered-trace", "Layered trace: API & logic → UI top-down → data bottom-up",
                 ("api", "ui", "db"),
                 "Three passes. (1) Every endpoint, job and listener traced once, down to the data store, for its "
                 "business logic — marking which ones no screen calls. (2) From every screen and control through "
                 "the client code to the endpoint it calls, linking to that endpoint's trace instead of reading "
                 "the backend again. (3) From every table, procedure and trigger up to whatever changes it. "
                 "Whatever no pass reaches becomes the dead-code list.",
                 "Full-stack monoliths with a UI, a service layer and a database.",
                 "End-to-end transaction tracing and the SEI 'horseshoe' architecture-recovery approach: recover "
                 "the as-is architecture from the code before any change; outside-in from the user interface, "
                 "inside-out from the data.",
                 available=ui and (api or db)),
        Strategy("api-first", "API-first: API & logic → data bottom-up (→ UI)",
                 ("api", "db") + (("ui",) if ui else ()),
                 "Starts from the service contracts — every endpoint, job and listener and the logic behind it — "
                 "then traces the data layer bottom-up; any UI is traced last against the documented API.",
                 "Back-end services and APIs consumed by other systems, with little or no UI in the repository.",
                 "Contract-first / outside-in analysis of service interfaces (OpenAPI-style contracts), then data "
                 "reverse engineering.",
                 available=api),
        Strategy("data-first", "Data-first: data bottom-up → API & logic → UI",
                 ("db", "api") + (("ui",) if ui else ()),
                 "Starts from the schema — tables, keys, views, procedures, triggers and change scripts — and "
                 "how each is written; then the code that reads and changes the data; then the screens.",
                 "Database-centric systems: heavy PL/SQL or SQL logic, batch and ETL, reporting.",
                 "Data reverse engineering (bottom-up schema recovery), as used for database-centric legacy "
                 "systems.",
                 available=db),
        Strategy(STACK_BY_STACK, "Stack by stack (technology view)", (),
                 "One evidence pass per confirmed technology stack, each documented on its own and then combined.",
                 "Repositories without a clear layering — libraries, tools, infrastructure code, several "
                 "unrelated parts.",
                 "Technology inventory (one checklist per technology).",
                 available=True),
    ]
    by_id = {s.id: s for s in out}
    if ui and api and db:
        rec = "layered-trace"
        why = [f"Layers found: {found}.",
               "All three layers are present, so a request can be followed from the screen to the database, and "
               "code that no screen, table or endpoint reaches stands out as dead-code candidates."]
    elif api and not ui and (sig.get("endpoints") or sig.get("soap") or sig.get("listeners") or sig.get("jobs")
                             or not db):
        rec = "api-first"
        why = [f"Layers found: {found}.", "No UI layer: the service contracts are the system's front door."]
    elif db and (not api or sig.get("routines", 0) > max(5, sig.get("endpoints", 0) + sig.get("soap", 0))):
        rec = "data-first"
        why = [f"Layers found: {found}.",
               "The logic sits largely in the database (procedures, triggers) or there is no service layer."]
    elif ui and (api or db):
        rec = "layered-trace"
        why = [f"Layers found: {found}.", "A UI is present with code behind it: tracing from the screens down "
               "follows every user journey end to end."]
    else:
        rec = STACK_BY_STACK
        why = [f"Layers found: {found}.", "No UI-to-data layering to trace; each technology is documented "
               "on its own."]
    by_id[rec].recommended = True
    by_id[rec].reasons = why
    for s in out:
        if not s.available:
            missing = {"layered-trace": "needs a UI layer and a service or data layer",
                       "api-first": "needs an API / service layer", "data-first": "needs a data layer"}[s.id]
            s.reasons = [f"Not available: this repository {missing} (found: {found})."]
    out.sort(key=lambda s: (not s.recommended, not s.available, STRATEGY_IDS.index(s.id)))
    return [s.to_dict() for s in out]


def get(strategy_id: str, offered: list[dict]) -> dict:
    """The offered strategy with this id; ValueError when unknown or not available."""
    chosen = next((s for s in offered if s["id"] == strategy_id), None)
    if chosen is None:
        raise ValueError(f"Unknown strategy '{strategy_id}'. Choose one of: {', '.join(s['id'] for s in offered)}.")
    if not chosen["available"]:
        raise ValueError(f"Strategy '{strategy_id}' is not available here: {' '.join(chosen['reasons'])}")
    return chosen


def to_markdown(offered: list[dict]) -> str:
    lines = ["## Reverse-Engineering Strategy Options", ""]
    for n, s in enumerate(offered, 1):
        flag = " — **recommended**" if s["recommended"] else ("" if s["available"] else " — not available")
        lines += [f"### {n}. {s['name']} (`{s['id']}`){flag}", "", s["summary"], "",
                  f"- **Best for:** {s['best_for']}", f"- **Practice:** {s['standards']}"]
        if s["pass_labels"]:
            lines.append("- **Passes, in order:** " + " → ".join(s["pass_labels"]))
        lines += [f"- {r}" for r in s["reasons"]] + [""]
    return "\n".join(lines).rstrip() + "\n"


# ─────────────────────────────────────────────────────────────────────────────
# Pass batches: what each agent run of a pass is given
# ─────────────────────────────────────────────────────────────────────────────

def _handler_class(handler: str) -> str:
    return handler.rsplit(".", 1)[0] if "." in handler else handler


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint traces: the API pass's work, reused by the UI pass
# ─────────────────────────────────────────────────────────────────────────────
#
# Screens share their backend: thirteen screens calling the same services used to
# mean thirteen agents each reading those services. When the API pass runs first,
# every handler is traced once, down to the data store; each UI batch is then given
# a one-line index of the traces of the endpoints its controls call and reads only
# the UI side. The index is computed here from the numbered pack — no model.

_TRACE_SECTIONS_RELATED = ("Entry Points & Interfaces", "Business Behaviour", "Data", "Security",
                           "Component Interactions")
_MAX_RELATED = 6
_SUMMARY_CHARS = 240


def _short_handler(handler: str) -> str:
    """`com.acme.web.OrderController.cancel` -> `OrderController.cancel`."""
    parts = handler.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else handler


def endpoint_traces(api_pack: str, inventory: dict) -> dict[str, dict]:
    """{endpoint key `VERB /path Handler.method` (the key UI controls carry): {"trace": [ids],
    "related": [ids], "summary": str}} from the API pass's numbered Evidence Pack. A trace is a
    Flow Traces item naming the handler method (or the verb and path); related items are the
    entry-point, behaviour, data, security and interaction items naming the handler method."""
    from .evidence_pack import parse
    if not api_pack:
        return {}
    sections = parse(api_pack)
    item_re = re.compile(r"^[-*+]\s+\[(EV-[^\]]+)\]\s*(.*)$", re.S)

    def items(section: str) -> list[tuple[str, str]]:
        out = []
        for raw in sections.get(section, []):
            m = item_re.match(raw)
            if m:
                out.append((m.group(1), " ".join(m.group(2).split())))
        return out

    flows = items("Flow Traces")
    related_pool = [(sec, i) for sec in _TRACE_SECTIONS_RELATED for i in items(sec)]
    out: dict[str, dict] = {}
    for e in inventory.get("endpoints", []):
        key = f"{e['verb']} {e['path']} {e['handler']}"
        method = _short_handler(e["handler"])
        by_method = re.compile(rf"(?<![\w.]){re.escape(method)}\b")
        by_route = re.compile(rf"\b{re.escape(e['verb'])}\s+`?[^\s`]*{re.escape(e['path'])}(?![\w/{{-])")
        # The handler method identifies the endpoint; the route (which may carry a servlet prefix) only
        # when no trace names the method, so a shared path suffix never borrows another endpoint's trace.
        trace = [(i, t) for i, t in flows if by_method.search(t)] or [(i, t) for i, t in flows if by_route.search(t)]
        related = [i for _sec, (i, t) in related_pool if by_method.search(t)][:_MAX_RELATED]
        if trace or related:
            summary = trace[0][1] if trace else ""
            out[key] = {"trace": [i for i, _ in trace], "related": [i for i in related if i not in dict(trace)],
                        "summary": summary[:_SUMMARY_CHARS] + (" …" if len(summary) > _SUMMARY_CHARS else "")}
    return out


def _batch_endpoints(batch: list[dict]) -> list[str]:
    """The endpoint keys the controls of a UI batch call, in order."""
    return list(dict.fromkeys(k for screen in batch for e in screen["elements"] for k in e["endpoints"]))


def endpoint_index(keys: list[str], traces: dict[str, dict], trace_file: str = "") -> str:
    """The section a UI batch gets: one line per endpoint its controls call, with the API pass's
    evidence ids, or a note that no trace exists (then the agent traces that one itself)."""
    if not keys:
        return ""
    lines = ["## Endpoint traces from the API pass — link to these, do not re-trace the backend", "",
             "The API pass already traced each of these handlers to the data store (validations, decisions, data "
             "effects, errors, with citations). For every control that calls one, read the UI side only and "
             "link the backend part to these ids (`→ see EV-api-…`). Trace below the handler yourself only "
             "for an endpoint marked **no trace**." + (f" For a detail a summary does not give, search "
                                                     f"`{trace_file}` for the id instead of reading the backend."
                                                     if trace_file else ""), ""]
    for key in keys:
        verb, path, handler = (key.split(" ", 2) + ["", ""])[:3]
        t = traces.get(key)
        head = f"- `{verb} {path}` → `{_short_handler(handler)}`"
        if not t:
            lines.append(f"{head}: **no trace** from the API pass — trace it below the handler yourself.")
            continue
        ids = ", ".join(t["trace"]) or "no flow trace"
        also = f"; also {', '.join(t['related'])}" if t["related"] else ""
        lines.append(f"{head}: trace {ids}{also}" + (f" — {t['summary']}" if t["summary"] else ""))
    return "\n".join(lines)


def ui_batches(ui_result: dict, ui_files: list[str], max_elements: int = 20, max_chars: int = 50_000,
               max_files: int = 40, traces: dict[str, dict] | None = None, trace_file: str = "") -> list[dict]:
    """Screens with their controls and the handler contracts they call; when the
    UI could not be parsed into screens, the UI files themselves in units. With the
    API pass's endpoint traces, each batch also gets the index of the traces of the
    endpoints its controls call."""
    out = []
    batches = ui_contracts.batches(ui_result, max_elements, max_chars) if ui_result.get("screens") else []
    for i, batch in enumerate(batches, 1):
        request = ("## Screens and controls to trace (computed from the code)\n\n"
                   + ui_contracts.batch_request(batch, ui_result))
        if traces is not None:
            index = endpoint_index(_batch_endpoints(batch), traces, trace_file)
            if index:
                request += "\n\n" + index
        out.append({"title": f"screens {i}/{len(batches)}: "
                             + ", ".join(dict.fromkeys(Path(s['file']).name for s in batch)),
                    "request": request})
    covered = {s["file"] for s in ui_result.get("screens", [])}
    rest = [f for f in ui_files if f not in covered]
    units = [rest[i:i + max_files] for i in range(0, len(rest), max_files)]
    for i, unit in enumerate(units, 1):
        out.append({"title": f"UI files {i}/{len(units)}",
                    "request": "## UI files to read and trace\nThese UI files were not parsed into screens by the "
                               "pipeline: read each, find every screen, control and call it makes, and trace each "
                               "downstream.\n\n" + "\n".join(f"- `{f}`" for f in unit)})
    return out


def db_batches(database: dict, workspace_dir: str, max_objects: int = 15) -> list[dict]:
    """Tables, views, routines and entities, each with the files that name it."""
    objects = [o for o in database.get("objects", [])
               if o["kind"].startswith(("TABLE", "VIEW", "MATERIALIZED", "PROCEDURE", "FUNCTION", "PACKAGE",
                                        "TRIGGER", "SEQUENCE"))]
    items = [{"kind": o["kind"], "name": o["name"], "definition": o["detail"], "where": o["where"]} for o in objects]
    defined = {i["name"].split(".")[-1].upper() for i in items}
    for e in database.get("entities", []):
        name = (e["table"] or e["class"]).split(".")[-1]
        if name.upper() not in defined:
            items.append({"kind": f"{e['kind']} class", "name": name, "definition": f"class {e['class']}",
                          "where": e["where"]})
    search = database.get("search") or {}
    for core in search.get("cores", []):
        sc = core.get("schema") or {}
        items.append({"kind": "SOLR CORE", "name": core["core"],
                      "definition": (f"unique key {sc.get('unique_key')}; " if sc.get("unique_key") else "")
                      + "fields " + ", ".join(f"{f['name']} ({f['type']})" for f in sc.get("fields", [])[:25])
                      + (("; request handlers " + ", ".join(h["name"] for h in core["handlers"]))
                         if core.get("handlers") else ""),
                      "where": sc.get("file") or core.get("config") or core["dir"]})
    if not items:
        return []
    names = {i["name"].split(".")[-1]: i for i in items}
    entity_class = {(e["table"] or e["class"]).split(".")[-1].upper(): e["class"] for e in database.get("entities", [])}
    users: dict[str, list[str]] = {n: [] for n in names}
    root = Path(workspace_dir)
    # A file or bean name (`xsd/accounts.xsd`, `/accounts/`) is not a use of the table.
    pattern = re.compile(r"(?<![/\w.-])(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
                         + r")(?![\w-]|\.[a-z]{2,4}\b|/)", re.I)
    for path in sorted(fswalk.files(root)) if root.is_dir() else []:
        if not path.is_file() or path.suffix.lower() not in {".java", ".kt", ".groovy", ".xml", ".sql", ".pls",
                                                             ".pks", ".pkb", ".js", ".ts", ".py", ".cs"}:
            continue
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(Path(rel).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = {m.group(1).lower() for m in pattern.finditer(text)}
        for n in names:
            cls = entity_class.get(n.upper())
            if n.lower() in hits or (cls and re.search(rf"\b{re.escape(cls)}\b", text)):
                if rel not in users[n] and len(users[n]) < 40:
                    users[n].append(rel)
    out = []
    keys = list(names)
    for i in range(0, len(keys), max_objects):
        chunk = keys[i:i + max_objects]
        lines = ["## Data objects to trace bottom-up (computed from the code)", ""]
        for n in chunk:
            it = names[n]
            lines += [f"### {it['kind']} `{it['name']}` ({it['where']})",
                      f"- Definition: {it['definition'] or '(see the file)'}",
                      "- Files that name it: " + (", ".join(f"`{u}`" for u in users[n]) or
                                                  "none found outside its definition — a dead-data candidate"), ""]
        out.append({"title": f"data objects {i // max_objects + 1}/{(len(keys) - 1) // max_objects + 1}",
                    "request": "\n".join(lines)})
    return out


def api_batches(inventory: dict, ui_result: dict, max_classes: int = 8) -> list[dict]:
    """Endpoints, jobs and listeners grouped by handler class, each marked with the
    UI controls that call it (none = not reached from the repository's UI)."""
    called: dict[str, list[str]] = {}
    has_ui = bool(ui_result.get("screens"))
    for c in ui_result.get("contracts", []):
        called[c["endpoint"]] = c.get("called_by", [])
    groups: dict[str, list[str]] = {}
    files: dict[str, str] = {}
    for e in inventory.get("endpoints", []):
        key = f"{e['verb']} {e['path']}"
        cls = _handler_class(e["handler"])
        files.setdefault(cls, e["source"].rsplit(":", 1)[0])
        ui = called.get(key, [])
        # "Not called from the UI" only means something when the repository has a UI.
        note = f" — called from UI {', '.join(ui[:12])}" if ui else \
            " — **no UI control in this repository calls it**" if has_ui else ""
        groups.setdefault(cls, []).append(f"- {e['kind']} `{key}` → `{e['handler']}` ({e['source']}){note}")
    for o in inventory.get("soap", []):
        cls = _handler_class(o["handler"])
        files.setdefault(cls, o["source"].rsplit(":", 1)[0])
        msg = o["request"] or ", ".join(o.get("params", []))
        groups.setdefault(cls, []).append(
            f"- SOAP ({o['style']}) operation `{o['operation']}` of `{o['service']}` at `{o['address'] or '?'}` "
            f"({msg or 'no input'} → {o['response'] or 'void'}) → `{o['handler']}` ({o['source']})")
    for j in inventory.get("jobs", []):
        cls = _handler_class(j["handler"])
        files.setdefault(cls, j["source"].rsplit(":", 1)[0])
        groups.setdefault(cls, []).append(f"- scheduled job `{j['handler']}` ({j['schedule']}) ({j['source']})")
    for li in inventory.get("listeners", []):
        cls = _handler_class(li["handler"])
        files.setdefault(cls, li["source"].rsplit(":", 1)[0])
        groups.setdefault(cls, []).append(f"- {li['kind']} listener `{li['handler']}` on `{li['destination']}` "
                                          f"({li['source']})")
    classes = sorted(groups)
    out = []
    for i in range(0, len(classes), max_classes):
        chunk = classes[i:i + max_classes]
        lines = ["## Entry points to analyse (computed from the code)", ""]
        for cls in chunk:
            lines += [f"### `{cls}` (`{files[cls]}`)", *groups[cls], ""]
        out.append({"title": f"entry points {i // max_classes + 1}/{(len(classes) - 1) // max_classes + 1}: "
                             + ", ".join(chunk[:4]) + (" …" if len(chunk) > 4 else ""),
                    "request": "\n".join(lines)})
    return out


def fallback_batches(files: list[str], label: str, max_files: int = 40) -> list[dict]:
    """A pass with nothing computed to start from reads its layer's files."""
    units = [files[i:i + max_files] for i in range(0, len(files), max_files)]
    return [{"title": f"{label} files {i}/{len(units)}",
             "request": f"## {label} files to read\n\n" + "\n".join(f"- `{f}`" for f in unit)}
            for i, unit in enumerate(units, 1)]


def pass_batches(pass_id: str, layer_files: list[str], inventory: dict, ui_result: dict, database: dict,
                 workspace_dir: str, max_elements: int = 20, max_chars: int = 50_000,
                 max_files: int = 40, api_pack: str = "", trace_file: str = "") -> list[dict]:
    """The batches of one pass: computed starting points first, the layer's files
    when nothing was computed for it. `api_pack` (the API pass's numbered pack, when it
    ran first) gives the UI batches their endpoint-trace index; `trace_file` is where an
    agent can look an id up."""
    if pass_id == "ui":
        traces = endpoint_traces(api_pack, inventory or {}) if api_pack else None
        return ui_batches(ui_result or {}, layer_files, max_elements, max_chars, max_files, traces, trace_file)
    if pass_id == "db":
        return db_batches(database or {}, workspace_dir) or fallback_batches(layer_files, "Data layer", max_files)
    return api_batches(inventory or {}, ui_result or {}) or fallback_batches(layer_files, "Service layer", max_files)


NOTHING_TO_TRACE = {"ui": "screens or UI files", "db": "tables, entities or data files",
                    "api": "endpoints, jobs, listeners or service files"}


def empty_pass_pack(pass_id: str) -> str:
    return (f"### Limitations\n- Nothing to trace in this layer: the pipeline found no {NOTHING_TO_TRACE[pass_id]} "
            "in the confirmed stacks.\n")


def debt_observations(packs: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    """(evidence id, text) of every item the passes recorded under Tech Debt & Dead Code."""
    from .evidence_pack import parse
    out = []
    for _sid, _label, text in packs:
        for item in parse(text).get("Tech Debt & Dead Code", []):
            m = re.match(r"^[-*+]\s+\[(EV-[^\]]+)\]\s*(.*)$", item, re.S)
            if m:
                out.append((m.group(1), " ".join(m.group(2).split())))
    return out
