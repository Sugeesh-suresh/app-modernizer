"""
The search engine an application uses (Apache Solr), read from the repository —
no model, no running Solr.

- Version: the SolrJ / Spring Data Solr dependency (Maven properties resolved,
  Gradle coordinates), `luceneMatchVersion` in `solrconfig.xml`, and a `solr:x`
  container image.
- Cores / collections: every folder holding `conf/schema.xml` or
  `conf/managed-schema` (the core's name: `core.properties` `name=`, else the
  folder), with the schema — unique key, fields, dynamic fields, copy fields,
  field types and their analyzers — and the request handlers `solrconfig.xml`
  declares, with their defaults.
- Clients: SolrJ 4 (`HttpSolrServer`, `CloudSolrServer`, `LBHttpSolrServer`,
  `ConcurrentUpdateSolrServer`, `EmbeddedSolrServer`), SolrJ 5+ (`*SolrClient`),
  Spring Data Solr (`SolrTemplate`, `SolrCrudRepository`, `@SolrDocument`), and
  the base URL the configuration gives them.
- Operations: every query (request handler, filter queries, facets, fields,
  sort, paging, highlighting) and every index write (`add`, `addBean(s)`,
  `commit`, `deleteById`, `deleteByQuery`, `optimize`) with its method and line,
  and the HTTP endpoints whose handler reaches a class that talks to Solr.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

_CLIENT = re.compile(r"\b(HttpSolrServer|CloudSolrServer|LBHttpSolrServer|ConcurrentUpdateSolrServer|"
                     r"EmbeddedSolrServer|HttpSolrClient|Http2SolrClient|CloudSolrClient|LBHttpSolrClient|"
                     r"ConcurrentUpdateSolrClient|SolrTemplate|SolrCrudRepository|SolrRepository)\b")
_USES = re.compile(r"\b(?:SolrServer|SolrClient|SolrQuery|SolrTemplate|SolrInputDocument|SolrCrudRepository|"
                   r"QueryResponse)\b|@SolrDocument\b")
_QUERY_PARTS = [
    ("request handler", re.compile(r"setRequestHandler\(\s*\"([^\"]+)\"")),
    ("query", re.compile(r"new\s+SolrQuery\(\s*([^;]{1,120}?)\)\s*;")),
    ("filter query", re.compile(r"(?:addFilterQuery|setFilterQueries)\(\s*([^;]{1,120}?)\)\s*;")),
    ("facet field", re.compile(r"addFacetField\(\s*([^)]{1,80})\)")),
    ("facet query", re.compile(r"addFacetQuery\(\s*([^)]{1,80})\)")),
    ("fields", re.compile(r"(?:setFields|addField)\(\s*([^)]{1,80})\)")),
    ("sort", re.compile(r"(?:addSort|setSort|addSortField)\(\s*([^)]{1,80})\)")),
    ("paging", re.compile(r"(?:setStart|setRows)\(\s*([^;]{1,60})\)")),
    ("highlighting", re.compile(r"setHighlight\w*\(\s*([^)]{0,60})\)")),
]
_WRITES = re.compile(r"\.\s*(add|addBean|addBeans|commit|deleteById|deleteByQuery|optimize|rollback)\s*\(")
_METHOD = re.compile(r"(?:public|protected|private)\s+[\w<>\[\],.? ]+\s+(\w+)\s*\([^)]*\)\s*(?:throws[^{]+)?\{")


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _method_at(text: str, pos: int) -> str:
    name = ""
    for m in _METHOD.finditer(text, 0, pos):
        name = m.group(1)
    return name


def _xml(text: str):
    try:
        return ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", text))
    except ET.ParseError:
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _schema(rel: str, text: str) -> dict:
    root = _xml(text)
    out = {"file": rel, "name": "", "unique_key": "", "fields": [], "dynamic": [], "copy": [], "types": []}
    if root is None:
        return out
    out["name"] = root.get("name", "")
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "uniqueKey":
            out["unique_key"] = (el.text or "").strip()
        elif tag in ("field", "dynamicField") and el.get("name"):
            flags = [k for k in ("indexed", "stored", "required", "multiValued", "docValues")
                     if el.get(k) == "true"]
            row = {"name": el.get("name"), "type": el.get("type", ""), "flags": ", ".join(flags) or "—"}
            (out["fields"] if tag == "field" else out["dynamic"]).append(row)
        elif tag == "copyField":
            out["copy"].append((el.get("source", ""), el.get("dest", "")))
        elif tag == "fieldType" and el.get("name"):
            chain = []
            for a in el.iter():
                if _local(a.tag) in ("tokenizer", "filter", "charFilter") and a.get("class"):
                    chain.append(a.get("class").rsplit(".", 1)[-1])
            out["types"].append({"name": el.get("name"), "class": el.get("class", "").rsplit(".", 1)[-1],
                                 "analysis": " → ".join(chain)})
    return out


def _handlers(rel: str, text: str) -> tuple[list[dict], str]:
    root = _xml(text)
    if root is None:
        return [], ""
    version = ""
    handlers = []
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "luceneMatchVersion":
            version = (el.text or "").strip()
        if tag == "requestHandler" and el.get("name"):
            defaults = []
            for lst in el:
                if _local(lst.tag) == "lst":
                    for item in lst:
                        if item.get("name"):
                            defaults.append(f"{lst.get('name', '')}.{item.get('name')}={(item.text or '').strip()}")
            handlers.append({"name": el.get("name"), "class": el.get("class", "").rsplit(".", 1)[-1],
                             "defaults": "; ".join(defaults[:8]), "where": f"{rel}:{_line(text, text.find(el.get('name')))}"})
    return handlers, version


def _versions(files: list[tuple[str, str]]) -> list[dict]:
    out = []
    for rel, text in files:
        name = PurePosixPath(rel).name
        if name == "pom.xml" and "solr" in text.lower():
            props = dict(re.findall(r"<([\w.-]+)>([^<]+)</\1>", text))
            for m in re.finditer(r"<artifactId>((?:spring-data-)?solr[\w-]*)</artifactId>\s*(?:<version>([^<]+)</version>)?",
                                 text):
                version = m.group(2) or "managed by the parent / BOM"
                version = re.sub(r"\$\{([^}]+)\}", lambda p: props.get(p.group(1), p.group(0)), version)
                out.append({"what": m.group(1), "version": version, "where": f"{rel}:{_line(text, m.start())}"})
        elif name.startswith("build.gradle"):
            for m in re.finditer(r"['\"]org\.(?:apache\.solr|springframework\.data):((?:spring-data-)?solr[\w-]*):?([\w.$-]*)['\"]",
                                 text):
                out.append({"what": m.group(1), "version": m.group(2) or "—", "where": f"{rel}:{_line(text, m.start())}"})
        elif re.match(r"(?:docker-)?compose[\w.-]*\.ya?ml$|Dockerfile", name):
            for m in re.finditer(r"image:\s*['\"]?(solr:[\w.-]+)|FROM\s+(solr:[\w.-]+)", text):
                out.append({"what": "Solr server image", "version": (m.group(1) or m.group(2)).split(":", 1)[1],
                            "where": f"{rel}:{_line(text, m.start())}"})
    return out


def scan(files: list[tuple[str, str]], settings: dict | None = None) -> dict:
    """{} when the repository does not use Solr; else versions, cores, clients, operations."""
    texts = dict(files)
    uses_solr = any(_USES.search(t) for r, t in files if r.endswith((".java", ".kt", ".groovy", ".scala"))) or \
        any(PurePosixPath(r).name in ("solrconfig.xml",) for r, _ in files)
    if not uses_solr:
        return {}
    cores: dict[str, dict] = {}
    for rel, text in files:
        p = PurePosixPath(rel)
        if p.name in ("schema.xml", "managed-schema", "managed-schema.xml") and p.parent.name == "conf":
            core_dir = p.parent.parent
            props = texts.get(str(core_dir / "core.properties"), "")
            m = re.search(r"^name\s*=\s*(\S+)", props, re.M)
            core = m.group(1) if m else core_dir.name
            entry = cores.setdefault(core, {"core": core, "dir": str(core_dir), "schema": None, "handlers": [],
                                            "lucene": "", "config": ""})
            entry["schema"] = _schema(rel, text)
        if p.name == "solrconfig.xml":
            core_dir = p.parent.parent if p.parent.name == "conf" else p.parent
            props = texts.get(str(core_dir / "core.properties"), "")
            m = re.search(r"^name\s*=\s*(\S+)", props, re.M)
            core = m.group(1) if m else core_dir.name
            entry = cores.setdefault(core, {"core": core, "dir": str(core_dir), "schema": None, "handlers": [],
                                            "lucene": "", "config": ""})
            entry["handlers"], entry["lucene"] = _handlers(rel, text)
            entry["config"] = rel
    clients, operations, solr_classes = [], [], set()
    for rel, text in files:
        if not rel.endswith((".java", ".kt", ".groovy", ".scala")) or not _USES.search(text):
            continue
        cls = PurePosixPath(rel).stem
        solr_classes.add(cls)
        for m in _CLIENT.finditer(text):
            if re.search(r"new\s+$|extends\s+$|implements\s+$|@Bean[\s\S]*$", text[max(0, m.start() - 12):m.start()]) \
                    or "import" not in text[max(0, text.rfind("\n", 0, m.start())):m.start()]:
                ctx = text[m.end():m.end() + 160]
                url = re.search(r"\(\s*(\"[^\"]+\"|[\w.]+)", ctx)
                target = url.group(1) if url and m.group(1).startswith(("Http", "Cloud", "LB", "Concurrent")) else ""
                bound = re.search(rf"@Value\(\s*\"\$\{{([^}}:]+)[^\"]*\"\s*\)\s*(?:final\s+)?String\s+{re.escape(target)}\b",
                                  text) if re.fullmatch(r"\w+", target or "-") else None
                if bound:
                    target = f"{target} = ${{{bound.group(1)}}}"
                clients.append({"client": m.group(1), "target": target, "where": f"{rel}:{_line(text, m.start())}"})
        for m in re.finditer(r"new\s+SolrQuery\s*\(", text):
            end = text.find("\n    }", m.start())
            block = text[m.start(): end if end != -1 else m.start() + 1500]
            parts = []
            for label, pattern in _QUERY_PARTS:
                for q in pattern.finditer(block):
                    parts.append(f"{label}: `{' '.join(q.group(1).split())[:100]}`")
            operations.append({"kind": "query", "method": f"{cls}.{_method_at(text, m.start())}",
                               "detail": "; ".join(dict.fromkeys(parts)), "where": f"{rel}:{_line(text, m.start())}"})
        for m in _WRITES.finditer(text):
            before = text[max(0, m.start() - 40):m.start()]
            if not re.search(r"\b(?:solr|server|client|solrServer|solrClient|template)\w*\s*$", before, re.I):
                continue
            operations.append({"kind": f"index write: {m.group(1)}", "method": f"{cls}.{_method_at(text, m.start())}",
                               "detail": "", "where": f"{rel}:{_line(text, m.start())}"})
    # Dedupe client rows (one per class and line).
    seen, uniq = set(), []
    for c in clients:
        key = (c["client"], c["where"])
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    urls = []
    for key, values in (settings or {}).items():
        if re.search(r"solr", key, re.I) and not key.startswith("services."):     # compose services: setup facts
            urls += [{"key": key, "value": v, "where": w} for v, w in values]
    return {"versions": _versions(files), "cores": sorted(cores.values(), key=lambda c: c["core"]),
            "clients": uniq, "operations": operations, "classes": sorted(solr_classes), "config": urls}


_FIELD = re.compile(r"(?:private|protected|public)?\s*(?:final\s+)?([A-Z]\w*)(?:<[^>]*>)?\s+(\w+)\s*[;=]")


def _fields(text: str) -> dict[str, str]:
    """{field or parameter name: its type} declared in a class."""
    return {name: typ for typ, name in _FIELD.findall(text)}


def _method_body(text: str, method: str) -> str:
    m = re.search(rf"\b{re.escape(method)}\s*\([^)]*\)[^{{;]*\{{", text)
    if not m:
        return ""
    depth, i = 1, m.end()
    while i < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[m.end():i]


def backed_endpoints(search: dict, endpoints: list[dict], files: list[tuple[str, str]]) -> list[dict]:
    """HTTP endpoints whose handler method reaches Solr: it uses a Solr type itself, or calls a
    field whose class does — directly or through other classes (`ReindexJob` → search service)."""
    if not search:
        return []
    texts = {PurePosixPath(r).stem: t for r, t in files if r.endswith((".java", ".kt"))}
    reaching = {c: c for c in search.get("classes", [])}          # class → the Solr class it reaches
    for _ in range(4):                                           # a few hops of "holds a field of type"
        for cls, text in texts.items():
            if cls in reaching:
                continue
            for typ in _fields(text).values():
                if typ in reaching and typ != cls:
                    reaching[cls] = typ
                    break
    out = []
    for e in endpoints:
        cls, method = e["handler"].rsplit(".", 1)
        text = texts.get(cls, "")
        body = _method_body(text, method)
        fields = _fields(text)
        via = sorted({typ for name, typ in fields.items() if typ in reaching and typ != cls
                      and re.search(rf"\b{re.escape(name)}\s*\.", body)})
        if via or (cls in search.get("classes", []) and _USES.search(body)):
            out.append({"endpoint": f"{e['verb']} {e['path']}", "handler": e["handler"],
                        "via": ", ".join(f"{v} → {reaching[v]}" if reaching[v] != v else v for v in via) or "directly",
                        "source": e["source"]})
    return out


def _cell(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).replace("|", "\\|").strip() or "—"


def to_markdown(search: dict, backed: list[dict] | None = None) -> str:
    if not search:
        return ""
    lines = ["### Search Engine — Apache Solr (computed)", "",
             "_Read from the repository's Solr configuration, build files and code by the pipeline (no model)._", ""]
    if search["versions"]:
        lines += ["#### Versions", "", "| Component | Version | Where |", "|---|---|---|"]
        lines += [f"| `{v['what']}` | {_cell(v['version'])} | `{v['where']}` |" for v in search["versions"]]
        lines.append("")
    if search["config"] or search["clients"]:
        lines += ["#### Clients and connection", "", "| Client | Target / setting | Where |", "|---|---|---|"]
        lines += [f"| `{c['client']}` | {('`' + _cell(c['target']) + '`') if c['target'] else '—'} | `{c['where']}` |"
                  for c in search["clients"]]
        lines += [f"| configuration `{c['key']}` | `{_cell(c['value'])}` | `{c['where']}` |" for c in search["config"]]
        lines.append("")
    for core in search["cores"]:
        lines += [f"#### Core `{core['core']}` (`{core['dir']}`)", ""]
        if core["lucene"]:
            lines.append(f"- `luceneMatchVersion`: {core['lucene']} (`{core['config']}`)")
        sc = core["schema"]
        if sc:
            lines.append(f"- Schema `{sc['file']}`" + (f" (name `{sc['name']}`)" if sc["name"] else "")
                         + (f", unique key `{sc['unique_key']}`" if sc["unique_key"] else ""))
            lines += ["", "| Field | Type | Flags |", "|---|---|---|"]
            lines += [f"| `{f['name']}` | `{f['type']}` | {f['flags']} |" for f in sc["fields"]]
            lines += [f"| `{f['name']}` (dynamic) | `{f['type']}` | {f['flags']} |" for f in sc["dynamic"]]
            if sc["copy"]:
                lines += ["", "Copy fields: " + ", ".join(f"`{s}` → `{d}`" for s, d in sc["copy"])]
            if sc["types"]:
                lines += ["", "| Field type | Class | Analysis chain |", "|---|---|---|"]
                lines += [f"| `{t['name']}` | `{t['class']}` | {_cell(t['analysis'])} |" for t in sc["types"]]
        if core["handlers"]:
            lines += ["", "| Request handler | Class | Defaults | Where |", "|---|---|---|---|"]
            lines += [f"| `{h['name']}` | `{h['class']}` | {_cell(h['defaults'])} | `{h['where']}` |"
                      for h in core["handlers"]]
        lines.append("")
    if search["operations"]:
        lines += ["#### Queries and index writes in the code", "", "| Operation | Method | Detail | Where |",
                  "|---|---|---|---|"]
        lines += [f"| {o['kind']} | `{o['method']}` | {_cell(o['detail'])} | `{o['where']}` |"
                  for o in search["operations"]]
        lines.append("")
    if backed:
        lines += ["#### HTTP endpoints backed by Solr", "", "| Endpoint | Handler | Via | Source |", "|---|---|---|---|"]
        lines += [f"| `{b['endpoint']}` | `{b['handler']}` | {b['via'] if b['via'] == 'directly' else '`' + b['via'] + '`'} "
                  f"| `{b['source']}` |" for b in backed]
        lines.append("")
    return "\n".join(lines).rstrip()
