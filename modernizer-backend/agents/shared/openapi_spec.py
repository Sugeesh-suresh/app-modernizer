"""
An OpenAPI 3.0 specification of the repository's HTTP interface — generated from
the computed Endpoint Contracts (shared/ui_contracts.py), no model involved.

Every endpoint of the Interface & Job Inventory is a path operation with:
parameters (path, query, header, cookie) with type, required, default and the
bean-validation constraints as schema keywords; the request body (JSON, form or
multipart) as a schema built from its flattened fields (`items[].sku`); the
response schema, the HTTP statuses the handler sets and each exception mapped
to a status; the access rule (`@PreAuthorize`, `@RolesAllowed`, …) as an
`x-access-rule` extension and in the description; the source location as
`x-source`. Server-rendered page endpoints are included under the `Pages` tag
with a `text/html` response, so the whole HTTP surface is in one file.

The document is plain OpenAPI 3.0.3 — it loads in Swagger UI / Swagger Editor,
Postman, Stoplight and code generators as it is.
"""
from __future__ import annotations

import json
import re

_TYPES = {
    "string": {"type": "string"}, "integer": {"type": "integer", "format": "int32"},
    "integer (64-bit)": {"type": "integer", "format": "int64"}, "number": {"type": "number"},
    "decimal": {"type": "number"}, "boolean": {"type": "boolean"},
    "date": {"type": "string", "format": "date"}, "date-time": {"type": "string", "format": "date-time"},
    "time": {"type": "string", "format": "time"}, "uuid": {"type": "string", "format": "uuid"},
    "file": {"type": "string", "format": "binary"}, "binary": {"type": "string", "format": "binary"},
    "any": {}, "any JSON": {}, "empty": {},
}
_STATUS = re.compile(r"\b([1-5]\d\d)\b")
_MIN = re.compile(r"@(?:Min|DecimalMin|Positive(OrZero)?)\b(?:\(\s*(?:value\s*=\s*)?\"?(-?[\d.]+)\"?)?")
_MAX = re.compile(r"@(?:Max|DecimalMax|Negative(OrZero)?)\b(?:\(\s*(?:value\s*=\s*)?\"?(-?[\d.]+)\"?)?")
_SIZE = re.compile(r"@(?:Size|Length)\s*\(([^)]*)\)")
_PATTERN = re.compile(r"@Pattern\s*\(\s*(?:regexp\s*=\s*)?\"((?:[^\"\\]|\\.)*)\"")


def schema_of(type_label: str) -> dict:
    """A schema for one of the contract's type labels ("integer (64-bit)", "enum: A | B",
    "list of string", "map of string → integer", a class name...)."""
    t = (type_label or "").strip()
    base = t.split(" (")[0] if t.startswith(("integer (zero", "integer (")) and t != "integer (64-bit)" else t
    if base in _TYPES:
        return dict(_TYPES[base])
    if t.startswith("enum:"):
        values = [v.strip() for v in t[5:].split("|") if v.strip()]
        return {"type": "string", "enum": values}
    for prefix in ("list of ", "array of ", "set of "):
        if t.startswith(prefix):
            return {"type": "array", "items": schema_of(t[len(prefix):])}
    if t.startswith("map of "):
        value = t.split("→", 1)[1].strip() if "→" in t else "any"
        return {"type": "object", "additionalProperties": schema_of(value) or True}
    if t in ("list", "array"):
        return {"type": "array", "items": {}}
    if t in ("map", "object"):
        return {"type": "object"}
    return {"type": "object", "description": f"`{t}`"} if t else {}


