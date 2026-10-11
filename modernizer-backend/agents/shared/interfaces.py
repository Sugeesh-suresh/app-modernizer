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
- SOAP operations: Spring Web Services (`@PayloadRoot` / `@SoapAction` /
  `@Action` methods of an `@Endpoint` class) and JAX-WS (`@WebService` classes,
  every public method unless `@WebMethod(exclude = true)`). The address comes from
  the code or configuration (`MessageDispatcherServlet` mapping,
  `spring.webservices.path`, `Endpoint.publish`, CXF `EndpointImpl.publish`,
  `sun-jaxws.xml`), and the request and response fields from the repository's XSD
  schemas when the payload is a schema element.

The tables go into the Technical Specification as computed facts, are given
to the Enterprise Architect agent, and the evidence check lists any endpoint or
job the Architect's specification does not mention — so the interface catalog
is complete by construction, not by how much an agent happened to read.
"""
import re
import xml.etree.ElementTree as ET
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
    """{"endpoints": [...], "jobs": [...], "listeners": [...], "soap": [...]}, in path order."""
    root = Path(workspace_dir)
    endpoints, jobs, listeners, soap = [], [], [], []
    if "java" not in _PARSERS or not root.is_dir():
        return {"endpoints": endpoints, "jobs": jobs, "listeners": listeners, "soap": soap}
    addresses = _soap_addresses(root)
    for path in sorted(root.rglob("*.java")):
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(Path(rel).parts) or _TEST_PATH.search(rel):
            continue
        try:
            src = path.read_bytes()
        except OSError:
            continue
        if not re.search(rb"Mapping|@Path|@Scheduled|Listener|@Endpoint|@WebService|PayloadRoot|SoapAction", src):
            continue
        consts = dict(re.findall(r'\b(\w+)\s*=\s*"([^"]*)"\s*;', src.decode("utf-8", "replace")))
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
            jaxws = "WebService" in cls_ann
            for member in (body.children if body else []):
                if member.type != "method_declaration":
                    continue
                ann = _annotations(member, src)
                name = _text(member.child_by_field_name("name"), src)
                line = member.start_point[0] + 1
                handler = f"{cls_name}.{name}"
                op = _soap_operation(member, ann, cls_name, cls_ann, jaxws, name, src, consts, addresses)
                if op:
                    soap.append({**op, "handler": handler, "source": f"{rel}:{line}"})
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
    if soap:
        schemas = _xsd_elements(root)
        for op in soap:
            op["request_fields"] = schemas.get(op["request"], [])
            op["response_fields"] = schemas.get(op["response"], [])
    return {"endpoints": endpoints, "jobs": jobs, "listeners": listeners, "soap": soap}


# ── SOAP ────────────────────────────────────────────────────────────────────

def _soap_operation(member, ann, cls_name, cls_ann, jaxws, name, src, consts, addresses) -> dict | None:
    """One SOAP operation, when this method is one."""
    def value(raw: str) -> str:
        raw = raw.strip()
        return raw.strip('"') if raw.startswith('"') else consts.get(raw.rsplit(".", 1)[-1], raw)

    params = member.child_by_field_name("parameters")
    ret = member.child_by_field_name("type")
    returns = _base_type(_text(ret, src)) if ret is not None else ""
    plist = [p for p in (params.children if params else []) if p.type in ("formal_parameter", "spread_parameter")]
    if "PayloadRoot" in ann or "SoapAction" in ann or ("Action" in ann and "Endpoint" in cls_ann):
        a = ann.get("PayloadRoot") or ann.get("SoapAction") or ann.get("Action") or ""
        local = value(_attr(a, "localPart")) if "PayloadRoot" in ann else ""
        payload = next((p for p in plist if "RequestPayload" in _text(p, src)), plist[0] if plist else None)
        request = _base_type(_text(payload.child_by_field_name("type"), src)) if payload is not None else ""
        action = value(_attr(a, "value") or re.sub(r"^\(|\)$", "", a)) if "PayloadRoot" not in ann else ""
        # DefaultWsdl11Definition names the operation after the request element without its suffix.
        operation = re.sub(r"Request$", "", local) if local else (action or name)
        return {"style": "Spring-WS", "service": cls_name, "operation": operation,
                "namespace": value(_attr(a, "namespace")), "soap_action": action,
                "request": local or request, "response": returns if returns != "void" else "",
                "address": addresses.get("spring-ws", "/services/* (Spring Boot default)"),
                "wsdl": addresses.get("wsdl", "")}
    if not jaxws:
        return None
    mods = next((c for c in member.children if c.type == "modifiers"), None)
    if mods is None or "public" not in _text(mods, src).split():
        return None
    wm = ann.get("WebMethod", "")
    if re.search(r"exclude\s*=\s*true", wm):
        return None
    ws = cls_ann.get("WebService", "")
    service = value(_attr(ws, "serviceName")) or cls_name + "Service"
    names = []
    for p in plist:
        wp = re.search(r'@WebParam\s*\([^)]*name\s*=\s*"([^"]+)"', _text(p, src))
        pname = p.child_by_field_name("name")
        names.append((wp.group(1) if wp else _text(pname, src) if pname is not None else "?",
                      _base_type(_text(p.child_by_field_name("type"), src))))
    return {"style": "JAX-WS", "service": service, "operation": value(_attr(wm, "operationName")) or name,
            "namespace": value(_attr(ws, "targetNamespace")), "soap_action": value(_attr(wm, "action")),
            "request": "", "response": "" if returns == "void" else returns,
            "params": [f"{n}: {t}" for n, t in names],
            "address": addresses.get(cls_name, ""), "wsdl": addresses.get(cls_name, "") + "?wsdl"
            if addresses.get(cls_name) else ""}


def _base_type(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _soap_addresses(root: Path) -> dict[str, str]:
    """Where the SOAP services listen: {"spring-ws": path, "wsdl": url, <JAX-WS class>: address}."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(Path(rel).parts) or _TEST_PATH.search(rel) or not path.is_file() or path.is_symlink():
            continue
        if path.suffix not in (".java", ".properties", ".yml", ".yaml", ".xml") or path.stat().st_size > 1_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".java":
            m = re.search(r"MessageDispatcherServlet[\s\S]{0,600}?ServletRegistrationBean\s*<?[^(]*\(\s*\w+\s*,\s*\"([^\"]+)\"",
                          text)
            if m:
                out["spring-ws"] = m.group(1)
            w = re.search(r"@Bean\s*\(\s*(?:name\s*=\s*)?\"([^\"]+)\"\s*\)[\s\S]{0,200}?DefaultWsdl11Definition", text)
            if w:
                out["wsdl_bean"] = w.group(1)
            for pub in re.finditer(r"Endpoint\.publish\(\s*\"([^\"]+)\"\s*,\s*(?:new\s+(\w+)\s*\(|(\w+))", text):
                cls = pub.group(2) or next(iter(re.findall(rf"\b([A-Z]\w*)\s+{pub.group(3)}\b", text)), "")
                if cls:
                    out[cls] = pub.group(1)
            for impl in re.finditer(r"new\s+EndpointImpl\([^,]+,\s*(?:new\s+(\w+)\s*\(|(\w+))[\s\S]{0,300}?"
                                    r"\.publish\(\s*\"([^\"]+)\"", text):
                cls = impl.group(1) or next(iter(re.findall(rf"\b([A-Z]\w*)\s+{impl.group(2)}\b", text)), "")
                if cls:
                    out[cls] = impl.group(3)
        elif path.name == "sun-jaxws.xml":
            for e in re.finditer(r'implementation\s*=\s*"([\w.]+)"[^>]*url-pattern\s*=\s*"([^"]+)"', text):
                out[e.group(1).rsplit(".", 1)[-1]] = e.group(2)
        else:
            m = re.search(r"spring\.webservices\.path\s*[=:]\s*(\S+)|webservices:\s*\n\s+path:\s*(\S+)", text)
            if m and "spring-ws" not in out:
                out["spring-ws"] = (m.group(1) or m.group(2)).rstrip("/") + "/*"
    if "wsdl_bean" in out:
        out["wsdl"] = out.get("spring-ws", "/services/*").rstrip("*").rstrip("/") + f"/{out.pop('wsdl_bean')}.wsdl"
    return out


