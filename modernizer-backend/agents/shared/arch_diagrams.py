"""
Architecture diagrams for the Technical Specification: the Enterprise
Architect agent declares them, the pipeline checks and draws them.

The agent answers with a JSON spec (skill `architecture-diagrams`): high-level
diagrams (system context, containers / deployment) and low-level ones
(components, request sequences, data model), each a list of nodes and edges —
or, for a sequence, participants and numbered steps. It draws nothing itself.

Then, with no model involved:

1. **Check** (`validate`). Every node, edge and step must cite at least one
   source the pipeline knows — an evidence id (`EV-…`) of a verified item, or a
   computed fact (`stack:java`, `endpoint:GET /api/jobs`, `handler:JobApi.search`,
   `module:pds-service`, `config:spring.datasource.url`, `UI-007`). A name
   written like code (`OrderService`, `orders.queue`, `/api/jobs`) must appear in
   what it cites or in the computed facts; a label must share a key word with
   what it cites; numbers must appear there too. Edges whose ends were dropped go
   with them. What fails is left out and listed in the audit file with the reason.
2. **Draw** (`render`). A layered left-to-right layout (cycles broken, long
   edges routed through bend points, crossings reduced by barycentre sweeps),
   one shape per kind of element (actor, system, container, component,
   database, queue, external system, UI, entity with its fields), labelled
   arrows; sequences as lifelines with numbered messages. The same spec always
   gives the same picture. PNG through Pillow; without Pillow, the same diagram
   as plain text.
3. **Document** (`to_markdown`). Each diagram is an image under "Architecture
   Diagrams" (High-level design / Low-level design) followed by the table of its
   elements and what each rests on, so the Markdown reads without the image.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .grounding import code_vocabulary, significant_words, unsupported_values

HEADING = "## Architecture Diagrams"
KINDS = ("context", "container", "deployment", "component", "sequence", "data")
NODE_TYPES = ("actor", "system", "container", "component", "database", "queue", "external", "ui", "entity",
              "file", "job")
_EV = re.compile(r"\bEV-[a-z0-9]+(?:-[a-z0-9]+)*-\d{4}\b")
_UI = re.compile(r"^UI-\d{3,}$")
_CODE_NAME = re.compile(r"(?:[A-Za-z_]\w*\.)+[A-Za-z_]\w*|[a-z]+[A-Z]\w*|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+|"
                        r"\w+_\w+|/[\w{}/.-]+")
_ID = re.compile(r"^(?:HLD|LLD)-\d{1,3}$")


# ── the spec ────────────────────────────────────────────────────────────────

@dataclass
class Node:
    id: str
    label: str
    type: str = "component"
    detail: str = ""
    group: str = ""
    fields: list = field(default_factory=list)
    sources: list = field(default_factory=list)


@dataclass
class Edge:
    source: str
    target: str
    label: str = ""
    sources: list = field(default_factory=list)


@dataclass
class Diagram:
    id: str
    level: str                 # high | low
    kind: str
    title: str
    description: str = ""
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)     # for a sequence: the steps, in order
    image: str = ""


def parse(text: str) -> tuple[list[dict], str]:
    """The agent's answer → (raw diagram dicts, problem). Takes the first JSON object
    with a "diagrams" list, in a ```json fence or bare."""
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.S)
    start = (text or "").find("{")
    if start >= 0:
        candidates.append(text[start:text.rfind("}") + 1])
    for raw in candidates:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("diagrams"), list):
            return [d for d in data["diagrams"] if isinstance(d, dict)], ""
    return [], "the answer holds no JSON object with a \"diagrams\" list"


# ── the check ───────────────────────────────────────────────────────────────

@dataclass
class Facts:
    """What a diagram element may cite besides evidence: the computed facts."""
    refs: set = field(default_factory=set)        # "stack:java", "endpoint:GET /api/jobs", "UI-007", …
    text: str = ""                                # every computed section, for names written like code

    @staticmethod
    def build(stacks: list[str], endpoints: list[dict], modules: list[str], config_keys: list[str],
              ui_ids: list[str], text: str) -> "Facts":
        refs = {f"stack:{s}" for s in stacks}
        for e in endpoints:
            refs.add(f"endpoint:{e['verb']} {e['path']}")
            refs.add(f"handler:{e['handler']}")
            refs.add(f"handler:{e['handler'].split('.')[0]}")
        refs |= {f"module:{m}" for m in modules}
        refs |= {f"config:{k}" for k in config_keys}
        refs |= set(ui_ids)
        return Facts(refs, text)


def _norm_ref(ref: str) -> str:
    ref = str(ref).strip().strip("`")
    m = re.match(r"^(endpoint):\s*([A-Z]+)\s+(\S+)$", ref)
    return f"endpoint:{m.group(2)} {m.group(3)}" if m else ref


