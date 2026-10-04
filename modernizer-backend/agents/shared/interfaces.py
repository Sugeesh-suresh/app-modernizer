"""
The application's interfaces and jobs, read from the code's syntax tree — no
model involved.

- HTTP endpoints: Spring MVC/REST (`@RequestMapping` on the class joined with
  `@GetMapping`/`@PostMapping`/… or `@RequestMapping(method=…)` on the method)
  and JAX-RS (`@Path` + `@GET`/`@POST`/…). For a page controller the view name it
  returns is recorded when it is a literal (`return "x"`, `new ModelAndView("x")`,
  `setViewName("x")`).
- Scheduled jobs: `@Scheduled` (cron / fixedRate / fixedDelay / initialDelay,
  property placeholders kept as written).
- Message listeners: `@JmsListener`, `@KafkaListener`, `@RabbitListener`,
  `@SqsListener`, `@StreamListener`.

The tables go into the Technical Specification as computed facts, are given
to the Enterprise Architect agent, and the evidence check lists any endpoint or
job the Architect's specification does not mention — so the interface catalog
is complete by construction, not by how much an agent happened to read.
"""
import re
from pathlib import Path

from .dependency_graph import EXCLUDED_DIRS
from .rule_candidates import _PARSERS, _TEST_PATH

_VERBS = {"GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT", "DeleteMapping": "DELETE",
          "PatchMapping": "PATCH"}
_JAXRS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")   # a tuple: output order must not vary
_LISTENERS = {"JmsListener": "destination", "KafkaListener": "topics", "RabbitListener": "queues",
              "SqsListener": "value", "StreamListener": "value"}


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _annotations(node, src: bytes) -> dict[str, str]:
    """{annotation name: argument text} for a declaration."""
    out = {}
    for child in node.children:
        if child.type == "modifiers":
            for a in child.children:
                if a.type in ("annotation", "marker_annotation"):
                    name = a.child_by_field_name("name")
                    args = a.child_by_field_name("arguments")
                    out[_text(name, src).rsplit(".", 1)[-1] if name else ""] = _text(args, src) if args else ""
    return out


def _paths(args: str) -> list[str]:
    """Paths of a mapping annotation: ("/x"), (value = "/x"), (path = {"/a", "/b"})."""
    if not args:
        return [""]
    m = re.search(r"(?:\b(?:value|path)\s*=\s*)?(\{[^}]*\}|\"[^\"]*\")", args)
    if not m or re.match(r"\(\s*(?:method|produces|consumes|params|headers)\s*=", args):
        named = re.search(r"\b(?:value|path)\s*=\s*(\{[^}]*\}|\"[^\"]*\")", args)
        if not named:
            return [""]
        m = named
    return re.findall(r"\"([^\"]*)\"", m.group(1)) or [""]


def _join(base: str, path: str) -> str:
    joined = "/".join(p.strip("/") for p in (base, path) if p and p.strip("/"))
    return "/" + joined


def _attr(args: str, key: str) -> str:
    m = re.search(rf"\b{key}\s*=\s*(\"[^\"]*\"|[^,)]+)", args or "")
    return m.group(1).strip().strip('"') if m else ""