def _constraints(schema: dict, constraints: str) -> bool:
    """Bean-validation constraints as schema keywords; True when the field is required."""
    c = constraints or ""
    m = _MIN.search(c)
    if m:
        if m.group(2):
            schema["minimum"] = float(m.group(2)) if "." in m.group(2) else int(m.group(2))
        elif "Positive" in m.group(0):
            schema["minimum"] = 0 if m.group(1) else 1
    m = _MAX.search(c)
    if m:
        if m.group(2):
            schema["maximum"] = float(m.group(2)) if "." in m.group(2) else int(m.group(2))
        elif "Negative" in m.group(0):
            schema["maximum"] = 0 if m.group(1) else -1
    m = _SIZE.search(c)
    if m:
        lo = re.search(r"\bmin\s*=\s*(\d+)", m.group(1))
        hi = re.search(r"\bmax\s*=\s*(\d+)", m.group(1))
        key = ("minItems", "maxItems") if schema.get("type") == "array" else ("minLength", "maxLength")
        if lo:
            schema[key[0]] = int(lo.group(1))
        if hi:
            schema[key[1]] = int(hi.group(1))
    m = _PATTERN.search(c)
    if m:
        schema["pattern"] = m.group(1).replace("\\\\", "\\")
    if "@Email" in c:
        schema["format"] = "email"
    if "@NotBlank" in c or "@NotEmpty" in c:
        if schema.get("type") == "array":
            schema.setdefault("minItems", 1)
        else:
            schema.setdefault("minLength", 1)
    if c and not schema.get("description"):
        schema["description"] = f"Constraints in code: {c}"
    return bool(re.search(r"@(?:NotNull|NotBlank|NotEmpty)\b", c))


def object_schema(fields: list) -> dict:
    """Flattened fields `[(path, type, constraints|note), ...]` → one nested schema.
    `items[].sku` nests an array; a path starting with `[]` makes the root an array."""
    root: dict = {}

    def node_for(path_parts: list[str], holder: dict) -> dict:
        cur = holder
        for part in path_parts:
            is_array = part.endswith("[]")
            name = part[:-2] if is_array else part
            if name:
                cur.setdefault("type", "object")
                props = cur.setdefault("properties", {})
                cur = props.setdefault(name, {})
            if is_array:
                cur["type"] = "array"
                cur = cur.setdefault("items", {})
        return cur

    for item in fields or []:
        path, type_label, note = (list(item) + ["", "", ""])[:3]
        if not path or path == "(body)":
            leaf = schema_of(type_label)
            root.update(leaf)
            if note:
                _constraints(root, note)
            continue
        parts = [p for p in re.split(r"\.(?![^\[]*\])", path) if p != ""]
        *parents, last = parts
        parent = node_for(parents, root)
        is_array = last.endswith("[]")
        name = last[:-2] if is_array else last
        if name:
            parent.setdefault("type", "object")
            props = parent.setdefault("properties", {})
            target = props.setdefault(name, {})
        else:
            parent["type"] = "array"
            target = parent.setdefault("items", {})
        leaf = schema_of(type_label)
        if is_array and name:
            target["type"] = "array"
            target.setdefault("items", {}).update(leaf)
            dest = target["items"]
        else:
            for k, v in leaf.items():
                if k not in target or k == "type" and target.get("type") not in ("object", "array"):
                    target[k] = v
            dest = target
        if note and note not in ("Spring Data page",):
            if _constraints(dest, note) and name:
                req = parent.setdefault("required", [])
                if name not in req:
                    req.append(name)
        elif note:
            dest.setdefault("description", note)
    return root


def _component_name(type_text: str) -> str:
    """`ResponseEntity<List<OrderDto>>` → `OrderDtoList`; `Page<X>` → `XPage`."""
    t = re.sub(r"\s+", "", type_text or "")
    t = re.sub(r"^(?:ResponseEntity|Optional|Mono|Flux|CompletableFuture|HttpEntity|DeferredResult)<(.*)>$", r"\1", t)
    inner = re.findall(r"[A-Za-z_]\w*", t)
    if not inner:
        return ""
    head, rest = inner[0], inner[1:]
    if head in ("List", "Set", "Collection", "Iterable", "Page", "Slice") and rest:
        return rest[-1] + ("Page" if head in ("Page", "Slice") else "List")
    return "".join(inner) if len(inner) > 1 else head


def _status_code(text: str) -> str:
    m = _STATUS.search(text or "")
    return m.group(1) if m else ""