def _grounded(item_text: str, sources: list, evidence: dict[str, str], facts: Facts) -> tuple[list[str], str]:
    """(the valid sources, the reason it fails or "")."""
    valid, cited = [], []
    for ref in sources or []:
        ref = _norm_ref(ref)
        if _EV.fullmatch(ref):
            if ref in evidence:
                valid.append(ref)
                cited.append(evidence[ref])
        elif ref in facts.refs:
            valid.append(ref)
            cited.append(ref.split(":", 1)[-1])
    if not valid:
        return [], "it cites no evidence item or computed fact the pipeline knows"
    vocabulary = "\n".join(cited) + "\n" + facts.text
    unknown = [n for n in _CODE_NAME.findall(item_text)
               if n.strip("/") and n not in vocabulary and n.split(".")[-1] not in vocabulary]
    if unknown:
        return [], f"`{unknown[0]}` appears neither in what it cites nor in the computed facts"
    words = significant_words(item_text)
    if words and any(_EV.fullmatch(v) for v in valid):
        prefixes = {w[:4] for w in code_vocabulary("\n".join(cited))}       # "save" matches "saves"
        if not any(w[:4] in prefixes for w in words) and not any(f.split(":", 1)[-1] in item_text
                                                                 for f in valid if not _EV.fullmatch(f)):
            return [], "its label shares no key word with what it cites"
    problems = unsupported_values(item_text, vocabulary)
    if problems:
        return [], problems[0]
    return valid, ""


def validate(raw: list[dict], evidence: dict[str, str], facts: Facts) -> tuple[list[Diagram], list[tuple[str, str]]]:
    """Diagrams with every element traceable, numbered HLD-n / LLD-n, and [(what, why)] left out."""
    out: list[Diagram] = []
    rejected: list[tuple[str, str]] = []
    counters = {"high": 0, "low": 0}
    for d in raw:
        kind = str(d.get("kind", "")).lower()
        if kind not in KINDS:
            kind = "component"
        level = "high" if str(d.get("level", "")).lower().startswith("h") or kind in ("context", "container",
                                                                                       "deployment") \
            and str(d.get("level", "")).lower() not in ("low", "lld") else "low"
        title = str(d.get("title") or kind.title()).strip()[:120]
        where = f"diagram “{title}”"
        nodes: dict[str, Node] = {}
        for n in d.get("nodes") or d.get("participants") or []:
            if not isinstance(n, dict) or not n.get("id"):
                continue
            node = Node(str(n["id"]), str(n.get("label") or n["id"])[:80],
                        str(n.get("type", "component")).lower() if str(n.get("type", "")).lower() in NODE_TYPES
                        else "component", str(n.get("detail") or "")[:120], str(n.get("group") or "")[:60],
                        [str(f)[:60] for f in (n.get("fields") or []) if str(f).strip()],
                        list(n.get("sources") or []))
            text = " ".join([node.label, node.detail, *node.fields])
            valid, why = _grounded(text, node.sources, evidence, facts)
            if why:
                rejected.append((f"{where}: node “{node.label}”", why))
                continue
            node.sources = valid
            nodes.setdefault(node.id, node)
        edges: list[Edge] = []
        for e in d.get("edges") or d.get("steps") or []:
            if not isinstance(e, dict):
                continue
            a, b = str(e.get("from", "")), str(e.get("to", ""))
            label = str(e.get("label") or "")[:80]
            if a not in nodes or b not in nodes:
                rejected.append((f"{where}: {a} → {b} “{label}”", "an end of it is not a node of the diagram "
                                 "(or that node was left out)"))
                continue
            valid, why = _grounded(label, list(e.get("sources") or []), evidence, facts)
            if why:
                rejected.append((f"{where}: {nodes[a].label} → {nodes[b].label} “{label}”", why))
                continue
            edges.append(Edge(a, b, label, valid))
        if len(nodes) < 2 or (kind != "data" and not edges):
            rejected.append((where, "fewer than two traceable elements, or nothing connecting them"))
            continue
        counters[level] += 1
        out.append(Diagram(f"{'HLD' if level == 'high' else 'LLD'}-{counters[level]}", level, kind, title,
                           str(d.get("description") or "")[:400], list(nodes.values()), edges))
    return out, rejected