def scan(workspace_dir: str) -> dict:
    """{"endpoints": [...], "jobs": [...], "listeners": [...]}, in path order."""
    root = Path(workspace_dir)
    endpoints, jobs, listeners = [], [], []
    if "java" not in _PARSERS or not root.is_dir():
        return {"endpoints": endpoints, "jobs": jobs, "listeners": listeners}
    for path in sorted(root.rglob("*.java")):
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(Path(rel).parts) or _TEST_PATH.search(rel):
            continue
        try:
            src = path.read_bytes()
        except OSError:
            continue
        if not re.search(rb"Mapping|@Path|@Scheduled|Listener", src):
            continue
        tree = _PARSERS["java"].parse(src)
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            stack.extend(reversed(node.children))
            if node.type != "class_declaration":
                continue
            cls_name = _text(node.child_by_field_name("name"), src)
            cls_ann = _annotations(node, src)
            rest = "RestController" in cls_ann
            web = rest or "Controller" in cls_ann or "RequestMapping" in cls_ann or "Path" in cls_ann
            bases = _paths(cls_ann.get("RequestMapping", "")) if "RequestMapping" in cls_ann else \
                [_paths(cls_ann["Path"])[0]] if "Path" in cls_ann else [""]
            body = node.child_by_field_name("body")
            for member in (body.children if body else []):
                if member.type != "method_declaration":
                    continue
                ann = _annotations(member, src)
                name = _text(member.child_by_field_name("name"), src)
                line = member.start_point[0] + 1
                handler = f"{cls_name}.{name}"
                if web:
                    verbs, mpaths = [], [""]
                    for a, verb in _VERBS.items():
                        if a in ann:
                            verbs, mpaths = [verb], _paths(ann[a])
                    if "RequestMapping" in ann:
                        found = re.findall(r"RequestMethod\.(\w+)", ann["RequestMapping"])
                        verbs, mpaths = (found or ["ANY"]), _paths(ann["RequestMapping"])
                    jaxrs = [v for v in _JAXRS if v in ann]
                    if jaxrs:
                        verbs, mpaths = jaxrs, (_paths(ann["Path"]) if "Path" in ann else [""])
                    if verbs:
                        # The page's view: the first literal that is not an early redirect / forward.
                        literals = [next(g for g in m.groups() if g) for m in re.finditer(
                            r"return\s+\"([^\"]+)\"\s*;|new\s+ModelAndView\(\s*\"([^\"]+)\"|"
                            r"setViewName\(\s*\"([^\"]+)\"\s*\)", _text(member, src))]
                        returns = next((v for v in literals if not v.startswith(("redirect:", "forward:"))),
                                       literals[0] if literals else "")
                        api = rest or "ResponseBody" in ann or bool(jaxrs)
                        view = "" if api else returns
                        for base in bases:
                            for mp in mpaths:
                                for verb in verbs:
                                    endpoints.append({"verb": verb, "path": _join(base, mp), "handler": handler,
                                                      "kind": "REST" if api else "page", "view": view,
                                                      "source": f"{rel}:{line}"})
                if "Scheduled" in ann:
                    a = ann["Scheduled"]
                    schedule = next((f"{k} = {v}" for k in ("cron", "fixedRate", "fixedDelay", "fixedRateString",
                                                            "fixedDelayString") for v in [_attr(a, k)] if v), a)
                    delay = _attr(a, "initialDelay") or _attr(a, "initialDelayString")
                    jobs.append({"handler": handler, "schedule": schedule + (f", initialDelay = {delay}" if delay else ""),
                                 "zone": _attr(a, "zone"), "source": f"{rel}:{line}"})
                for a, key in _LISTENERS.items():
                    if a in ann:
                        dest = _attr(ann[a], key) or re.sub(r"^\(|\)$", "", ann[a])
                        listeners.append({"kind": a.replace("Listener", ""), "destination": dest,
                                          "handler": handler, "source": f"{rel}:{line}"})
    return {"endpoints": endpoints, "jobs": jobs, "listeners": listeners}


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|")


def to_markdown(inventory: dict) -> str:
    endpoints, jobs, listeners = inventory["endpoints"], inventory["jobs"], inventory["listeners"]
    if not (endpoints or jobs or listeners):
        return ""
    lines = ["## Interface & Job Inventory (computed)", "",
             "_Read from the code's syntax tree by the pipeline — complete for the annotation styles listed, "
             "not generated by an agent._", ""]
    if endpoints:
        lines += [f"### HTTP endpoints ({len(endpoints)})", "", "| Method | Path | Kind | Handler | View | Source |",
                  "|---|---|---|---|---|---|"]
        lines += [f"| {e['verb']} | `{_cell(e['path'])}` | {e['kind']} | `{e['handler']}` | "
                  f"{('`' + e['view'] + '`') if e['view'] else '—'} | `{e['source']}` |" for e in endpoints]
        lines.append("")
    if jobs:
        lines += [f"### Scheduled jobs ({len(jobs)})", "", "| Job | Schedule | Zone | Source |", "|---|---|---|---|"]
        lines += [f"| `{j['handler']}` | `{_cell(j['schedule'])}` | {j['zone'] or '—'} | `{j['source']}` |" for j in jobs]
        lines.append("")
    if listeners:
        lines += [f"### Message listeners ({len(listeners)})", "", "| Kind | Destination | Handler | Source |",
                  "|---|---|---|---|"]
        lines += [f"| {m['kind']} | `{_cell(m['destination'])}` | `{m['handler']}` | `{m['source']}` |" for m in listeners]
        lines.append("")
    return "\n".join(lines).rstrip()


def uncovered(inventory: dict, document: str) -> list[str]:
    """Endpoints and jobs a document does not mention (path or handler method name)."""
    missing = []
    for e in inventory["endpoints"]:
        method = e["handler"].rsplit(".", 1)[-1]
        # The exact path ("/rest/v1/jobs" is not covered by "/rest/v1/jobs/{id}") or the handler.
        # Sentence punctuation may follow the path; another path segment may not.
        path_named = re.search(re.escape(e["path"]) + r"(?![\w/{-]|\.\w)", document)
        if not path_named and f"{method}(" not in document and e["handler"] not in document:
            missing.append(f"{e['verb']} {e['path']} ({e['handler']})")
    for j in inventory["jobs"]:
        if j["handler"].rsplit(".", 1)[-1] not in document:
            missing.append(f"scheduled job {j['handler']}")
    return missing