def _operation_id(handler: str, verb: str, seen: set) -> str:
    base = re.sub(r"[^A-Za-z0-9_]", "_", handler.replace(".", "_")) or verb.lower()
    op, n = base, 2
    while op in seen:
        op, n = f"{base}_{n}", n + 1
    seen.add(op)
    return op


def build(contracts: list[dict], title: str, version: str = "as-is", description: str = "",
          servers: list[str] | None = None) -> dict:
    """The OpenAPI 3.0.3 document for these endpoint contracts."""
    paths: dict = {}
    components: dict = {}
    tags: dict[str, str] = {}
    op_ids: set = set()
    for c in contracts:
        verb, _, path = c["endpoint"].partition(" ")
        verb = verb.lower()
        if verb not in ("get", "post", "put", "delete", "patch", "head", "options", "trace"):
            verb = "get"
        path = path or "/"
        path = re.sub(r"\{([^}:]+):[^}]*\}", r"{\1}", path)          # Spring {id:\\d+} → {id}
        handler = c.get("handler", "")
        cls = handler.rsplit(".", 1)[0] if "." in handler else handler
        page = c.get("kind") == "page"
        tag = "Pages" if page else (cls or "Default")
        tags.setdefault(tag, "Server-rendered pages (HTML)" if page else f"Handled by `{cls}`")
        op: dict = {"tags": [tag], "operationId": _operation_id(handler or path, verb, op_ids),
                    "summary": f"{c['endpoint']}" + (f" — {handler}" if handler else ""),
                    "x-source": c.get("source", "")}
        notes = []
        if c.get("access"):
            op["x-access-rule"] = c["access"]
            notes.append(f"Access rule: `{c['access']}`.")
        if c.get("called_by"):
            op["x-ui-callers"] = c["called_by"]
        if c.get("validation"):
            notes += [f"Validation: {v}." for v in c["validation"]]
        if page and c.get("view"):
            notes.append(f"Renders view `{c['view']}`.")
        if c.get("redirects"):
            notes.append("Redirects: " + ", ".join(f"`{r}`" for r in c["redirects"]) + ".")
        if c.get("model_fields") or c.get("model"):
            notes.append("Model attributes for the view: " + ", ".join(
                f"`{m[0] if isinstance(m, (list, tuple)) else m}`" for m in (c.get("model") or [])) + ".")
        if notes:
            op["description"] = "\n\n".join(notes)
        params = []
        declared = set()
        for p in c.get("params", []):
            where = p.get("in", "query")
            if where not in ("path", "query", "header", "cookie"):
                continue
            s = schema_of(p.get("type", "string")) or {"type": "string"}
            if p.get("default"):
                d = p["default"]
                s["default"] = (int(d) if re.fullmatch(r"-?\d+", d) and s.get("type") == "integer" else
                                (d.lower() == "true") if s.get("type") == "boolean" and d.lower() in ("true", "false")
                                else d)
            _constraints(s, p.get("constraints", ""))
            s.pop("description", None)
            param = {"name": p["name"], "in": where, "required": where == "path" or p.get("required") == "yes",
                     "schema": s}
            if p.get("constraints"):
                param["description"] = f"Constraints in code: {p['constraints']}"
            params.append(param)
            declared.add((p["name"], where))
        for name in re.findall(r"\{([^}]+)\}", path):
            if (name, "path") not in declared:
                params.append({"name": name, "in": "path", "required": True, "schema": {"type": "string"}})
        if params:
            op["parameters"] = params
        if c.get("body"):
            body_schema = object_schema(c["body"])
            comp = _component_name(c.get("body_type", ""))
            if comp and body_schema.get("type") == "object" and comp not in components:
                components[comp] = body_schema
            ref = {"$ref": f"#/components/schemas/{comp}"} if comp and comp in components else body_schema
            body_in = (c.get("body_in") or "").lower()
            media = ("multipart/form-data" if "multipart" in body_in or any(
                "file" in (f[1] if len(f) > 1 else "") for f in c["body"]) else
                     "application/x-www-form-urlencoded" if "form" in body_in else
                     c.get("consumes") or "application/json")
            op["requestBody"] = {"required": True, "content": {media: {"schema": ref}}}
        responses: dict = {}
        ok_codes = [_status_code(s) for s in c.get("statuses", []) if _status_code(s)]
        success = next((s for s in ok_codes if s.startswith("2")), "200")
        if page:
            responses[success] = {"description": f"HTML page" + (f" (view `{c['view']}`)" if c.get("view") else ""),
                                  "content": {"text/html": {"schema": {"type": "string"}}}}
            if c.get("redirects"):
                responses.setdefault("302", {"description": "Redirect: " + ", ".join(c["redirects"])})
        else:
            resp_schema = object_schema(c.get("response") or []) if c.get("response") else \
                schema_of(c.get("response_type", "")) if c.get("response_type") and \
                c["response_type"] not in ("void", "Void", "ResponseEntity<Void>") else {}
            comp = _component_name(c.get("response_type", ""))
            if resp_schema and comp and resp_schema.get("type") == "object" and resp_schema.get("properties"):
                components.setdefault(comp, resp_schema)
                resp_schema = {"$ref": f"#/components/schemas/{comp}"}
            elif resp_schema.get("type") == "array" and (resp_schema.get("items") or {}).get("properties") \
                    and comp.endswith("List"):
                components.setdefault(comp[:-4], resp_schema["items"])
                resp_schema = {"type": "array", "items": {"$ref": f"#/components/schemas/{comp[:-4]}"}}
            entry = {"description": "Success" if success != "204" else "No content"}
            if resp_schema and success != "204":
                entry["content"] = {c.get("produces") or "application/json": {"schema": resp_schema}}
            responses[success] = entry
        for code in ok_codes:
            responses.setdefault(code, {"description": next(s for s in c["statuses"] if code in s)})
        for exc, mapped in c.get("errors", []):
            code = _status_code(mapped) or "500"
            prev = responses.get(code, {}).get("description", "")
            text = f"`{exc}` → {mapped}"
            responses[code] = {"description": f"{prev}; {text}" if prev and text not in prev else (prev or text)}
        if c.get("access"):
            responses.setdefault("401", {"description": "Not authenticated (access rule in code)"})
            responses.setdefault("403", {"description": "Not authorised: " + c["access"]})
        if any(v.startswith("the form object is validated") or "@Valid" in v for v in c.get("validation", [])) \
                and not page:
            responses.setdefault("400", {"description": "Request failed validation"})
        op["responses"] = dict(sorted(responses.items()))
        paths.setdefault(path, {})[verb] = op
    doc = {
        "openapi": "3.0.3",
        "info": {"title": title, "version": version,
                 "description": description or (
                     "Generated from the repository's code by the Stella Modernizer (no model): every HTTP endpoint "
                     "with its parameters, request and response fields, statuses, mapped exceptions and access rules "
                     "as the code declares them. `x-source` gives the handler's file and line.")},
        "servers": [{"url": s} for s in (servers or ["/"])],
        "tags": [{"name": k, "description": v} for k, v in sorted(tags.items())],
        "paths": dict(sorted(paths.items())),
    }
    if components:
        doc["components"] = {"schemas": dict(sorted(components.items()))}
    return doc


def to_json(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def to_yaml(doc: dict) -> str:
    import yaml

    class _Dumper(yaml.SafeDumper):
        pass

    _Dumper.add_representer(str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s,
                                                                  style="|" if "\n" in s else None))
    return yaml.dump(doc, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=120)


def servers_from_config(settings: dict[str, list[tuple[str, str]]]) -> list[str]:
    """Base URLs from server.port / server.servlet.context-path when the repository sets them."""
    port = next((v for v, _ in settings.get("server.port", []) if v.strip().isdigit()), "")
    ctx = next((v for v, _ in settings.get("server.servlet.context-path", [])
                + settings.get("server.context-path", []) if v.startswith("/")), "")
    if port or ctx:
        return [f"http://localhost:{port or 8080}{ctx.rstrip('/')}"]
    return ["/"]