def _xsd_elements(root: Path) -> dict[str, list[tuple[str, str, str]]]:
    """{global element name: [(field, type, occurs)]} from the repository's XSD schemas."""
    out: dict[str, list] = {}
    ns = "{http://www.w3.org/2001/XMLSchema}"
    for path in sorted(root.rglob("*.xsd")):
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(Path(rel).parts) or path.is_symlink():
            continue
        try:
            tree = ET.parse(path)
        except (ET.ParseError, OSError):
            continue
        for el in tree.getroot().findall(f"{ns}element"):
            fields = []
            for child in el.iter(f"{ns}element"):
                if child is el or not child.get("name"):
                    continue
                lo, hi = child.get("minOccurs", "1"), child.get("maxOccurs", "1")
                occurs = "required" if lo != "0" else "optional"
                if hi not in ("1",):
                    occurs += ", repeated"
                fields.append((child.get("name"), (child.get("type") or "complex").split(":")[-1], occurs))
            if el.get("name"):
                out.setdefault(el.get("name"), fields)
    return out


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|")


def to_markdown(inventory: dict) -> str:
    endpoints, jobs, listeners = inventory["endpoints"], inventory["jobs"], inventory["listeners"]
    soap = inventory.get("soap", [])
    if not (endpoints or jobs or listeners or soap):
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
    if soap:
        lines += [f"### SOAP operations ({len(soap)})", "",
                  "| Style | Service | Operation | Namespace | Address | Request → Response | Handler | Source |",
                  "|---|---|---|---|---|---|---|---|"]
        for o in soap:
            req = o["request"] or ", ".join(o.get("params", [])) or "—"
            lines.append(f"| {o['style']} | `{o['service']}` | `{o['operation']}` | {('`' + o['namespace'] + '`') if o['namespace'] else '—'} | "
                         f"{('`' + _cell(o['address']) + '`') if o['address'] else 'not found in the code'} | "
                         f"`{_cell(req)}` → `{_cell(o['response'] or 'void')}` | `{o['handler']}` | `{o['source']}` |")
        wsdls = sorted({o["wsdl"] for o in soap if o.get("wsdl")})
        if wsdls:
            lines += ["", "WSDL: " + ", ".join(f"`{w}`" for w in wsdls)]
        for o in soap:
            if o.get("request_fields") or o.get("response_fields"):
                lines += ["", f"**`{o['operation']}`** — fields from the XSD schema:", "",
                          "| Message | Field | Type | Occurs |", "|---|---|---|---|"]
                lines += [f"| request `{o['request']}` | `{f}` | {t} | {occ} |" for f, t, occ in o["request_fields"]]
                lines += [f"| response `{o['response']}` | `{f}` | {t} | {occ} |" for f, t, occ in o["response_fields"]]
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
    for o in inventory.get("soap", []):
        if o["operation"] not in document and o["handler"].rsplit(".", 1)[-1] not in document:
            missing.append(f"SOAP operation {o['operation']} ({o['handler']})")
    for j in inventory["jobs"]:
        if j["handler"].rsplit(".", 1)[-1] not in document:
            missing.append(f"scheduled job {j['handler']}")
    return missing