# ── drawing ─────────────────────────────────────────────────────────────────

_FILL = {"actor": "#e8f1e9", "system": "#e3edf7", "container": "#e3edf7", "component": "#eef0f8",
         "database": "#fbf1dd", "queue": "#f6e7f2", "external": "#f3f3f3", "ui": "#e6f3f2", "entity": "#fbf7ea",
         "file": "#f3f3f3", "job": "#efeaf8"}
_STROKE = {"actor": "#3c7a4a", "system": "#2f5f8f", "container": "#2f5f8f", "component": "#4a5590",
           "database": "#a8741c", "queue": "#94457f", "external": "#666666", "ui": "#2a7d77", "entity": "#8a7a2c",
           "file": "#666666", "job": "#5f4a99"}
_STEREOTYPE = {"actor": "actor", "system": "system", "container": "container", "component": "component",
               "database": "database", "queue": "queue / topic", "external": "external system", "ui": "user interface",
               "entity": "entity", "file": "file", "job": "scheduled job"}
SCALE = 2


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    names = (["DejaVuSans-Bold.ttf", "arialbd.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf"] if bold else
             ["DejaVuSans.ttf", "arial.ttf", "LiberationSans-Regular.ttf", "Arial.ttf"])
    for name in names:
        try:
            return ImageFont.truetype(name, size * SCALE)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size * SCALE)
    except TypeError:                                   # Pillow < 10.1
        return ImageFont.load_default()


def _wrap(text: str, font, width: int) -> list[str]:
    lines, cur = [], ""
    for word in (text or "").split():
        trial = f"{cur} {word}".strip()
        if font.getlength(trial) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    out = []
    for line in lines:                                  # a single word wider than the box: cut it
        while font.getlength(line) > width and len(line) > 4:
            cut = len(line)
            while cut > 4 and font.getlength(line[:cut] + "…") > width:
                cut -= 1
            out.append(line[:cut] + "…" if cut < len(line) else line)
            line = line[cut:]
            if not line:
                break
        if line:
            out.append(line)
    return out


@dataclass
class _Box:
    node: Node
    w: int
    h: int
    lines: list
    detail: list
    x: int = 0
    y: int = 0


def _measure(node: Node, fonts: dict) -> _Box:
    inner = 200 * SCALE
    title = _wrap(node.label, fonts["bold"], inner)
    detail = _wrap(node.detail, fonts["small"], inner) if node.detail else []
    if node.type == "entity":
        detail = [f[:40] for f in node.fields]
    w = max([fonts["bold"].getlength(t) for t in title] + [fonts["small"].getlength(t) for t in detail]
            + [fonts["tiny"].getlength(f"«{_STEREOTYPE[node.type]}»"), 120 * SCALE]) + 28 * SCALE
    line_h = 17 * SCALE
    h = 22 * SCALE + len(title) * line_h + len(detail) * 15 * SCALE + 14 * SCALE
    if node.type == "database":
        h += 16 * SCALE
    if node.type == "entity" and detail:
        h += 8 * SCALE
    return _Box(node, int(w), int(h), title, detail)


def _layers(nodes: list[Node], edges: list[Edge]) -> dict[str, int]:
    """Longest-path layering over the graph with its cycles broken (back edges ignored)."""
    ids = [n.id for n in nodes]
    out_edges = {i: [] for i in ids}
    for e in edges:
        if e.source != e.target:
            out_edges[e.source].append(e.target)
    order, state, back = [], {}, set()

    def dfs(v):
        state[v] = 1
        for w in out_edges[v]:
            if state.get(w) == 1:
                back.add((v, w))
            elif w not in state:
                dfs(w)
        state[v] = 2
        order.append(v)
    for i in ids:
        if i not in state:
            dfs(i)
    layer = {i: 0 for i in ids}
    for v in reversed(order):
        for w in out_edges[v]:
            if (v, w) not in back:
                layer[w] = max(layer[w], layer[v] + 1)
    return layer


def _layout(diagram: Diagram, fonts: dict):
    boxes = {n.id: _measure(n, fonts) for n in diagram.nodes}
    layer = _layers(diagram.nodes, diagram.edges)
    # Long edges get a bend point in every layer they cross.
    columns: dict[int, list] = {}
    for n in diagram.nodes:
        columns.setdefault(layer[n.id], []).append(n.id)
    routes = []
    dummy = 0
    for e in diagram.edges:
        a, b = (e.source, e.target) if layer[e.source] <= layer[e.target] else (e.target, e.source)
        path = [a]
        for lyr in range(layer[a] + 1, layer[b]):
            name = f"__d{dummy}"
            dummy += 1
            columns.setdefault(lyr, []).append(name)
            layer[name] = lyr
            path.append(name)
        path.append(b)
        routes.append((e, path, layer[e.source] > layer[e.target]))
    neighbours: dict[str, list] = {}
    for _, path, _ in routes:
        for u, v in zip(path, path[1:]):
            neighbours.setdefault(u, []).append(v)
            neighbours.setdefault(v, []).append(u)
    # Barycentre sweeps to reduce crossings.
    for sweep in range(6):
        rng = range(1, max(columns) + 1) if sweep % 2 == 0 else range(max(columns) - 1, -1, -1)
        for c in rng:
            ref = c - 1 if sweep % 2 == 0 else c + 1
            if ref not in columns:
                continue
            pos = {v: i for i, v in enumerate(columns[ref])}
            here = {v: i for i, v in enumerate(columns[c])}

            def key(v, pos=pos, here=here):
                ns = [pos[u] for u in neighbours.get(v, []) if u in pos]
                return (sum(ns) / len(ns) if ns else here[v], here[v])
            columns[c].sort(key=key)
    gap_y, margin = 28 * SCALE, 30 * SCALE
    # Each gap between columns is as wide as the widest label drawn in it.
    gaps: dict[int, float] = {}
    for edge, path, reversed_ in routes:
        at = layer[path[-2]] if reversed_ else layer[path[0]]
        gaps[at] = max(gaps.get(at, 0), fonts["label"].getlength(edge.label) + 40 * SCALE)
    top = 70 * SCALE
    heights = {c: sum(boxes[v].h if v in boxes else 10 * SCALE for v in vs) + gap_y * (len(vs) - 1)
               for c, vs in columns.items()}
    tallest = max(heights.values())
    x = margin
    points: dict[str, tuple] = {}
    for c in sorted(columns):
        width = max((boxes[v].w for v in columns[c] if v in boxes), default=40 * SCALE)
        y = top + (tallest - heights[c]) // 2
        for v in columns[c]:
            if v in boxes:
                b = boxes[v]
                b.x, b.y = x + (width - b.w) // 2, y
                y += b.h + gap_y
            else:
                points[v] = (x + width // 2, y + 5 * SCALE)
                y += 10 * SCALE + gap_y
        gap = max(90 * SCALE, gaps.get(c, 0))
        x += width + gap
    return boxes, routes, points, x - gap + margin, top + tallest + margin


def _dashed(draw, xy, fill, width, dash=8):
    (x1, y1), (x2, y2) = xy
    length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 or 1
    steps = int(length // (dash * SCALE))
    for i in range(0, steps, 2):
        a, b = i / steps, min((i + 1) / steps, 1)
        draw.line([(x1 + (x2 - x1) * a, y1 + (y2 - y1) * a), (x1 + (x2 - x1) * b, y1 + (y2 - y1) * b)],
                  fill=fill, width=width)


def _arrowhead(draw, tip, tail, fill):
    import math
    angle = math.atan2(tip[1] - tail[1], tip[0] - tail[0])
    size = 9 * SCALE
    left = (tip[0] - size * math.cos(angle - 0.4), tip[1] - size * math.sin(angle - 0.4))
    right = (tip[0] - size * math.cos(angle + 0.4), tip[1] - size * math.sin(angle + 0.4))
    draw.polygon([tip, left, right], fill=fill)


def _label(draw, centre, text, font, colour="#333333"):
    if not text:
        return
    w = font.getlength(text)
    h = 14 * SCALE
    x, y = centre[0] - w / 2, centre[1] - h / 2
    draw.rectangle([x - 4 * SCALE, y - 2 * SCALE, x + w + 4 * SCALE, y + h + 2 * SCALE], fill="#ffffff")
    draw.text((x, y), text, font=font, fill=colour)


def _draw_box(draw, b: _Box, fonts):
    t, fill, stroke = b.node.type, _FILL[b.node.type], _STROKE[b.node.type]
    x1, y1, x2, y2 = b.x, b.y, b.x + b.w, b.y + b.h
    lw = 2 * SCALE
    if t == "database":
        e = 16 * SCALE
        draw.rectangle([x1, y1 + e // 2, x2, y2 - e // 2], fill=fill)
        draw.ellipse([x1, y2 - e, x2, y2], fill=fill, outline=stroke, width=lw)
        draw.rectangle([x1 + lw, y1 + e // 2, x2 - lw, y2 - e // 2], fill=fill)
        draw.line([(x1, y1 + e // 2), (x1, y2 - e // 2)], fill=stroke, width=lw)
        draw.line([(x2, y1 + e // 2), (x2, y2 - e // 2)], fill=stroke, width=lw)
        draw.ellipse([x1, y1, x2, y1 + e], fill=fill, outline=stroke, width=lw)
        y = y1 + e + 4 * SCALE
    else:
        radius = 14 * SCALE if t in ("actor", "ui", "system") else 6 * SCALE
        draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill,
                               outline=None if t in ("external", "file") else stroke, width=lw)
        if t in ("external", "file"):
            for a, bb in (((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))):
                _dashed(draw, (a, bb), stroke, lw)
        if t == "queue":
            for k in (1, 2):
                draw.line([(x2 - k * 8 * SCALE, y1 + 6 * SCALE), (x2 - k * 8 * SCALE, y2 - 6 * SCALE)],
                          fill=stroke, width=SCALE)
        y = y1 + 8 * SCALE
    stereo = f"«{_STEREOTYPE[t]}»"
    draw.text((x1 + (b.w - fonts["tiny"].getlength(stereo)) / 2, y), stereo, font=fonts["tiny"], fill=stroke)
    y += 15 * SCALE
    for line in b.lines:
        draw.text((x1 + (b.w - fonts["bold"].getlength(line)) / 2, y), line, font=fonts["bold"], fill="#1b1f24")
        y += 17 * SCALE
    if t == "entity" and b.detail:
        y += 3 * SCALE
        draw.line([(x1, y), (x2, y)], fill=stroke, width=SCALE)
        y += 5 * SCALE
        for line in b.detail:
            draw.text((x1 + 10 * SCALE, y), line, font=fonts["small"], fill="#333333")
            y += 15 * SCALE
    else:
        for line in b.detail:
            draw.text((x1 + (b.w - fonts["small"].getlength(line)) / 2, y), line, font=fonts["small"],
                      fill="#555555")
            y += 15 * SCALE


def _side(b: _Box, toward_x: float) -> tuple:
    """Where an edge leaves or enters a box: the middle of the side facing the other end."""
    return (b.x + b.w, b.y + b.h // 2) if toward_x > b.x + b.w / 2 else (b.x, b.y + b.h // 2)


def _render_graph(diagram: Diagram, path: Path) -> None:
    from PIL import Image, ImageDraw
    fonts = {"bold": _font(12, True), "small": _font(10), "tiny": _font(9), "title": _font(15, True),
             "label": _font(10)}
    boxes, routes, points, width, height = _layout(diagram, fonts)
    width = max(width, int(fonts["title"].getlength(diagram.title)) + 60 * SCALE)
    image = Image.new("RGB", (int(width), int(height)), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.text((30 * SCALE, 22 * SCALE), f"{diagram.id}  {diagram.title}", font=fonts["title"], fill="#1b1f24")
    for edge, route, reversed_ in routes:
        coords = []
        for i, v in enumerate(route):
            if v in boxes:
                other = route[i + 1] if i + 1 < len(route) else route[i - 1]
                ox = boxes[other].x + boxes[other].w / 2 if other in boxes else points[other][0]
                coords.append(_side(boxes[v], ox))
            else:
                coords.append(points[v])
        if reversed_:
            coords = coords[::-1]
        draw.line(coords, fill="#5a6470", width=2 * SCALE, joint="curve")
        _arrowhead(draw, coords[-1], coords[-2], "#5a6470")
        mid = ((coords[0][0] + coords[1][0]) / 2, (coords[0][1] + coords[1][1]) / 2)
        _label(draw, mid, edge.label, fonts["label"])
    for b in boxes.values():
        _draw_box(draw, b, fonts)
    image.save(path, "PNG", optimize=True, dpi=(96 * SCALE, 96 * SCALE))


def _render_sequence(diagram: Diagram, path: Path) -> None:
    from PIL import Image, ImageDraw
    fonts = {"bold": _font(12, True), "small": _font(10), "tiny": _font(9), "title": _font(15, True),
             "label": _font(10)}
    boxes = [_measure(n, fonts) for n in diagram.nodes]
    labels = [f"{i}. {e.label}" for i, e in enumerate(diagram.edges, 1)]
    widest = max([fonts["label"].getlength(l) for l in labels] + [0])
    col = max(max(b.w for b in boxes) + 30 * SCALE, min(widest + 30 * SCALE, 320 * SCALE))
    margin, top, row = 30 * SCALE, 64 * SCALE, 40 * SCALE
    head = max(b.h for b in boxes)
    width = int(margin * 2 + col * len(boxes))
    height = int(top + head + row * (len(diagram.edges) + 1) + margin)
    image = Image.new("RGB", (max(width, int(fonts["title"].getlength(diagram.title)) + 80 * SCALE), height),
                      "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.text((margin, 20 * SCALE), f"{diagram.id}  {diagram.title}", font=fonts["title"], fill="#1b1f24")
    centre = {}
    for i, b in enumerate(boxes):
        cx = margin + col * i + col // 2
        b.x, b.y = int(cx - b.w / 2), top
        centre[b.node.id] = cx
        _dashed(draw, ((cx, top + head), (cx, height - margin)), "#9aa3ad", SCALE * 2, dash=6)
        _draw_box(draw, b, fonts)
    y = top + head + row
    for label, e in zip(labels, diagram.edges):
        a, b = centre[e.source], centre[e.target]
        returning = e.label.lower().startswith(("return", "←", "response", "200", "201", "204", "redirect"))
        colour = "#5a6470"
        if a == b:
            loop = [(a, y - 6 * SCALE), (a + 40 * SCALE, y - 6 * SCALE), (a + 40 * SCALE, y + 10 * SCALE),
                    (a + 4 * SCALE, y + 10 * SCALE)]
            draw.line(loop, fill=colour, width=2 * SCALE)
            _arrowhead(draw, loop[-1], loop[-2], colour)
            draw.text((a + 46 * SCALE, y - 8 * SCALE), label, font=fonts["label"], fill="#333333")
        else:
            if returning:
                _dashed(draw, ((a, y), (b, y)), colour, 2 * SCALE, dash=6)
            else:
                draw.line([(a, y), (b, y)], fill=colour, width=2 * SCALE)
            _arrowhead(draw, (b, y), (a, y), colour)
            _label(draw, ((a + b) / 2, y - 10 * SCALE), label, fonts["label"])
        y += row
    image.save(path, "PNG", optimize=True, dpi=(96 * SCALE, 96 * SCALE))


def pillow_available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def render(diagrams: list[Diagram], out_dir: str) -> list[str]:
    """PNG files for the diagrams (HLD-1.png …), into `out_dir`; the names written.
    A diagram that cannot be drawn keeps no image and is shown as text."""
    if not pillow_available():
        return []
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for d in diagrams:
        target = folder / f"{d.id}.png"
        try:
            (_render_sequence if d.kind == "sequence" else _render_graph)(d, target)
        except Exception:                               # noqa: BLE001 — the text form still documents it
            continue
        d.image = target.name
        written.append(target.name)
    return written


def as_text(d: Diagram) -> str:
    """The diagram as plain text, for a reader without the image."""
    names = {n.id: n.label for n in d.nodes}
    if d.kind == "sequence":
        lines = ["Participants: " + ", ".join(names[n.id] for n in d.nodes)]
        lines += [f"{i:>2}. {names[e.source]} → {names[e.target]} : {e.label}" for i, e in enumerate(d.edges, 1)]
        return "\n".join(lines)
    lines = [f"[{n.type}] {n.label}" + (f" — {n.detail}" if n.detail else "") for n in d.nodes]
    lines += [f"{names[e.source]} ──{(' ' + e.label + ' ') if e.label else ''}──▶ {names[e.target]}"
              for e in d.edges]
    return "\n".join(lines)


# ── markdown ────────────────────────────────────────────────────────────────

def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _sources(refs: list) -> str:
    return ", ".join(r if _EV.fullmatch(r) or _UI.match(r) else f"`{r}`" for r in refs)


def to_markdown(diagrams: list[Diagram], image_prefix: str = "diagrams/") -> str:
    if not diagrams:
        return ""
    lines = [HEADING, "",
             "_Declared by the Enterprise Architect agent from the evidence and the computed facts; every element "
             "was checked against what it cites, and the pipeline drew the pictures. The table under each diagram "
             "lists its elements and what each rests on._", ""]
    for level, title in (("high", "### High-level design"), ("low", "### Low-level design")):
        group = [d for d in diagrams if d.level == level]
        if not group:
            continue
        lines += [title, ""]
        for d in group:
            names = {n.id: n.label for n in d.nodes}
            lines += [f"#### {d.id} — {d.title}", ""]
            if d.description:
                lines += [d.description, ""]
            if d.image:
                lines += [f"![{d.id} — {d.title}]({image_prefix}{d.image})", ""]
            else:
                lines += ["```text", as_text(d), "```", ""]
            if d.kind == "sequence":
                lines += ["| Step | From | To | Message | Sources |", "|---|---|---|---|---|"]
                lines += [f"| {i} | {_cell(names[e.source])} | {_cell(names[e.target])} | {_cell(e.label)} | "
                          f"{_sources(e.sources)} |" for i, e in enumerate(d.edges, 1)]
            else:
                lines += ["| Element | Kind | Detail | Sources |", "|---|---|---|---|"]
                for n in d.nodes:
                    detail = ", ".join(n.fields) if n.type == "entity" and n.fields else n.detail
                    lines.append(f"| {_cell(n.label)} | {n.type} | {_cell(detail) or '—'} | {_sources(n.sources)} |")
                for e in d.edges:
                    lines.append(f"| {_cell(names[e.source])} → {_cell(names[e.target])} | connection | "
                                 f"{_cell(e.label) or '—'} | {_sources(e.sources)} |")
            lines.append("")
    return "\n".join(lines).rstrip()


def to_json(diagrams: list[Diagram]) -> list[dict]:
    return [{"id": d.id, "level": d.level, "kind": d.kind, "title": d.title, "image": d.image} for d in diagrams]
