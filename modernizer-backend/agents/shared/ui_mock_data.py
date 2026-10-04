"""
Sample data for rendering a server-side template, read from the code — no
model involved, no randomness: the same repository always gives the same data.

Two sources, merged:

- **The controller.** The handler method's `model.addAttribute("x", expr)` /
  `mav.addObject("x", expr)` / `model.put("x", expr)` calls, its
  `@ModelAttribute` (and implicit command-object) parameters, and the class's
  (and any `@ControllerAdvice`'s) `@ModelAttribute` methods. The type of each
  expression is resolved with tree-sitter over the repository's own classes —
  literals, `new X(..)`, locals, parameters, fields and method return types
  (`service.findAll()` → `List<Job>`) — and a repository class becomes an
  object with its fields (inherited ones included), an enum its first
  constant, a collection three items.
- **The template.** Every `${...}` / `*{...}` path the template and the
  fragments/layout it pulls in use, scoped through `th:each`, `th:object` and
  `th:with`, so a value the code does not reveal (`${user.displayName}`) is
  still filled. A variable the template only tests (`th:if="${error}"`) and the
  controller does not set is left out of the first state: it is a page *state*
  (see `states`).

Values follow fixed rules from the name and type: `email` → user1@example.com,
dates → 2026-01-15, prices → 49.99, `is…`/`has…` → true, other text →
"Sample Field Name 1".
"""
import html.parser
import re
from dataclasses import dataclass, field
from pathlib import Path

from .dependency_graph import EXCLUDED_DIRS
from .rule_candidates import _PARSERS, _TEST_PATH

SAMPLE_DATE = "2026-01-15"
SAMPLE_DATETIME = "2026-01-15T10:30:00"
LIST_ITEMS = 3
MAX_DEPTH = 4
NEW = "new "          # type prefix: an object created empty in the handler (`new Job()`)

_INTS = {"int", "Integer", "long", "Long", "short", "Short", "byte", "Byte", "BigInteger", "AtomicInteger",
         "AtomicLong"}
_DECIMALS = {"double", "Double", "float", "Float", "BigDecimal", "Number"}
_BOOLS = {"boolean", "Boolean", "AtomicBoolean"}
_STRINGS = {"String", "CharSequence", "StringBuilder", "char", "Character", "Object"}
_DATES = {"LocalDate": "date", "LocalDateTime": "datetime", "ZonedDateTime": "datetime",
          "OffsetDateTime": "datetime", "Instant": "datetime", "LocalTime": "time", "Date": "legacy",
          "Timestamp": "legacy", "Calendar": "legacy", "java.util.Date": "legacy", "java.sql.Date": "legacy"}
_LISTS = {"List", "ArrayList", "LinkedList", "Set", "HashSet", "LinkedHashSet", "TreeSet", "SortedSet",
          "Collection", "Iterable", "Stream", "Flux", "Vector", "Queue", "Deque", "ImmutableList", "ImmutableSet"}
_WRAPPERS = {"Optional", "Mono", "ResponseEntity", "CompletableFuture", "Future", "Callable", "DeferredResult"}
_MAPS = {"Map", "HashMap", "LinkedHashMap", "TreeMap", "SortedMap", "ImmutableMap", "MultiValueMap"}
# Parameter types the framework supplies; never part of the model.
_FRAMEWORK_PARAMS = re.compile(
    r"^(?:Model|ModelMap|Map|RedirectAttributes|BindingResult|Errors|Principal|Authentication|HttpServletRequest|"
    r"HttpServletResponse|HttpSession|ServletRequest|ServletResponse|WebRequest|NativeWebRequest|Locale|"
    r"SessionStatus|UriComponentsBuilder|MultipartFile|Pageable|Sort|ServerWebExchange|OAuth2User|UserDetails|"
    r"String|Integer|Long|int|long|boolean|Boolean|Double|double|BigDecimal|LocalDate|LocalDateTime|UUID|"
    r"List|Set|Optional)\b")
_NOT_MODEL_PARAM_ANN = {"RequestParam", "PathVariable", "RequestBody", "RequestHeader", "CookieValue",
                        "RequestPart", "AuthenticationPrincipal", "SessionAttribute", "RequestAttribute", "Value"}
_EXPR_KEYWORDS = {"and", "or", "not", "eq", "ne", "lt", "gt", "le", "ge", "true", "false", "null", "div", "mod",
                  "instanceof", "new", "T", "this", "root"}
_CONDITION_ATTRS = {"if", "unless", "switch", "case"}


# ── repository class index ──────────────────────────────────────────────────

@dataclass
class JavaClass:
    name: str
    path: str
    fields: dict = field(default_factory=dict)       # name -> type
    methods: dict = field(default_factory=dict)      # name -> return type
    constants: list = field(default_factory=list)    # enum constants
    superclass: str = ""
    advice: bool = False                             # @ControllerAdvice
    model_methods: list = field(default_factory=list)  # [(model name, return type)] from @ModelAttribute methods
    node_ref: tuple = ()                             # (path, start byte, end byte)


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _annotations(node, src: bytes) -> dict:
    out = {}
    for child in node.children:
        if child.type == "modifiers":
            for a in child.children:
                if a.type in ("annotation", "marker_annotation"):
                    name = a.child_by_field_name("name")
                    args = a.child_by_field_name("arguments")
                    out[_text(name, src).rsplit(".", 1)[-1] if name else ""] = _text(args, src) if args else ""
    return out


def _decap(name: str) -> str:
    return name[:1].lower() + name[1:] if name else name


def java_files(workspace_dir: str) -> list[Path]:
    root = Path(workspace_dir)
    out = []
    for path in sorted(root.rglob("*.java")):
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(Path(rel).parts) or _TEST_PATH.search(rel):
            continue
        out.append(path)
    return out


def index_classes(workspace_dir: str) -> dict[str, JavaClass]:
    """Every class, interface, record and enum declared in the repository's main code."""
    classes: dict[str, JavaClass] = {}
    if "java" not in _PARSERS:
        return classes
    root = Path(workspace_dir)
    for path in java_files(workspace_dir):
        try:
            src = path.read_bytes()
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        tree = _PARSERS["java"].parse(src)
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            stack.extend(reversed(node.children))
            if node.type not in ("class_declaration", "interface_declaration", "enum_declaration",
                                 "record_declaration"):
                continue
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            cls = JavaClass(_text(name_node, src), rel, node_ref=(rel, node.start_byte, node.end_byte))
            ann = _annotations(node, src)
            cls.advice = "ControllerAdvice" in ann
            sup = node.child_by_field_name("superclass")
            if sup is not None:
                cls.superclass = _base(_text(sup, src).replace("extends", "").strip())
            if node.type == "record_declaration":
                params = node.child_by_field_name("parameters")
                for p in (params.children if params else []):
                    if p.type == "formal_parameter":
                        cls.fields[_text(p.child_by_field_name("name"), src)] = _text(p.child_by_field_name("type"), src)
            body = node.child_by_field_name("body")
            for member in (body.children if body else []):
                if member.type == "enum_body_declarations":
                    continue
                if member.type == "enum_constant":
                    cls.constants.append(_text(member.child_by_field_name("name"), src))
                elif member.type == "field_declaration":
                    ftype = _text(member.child_by_field_name("type"), src)
                    mods = next((_text(c, src) for c in member.children if c.type == "modifiers"), "")
                    if "static" in mods.split():
                        continue
                    for d in member.children:
                        if d.type == "variable_declarator":
                            cls.fields[_text(d.child_by_field_name("name"), src)] = ftype
                elif member.type == "method_declaration":
                    mname = _text(member.child_by_field_name("name"), src)
                    rtype = _text(member.child_by_field_name("type"), src)
                    cls.methods.setdefault(mname, rtype)
                    mann = _annotations(member, src)
                    if "ModelAttribute" in mann and rtype != "void":
                        named = re.search(r"\"([^\"]+)\"", mann["ModelAttribute"])
                        cls.model_methods.append((named.group(1) if named else _decap(_base(rtype)), rtype))
            if node.type == "enum_declaration" and body is not None:
                cls.constants = [_text(c.child_by_field_name("name"), src) for c in body.children
                                 if c.type == "enum_constant"]
            classes.setdefault(cls.name, cls)
    return classes


def _base(type_text: str) -> str:
    """`java.util.List<Job>` → `List`; `Job[]` → `Job[]`."""
    t = re.sub(r"<.*>", "", type_text.strip()).strip()
    return t.rsplit(".", 1)[-1] if "." in t and not t.endswith("]") else t


def _args(type_text: str) -> list[str]:
    """Generic arguments, top level only: `Map<String, List<Job>>` → [String, List<Job>]."""
    m = re.search(r"<(.*)>\s*$", type_text.strip())
    if not m:
        return []
    out, depth, cur = [], 0, ""
    for ch in m.group(1):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return [re.sub(r"^\?\s*(?:extends|super)\s+", "", a) for a in out]


# ── controller model ────────────────────────────────────────────────────────

def controller_model(workspace_dir: str, source: str, classes: dict[str, JavaClass]) -> dict[str, str]:
    """{model attribute: type} for the handler declared at `source` ("path:line")."""
    rel, _, line = source.rpartition(":")
    path = Path(workspace_dir) / rel
    if "java" not in _PARSERS or not path.is_file() or not line.isdigit():
        return {}
    src = path.read_bytes()
    tree = _PARSERS["java"].parse(src)
    target = int(line) - 1
    method, owner = None, None
    stack = [(tree.root_node, None)]
    while stack:
        node, cls = stack.pop()
        if node.type == "class_declaration":
            cls = node
        if node.type == "method_declaration" and node.start_point[0] <= target <= node.end_point[0]:
            method, owner = node, cls
        stack.extend((c, cls) for c in reversed(node.children))
    if method is None:
        return {}
    owner_name = _text(owner.child_by_field_name("name"), src) if owner is not None else ""
    owner_cls = classes.get(owner_name)

    model: dict[str, str] = {}
    # Global and class-level @ModelAttribute methods first; the handler's own calls win.
    for cls in sorted((c for c in classes.values() if c.advice), key=lambda c: c.name):
        model.update({k: v for k, v in cls.model_methods})
    if owner_cls:
        model.update({k: v for k, v in owner_cls.model_methods})

    scope: dict[str, str] = dict(owner_cls.fields) if owner_cls else {}
    params = method.child_by_field_name("parameters")
    model_params = set()
    for p in (params.children if params else []):
        if p.type != "formal_parameter":
            continue
        ptype = _text(p.child_by_field_name("type"), src)
        pname = _text(p.child_by_field_name("name"), src)
        scope[pname] = ptype
        if re.match(r"(?:Model|ModelMap|Map)\b", ptype):
            model_params.add(pname)
        ann = _annotations(p, src)
        if "ModelAttribute" in ann:
            named = re.search(r"\"([^\"]+)\"", ann["ModelAttribute"])
            model[named.group(1) if named else _decap(_base(ptype))] = ptype
        elif not (_NOT_MODEL_PARAM_ANN & set(ann)) and not _FRAMEWORK_PARAMS.match(ptype) \
                and _base(ptype) in classes and not classes[_base(ptype)].constants:
            model[_decap(_base(ptype))] = ptype      # an implicit command object
    body = method.child_by_field_name("body")
    if body is None:
        return model
    stack = [body]
    calls = []
    while stack:
        node = stack.pop()
        stack.extend(reversed(node.children))
        if node.type == "local_variable_declaration":
            vtype = _text(node.child_by_field_name("type"), src)
            for d in node.children:
                if d.type == "variable_declarator":
                    scope[_text(d.child_by_field_name("name"), src)] = vtype
        elif node.type == "method_invocation":
            calls.append(node)
        elif node.type == "object_creation_expression" and _base(_text(node.child_by_field_name("type"), src)) \
                == "ModelAndView":
            args = [a for a in node.child_by_field_name("arguments").children if a.is_named]
            if len(args) == 3 and args[1].type == "string_literal":
                model[_text(args[1], src).strip('"')] = _expr_type(args[2], src, scope, classes, owner_cls) or ""
    for call in calls:
        name = _text(call.child_by_field_name("name"), src)
        obj = call.child_by_field_name("object")
        args = [a for a in call.child_by_field_name("arguments").children if a.is_named]
        if name in ("addAttribute", "addObject") or (name == "put" and obj is not None
                                                      and _text(obj, src) in model_params):
            if len(args) == 2 and args[0].type == "string_literal":
                model[_text(args[0], src).strip('"')] = _expr_type(args[1], src, scope, classes, owner_cls) or ""
            elif len(args) == 1 and name != "put":
                t = _expr_type(args[0], src, scope, classes, owner_cls)
                if t:
                    model[_decap(_base(t))] = t
    return model


def _expr_type(node, src, scope, classes, owner) -> str | None:
    t = node.type
    if t == "string_literal" or t == "text_block":
        return "String"
    if t in ("decimal_integer_literal", "hex_integer_literal"):
        return "int"
    if t in ("decimal_floating_point_literal",):
        return "double"
    if t in ("true", "false"):
        return "boolean"
    if t == "object_creation_expression":
        args = node.child_by_field_name("arguments")
        created = _text(node.child_by_field_name("type"), src)
        # `new Job()` is an empty object — a form shown blank, as Spring shows it.
        return NEW + created if args is not None and not [a for a in args.children if a.is_named] else created
    if t == "array_creation_expression":
        return _text(node.child_by_field_name("type"), src) + "[]"
    if t == "identifier":
        return scope.get(_text(node, src))
    if t == "field_access":
        return scope.get(_text(node.child_by_field_name("field"), src))
    if t == "cast_expression":
        return _text(node.child_by_field_name("type"), src)
    if t == "parenthesized_expression":
        inner = [c for c in node.children if c.is_named]
        return _expr_type(inner[0], src, scope, classes, owner) if inner else None
    if t == "method_invocation":
        name = _text(node.child_by_field_name("name"), src)
        obj = node.child_by_field_name("object")
        if obj is None:
            return owner.methods.get(name) if owner else None
        if _text(obj, src) in ("List", "Set", "Arrays", "Collections", "Stream") and name in (
                "of", "asList", "singletonList", "emptyList", "unmodifiableList", "copyOf"):
            items = [a for a in node.child_by_field_name("arguments").children if a.is_named]
            inner = _expr_type(items[0], src, scope, classes, owner) if items else None
            return f"List<{inner}>" if inner else "List"
        otype = _expr_type(obj, src, scope, classes, owner)
        if obj.type == "identifier" and _text(obj, src) in classes and _text(obj, src) not in scope:
            static = classes[_text(obj, src)]
            if static.constants and name == "values":
                return f"{static.name}[]"      # every constant of a repository enum
            otype = static.name                # a static call on a repository class
        if _text(obj, src) == "EnumSet" and name in ("allOf", "of", "range"):
            items = [a for a in node.child_by_field_name("arguments").children if a.is_named]
            if items and items[0].type == "class_literal":
                return f"List<{_text(items[0], src).replace('.class', '')}>"
        if otype is None:
            return None
        return _method_return(otype, name, classes)
    return None


def _method_return(otype: str, name: str, classes: dict[str, JavaClass], depth: int = 0) -> str | None:
    base = _base(otype)
    cls = classes.get(base)
    if cls is None or depth > 5:
        if base in _WRAPPERS | {"Optional"} and name in ("get", "orElse", "orElseThrow", "block", "getBody"):
            args = _args(otype)
            return args[0] if args else None
        if base in _LISTS and name in ("get", "getFirst", "findFirst"):
            args = _args(otype)
            return args[0] if args else None
        return None
    if name in cls.methods:
        return cls.methods[name]
    if cls.superclass:
        return _method_return(cls.superclass, name, classes, depth + 1)
    return None


# ── template shape ──────────────────────────────────────────────────────────

class Shape:
    """What a template reads from one value: its properties, whether it is
    iterated, and whether it is only ever tested in a condition."""

    def __init__(self):
        self.props: dict[str, "Shape"] = {}
        self.item: "Shape | None" = None
        self.content = False      # used for output, not only in a condition
        self.tested_empty = False

    def child(self, name: str) -> "Shape":
        if name == "[]":
            if self.item is None:
                self.item = Shape()
            return self.item
        return self.props.setdefault(name, Shape())


_EXPR = re.compile(r"([$*])\{(.*?)\}", re.S)
_STRING_LIT = re.compile(r"'(?:[^'\\]|\\.)*'")
_PATH = re.compile(r"(?<![\w#@$.'])([A-Za-z_]\w*)((?:\s*\.\s*[A-Za-z_]\w*(?!\s*\()|\s*\[\s*\d+\s*\])*)(\s*\()?")
_EMPTY_TEST = re.compile(
    r"#(?:lists|sets|arrays|maps|strings)\.isEmpty\(\s*([A-Za-z_][\w.]*)\s*\)|"
    r"([A-Za-z_][\w.]*)\s*\.\s*(?:isEmpty\(\)|empty\b)|"
    r"(?:#(?:lists|sets|arrays|maps)\.size\(\s*([A-Za-z_][\w.]*)\s*\)|([A-Za-z_][\w.]*)\.size\(\))\s*(?:==|eq)\s*0|"
    r"^\s*(?:!|not\s+)\s*([A-Za-z_][\w.]*)\s*$")


class _TemplateReader(html.parser.HTMLParser):
    def __init__(self, shapes: dict[str, Shape], refs: list[str]):
        super().__init__(convert_charrefs=True)
        self.shapes, self.refs = shapes, refs
        self.scopes: list[dict] = [{}]
        self.selection: list[list[str] | None] = [None]
        self.tags: list[str] = []
        self.roles: set[str] = set()
        self.auth_tests = False
        self.flags: dict[str, str] = {}       # root variable -> "flag" | "param"

    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def _resolve(self, head: str, rest: list[str], selection: bool) -> list[str] | None:
        if selection:
            sel = next((s for s in reversed(self.selection) if s is not None), None)
            return (sel + [head] + rest) if sel is not None else [head] + rest
        for scope in reversed(self.scopes):
            if head in scope:
                return scope[head] + rest
        return [head] + rest

    def _paths(self, expression: str, selection: bool):
        text = _STRING_LIT.sub("''", expression)
        for m in _PATH.finditer(text):
            head = m.group(1)
            if head in _EXPR_KEYWORDS or text[max(0, m.start() - 1)] == "#":
                continue
            rest = [p.strip() for p in re.split(r"\s*\.\s*", m.group(2).strip()) if p.strip()] if m.group(2) else []
            rest = [p if not p.startswith("[") else "[]" for r in rest for p in [r]]
            if m.group(3) and not rest:
                continue                     # a function call: hasRole(...), not a variable
            yield self._resolve(head, rest, selection)

    def _record(self, value: str, condition: bool, attr: str = ""):
        for m in _EXPR.finditer(value):
            body = m.group(2)
            for path in self._paths(body, m.group(1) == "*"):
                if not path:
                    continue
                shape = self.shapes.setdefault(path[0], Shape())
                for part in path[1:]:
                    shape = shape.child(part)
                if not condition:
                    node = self.shapes[path[0]]
                    node.content = True
                    for part in path[1:]:
                        node = node.child(part)
                        node.content = True
            if condition:
                e = _EMPTY_TEST.search(body)
                if e:
                    var = next(g for g in e.groups() if g)
                    resolved = self._resolve(var.split(".")[0], var.split(".")[1:], m.group(1) == "*")
                    if resolved and len(resolved) == 1:
                        self.shapes.setdefault(resolved[0], Shape()).tested_empty = True
                for path in self._paths(body, m.group(1) == "*"):
                    if path and path[0] == "param" and len(path) > 1:
                        self.flags.setdefault(path[1], "param")
                    elif path and len(path) == 1:
                        self.flags.setdefault(path[0], "flag")

    def handle_starttag(self, tag, attrs):
        # th:each / th:object / th:with bind names for the element's own other
        # attributes too (th:value="${t}" next to th:each="t : ${types}"), so
        # they are read first and their scope opened before the rest.
        scope, selection = {}, None
        self.scopes.append(scope)
        self.selection.append(None)
        for name, value in attrs:
            if value is None or not name.startswith(("th:", "data-th-")):
                continue
            short = re.sub(r"^(?:th:|data-th-)", "", name)
            if short == "each":
                m = re.match(r"\s*(\w+)\s*(?:,\s*\w+)?\s*:\s*(.*)$", value, re.S)
                em = _EXPR.search(m.group(2)) if m else None
                paths = [p for p in self._paths(em.group(2), em.group(1) == "*") if p] if em else []
                if paths:
                    src = paths[0]
                    shape = self.shapes.setdefault(src[0], Shape())
                    for part in src[1:]:
                        shape = shape.child(part)
                    shape.child("[]")
                    self.shapes[src[0]].content = True
                    scope[m.group(1)] = src + ["[]"]
            elif short == "object":
                em = _EXPR.search(value)
                paths = [p for p in self._paths(em.group(2), em.group(1) == "*") if p] if em else []
                if paths:
                    selection = paths[0]
                    self.shapes.setdefault(paths[0][0], Shape()).content = True
            elif short == "with":
                for wm in re.finditer(r"(\w+)\s*=\s*([$*]\{.*?\})", value):
                    em = _EXPR.match(wm.group(2))
                    paths = [p for p in self._paths(em.group(2), em.group(1) == "*") if p]
                    if paths:
                        scope[wm.group(1)] = paths[0]
        self.selection[-1] = selection
        for name, value in attrs:
            if value is None:
                continue
            short = re.sub(r"^(?:th:|data-th-)", "", name)
            if name.startswith(("th:", "data-th-")):
                if short in ("each", "object", "with"):
                    continue
                if short in ("replace", "insert", "include", "decorate"):
                    self.refs.append(value)
                self._record(value, short in _CONDITION_ATTRS, short)
            elif name in ("layout:decorate", "layout:decorator", "layout:insert", "layout:replace",
                          "data-layout-decorate", "data-layout-insert", "data-layout-replace"):
                self.refs.append(value)
            elif name in ("sec:authorize", "sec:authorize-expr"):
                for args in re.findall(r"has(?:Any)?(?:Role|Authority)\s*\(([^)]*)\)", value):
                    self.roles.update(r[5:] if r.startswith("ROLE_") else r for r in re.findall(r"'([^']+)'", args))
                if re.search(r"is(?:Authenticated|Anonymous|FullyAuthenticated)\s*\(", value):
                    self.auth_tests = True
        if tag in self._VOID:
            self.scopes.pop()
            self.selection.pop()
        else:
            self.tags.append(tag)

    def handle_endtag(self, tag):
        if tag in self._VOID:
            return
        while self.tags:
            t = self.tags.pop()
            self.scopes.pop()
            self.selection.pop()
            if t == tag:
                break

    def handle_data(self, data):
        for m in re.finditer(r"\[\[(.*?)\]\]|\[\((.*?)\)\]", data, re.S):
            self._record(m.group(1) or m.group(2), False)


@dataclass
class TemplateFacts:
    shapes: dict
    roles: list
    auth_tests: bool
    flags: dict          # root var -> "flag" | "param"
    files: list          # template files read (the page, its fragments and layout), relative to the templates root


def _ref_names(ref: str) -> list[str]:
    """Template names in a fragment / layout reference: `~{fragments/header :: header}` → fragments/header."""
    out = []
    for m in re.finditer(r"~?\{?\s*([A-Za-z0-9_\-/.]+)\s*(?:::|\})", ref + "}"):
        name = m.group(1).strip()
        if name and not name.startswith(("::", "this")) and "${" not in name:
            out.append(name)
    return out


def read_template(templates_root: Path, name: str, depth: int = 0, seen: set | None = None,
                  shapes: dict | None = None) -> TemplateFacts:
    """The facts a template and everything it includes need from the model."""
    seen = set() if seen is None else seen
    shapes = {} if shapes is None else shapes
    facts = TemplateFacts(shapes, [], False, {}, [])
    path = templates_root / f"{name}.html"
    if name in seen or depth > 4 or not path.is_file():
        return facts
    seen.add(name)
    refs: list[str] = []
    reader = _TemplateReader(shapes, refs)
    try:
        reader.feed(path.read_text(encoding="utf-8", errors="replace"))
        reader.close()
    except Exception:                                       # malformed markup: use what was read
        pass
    facts.files.append(f"{name}.html")
    roles, auth, flags = set(reader.roles), reader.auth_tests, dict(reader.flags)
    for ref in refs:
        for ref_name in _ref_names(ref):
            sub = read_template(templates_root, ref_name, depth + 1, seen, shapes)
            facts.files += sub.files
            roles |= set(sub.roles)
            auth = auth or sub.auth_tests
            for k, v in sub.flags.items():
                flags.setdefault(k, v)
    facts.roles, facts.auth_tests, facts.flags = sorted(roles), auth, flags
    return facts


# ── values ──────────────────────────────────────────────────────────────────

def _words(name: str) -> str:
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ").split()
    return " ".join(p.capitalize() for p in parts) or "Value"


def _leaf_by_name(name: str, i: int):
    n = name.lower()
    if re.search(r"password|secret|token", n):
        return ""
    if re.match(r"(?:is|has|can|should)[A-Z_]", name) or n in ("enabled", "active", "visible", "selected",
                                                                 "checked", "valid", "flag"):
        return True
    if re.search(r"(?:date|time|created|updated|modified|timestamp|(?<=[a-z])at)$", n) or n.endswith("_at"):
        return {"$date": SAMPLE_DATETIME}
    if re.search(r"(?:^id|count|qty|quantity|size|total|number|num|index|year|age|rank|level|version)$", n):
        return (1000 + i) if n.endswith("id") else i
    if re.search(r"(?:price|amount|cost|weight|height|width|length|rate|percent|ratio|score)$", n):
        return round(49.99 + i, 2)
    return _string_by_name(name, i)


def _string_by_name(name: str, i: int) -> str:
    n = name.lower()
    if "email" in n:
        return f"user{i}@example.com"
    if re.search(r"url|link|href|uri", n):
        return f"https://example.com/{i}"
    if "phone" in n:
        return f"555-010{i}"
    if re.search(r"status|state", n):
        return "ACTIVE"
    if re.search(r"(?:code|sku|key)$", n):
        return f"CODE-{i:03d}"
    if re.search(r"description|notes?$|comment|summary|message|text", n):
        return f"Sample {_words(name).lower()} {i}."
    if re.search(r"(?:^id|id)$", n):
        return f"ID-{1000 + i}"
    if re.search(r"password|secret|token", n):
        return ""
    return f"Sample {_words(name)} {i}"


def value_for(type_text: str, shape: Shape | None, name: str, classes: dict[str, JavaClass], i: int = 1,
              depth: int = 0, seen: frozenset = frozenset()):
    """A deterministic sample value of `type_text` (may be empty: unknown), filling `shape`."""
    t = (type_text or "").strip()
    if t.startswith(NEW):
        # A freshly created object: every field unset, as the page first shows it.
        cls = classes.get(_base(t[len(NEW):]))
        fields = sorted(_all_fields(cls, classes)) if cls else []
        return {f: None for f in sorted(set(fields) | set(shape.props if shape else {}))}
    base = _base(t)
    if depth > MAX_DEPTH:
        return None
    if t.endswith("[]") or base.endswith("[]"):
        inner = t[:-2] if t.endswith("[]") else base[:-2]
        return [value_for(inner, shape.item if shape else None, _singular(name), classes, k, depth + 1, seen)
                for k in range(1, LIST_ITEMS + 1)]
    if base in _WRAPPERS:
        args = _args(t)
        return value_for(args[0] if args else "", shape, name, classes, i, depth, seen)
    if base in _LISTS or base in ("Page", "Slice") and shape is not None and shape.item is not None:
        args = _args(t)
        item = shape.item if shape else None
        return [value_for(args[0] if args else "", item, _singular(name), classes, k, depth + 1, seen)
                for k in range(1, LIST_ITEMS + 1)]
    if base in _MAPS:
        args = _args(t)
        vtype = args[1] if len(args) > 1 else ""
        keys = sorted(shape.props) if shape and shape.props else [f"key{k}" for k in range(1, LIST_ITEMS + 1)]
        return {k: value_for(vtype, shape.props.get(k) if shape else None, k, classes, i, depth + 1, seen)
                for k in keys}
    if base in _INTS:
        return (1000 + i) if name.lower().endswith("id") else i
    if base in _DECIMALS:
        return round(49.99 + i, 2)
    if base in _BOOLS:
        return True
    if base in _DATES:
        kind = _DATES[base]
        if kind == "date":
            return {"$date": SAMPLE_DATE}
        if kind == "legacy":
            return {"$date": SAMPLE_DATETIME, "$type": "java.util.Date"}
        if kind == "time":
            return "10:30"
        return {"$date": SAMPLE_DATETIME}
    if base == "UUID":
        return f"00000000-0000-0000-0000-{i:012d}"
    if base in _STRINGS and not (shape and (shape.props or shape.item)):
        return _string_by_name(name, i)
    cls = classes.get(base)
    if cls is not None and base not in seen:
        if cls.constants:
            return cls.constants[(i - 1) % len(cls.constants)]
        obj = {}
        for fname, ftype in sorted(_all_fields(cls, classes).items()):
            obj[fname] = value_for(ftype, shape.props.get(fname) if shape else None, fname, classes, i,
                                   depth + 1, seen | {base})
        for pname, pshape in sorted((shape.props if shape else {}).items()):
            if pname not in obj:
                obj[pname] = _from_shape(pshape, pname, i, depth + 1)
        return obj
    return _from_shape(shape, name, i, depth)


def _from_shape(shape: Shape | None, name: str, i: int, depth: int):
    if shape is None or depth > MAX_DEPTH:
        return _leaf_by_name(name, i)
    if shape.item is not None and not shape.props:
        return [_from_shape(shape.item, _singular(name), k, depth + 1) for k in range(1, LIST_ITEMS + 1)]
    if shape.props:
        obj = {p: _from_shape(s, p, i, depth + 1) for p, s in sorted(shape.props.items())}
        if shape.item is not None:          # a page object: properties plus iterable content
            obj.setdefault("content", [_from_shape(shape.item, _singular(name), k, depth + 1)
                                       for k in range(1, LIST_ITEMS + 1)])
        return obj
    return _leaf_by_name(name, i)


def _all_fields(cls: JavaClass, classes: dict[str, JavaClass], depth: int = 0) -> dict:
    fields = {}
    if cls.superclass and cls.superclass in classes and depth < 5:
        fields.update(_all_fields(classes[cls.superclass], classes, depth + 1))
    fields.update(cls.fields)
    return fields


def _singular(name: str) -> str:
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


# ── page model and states ───────────────────────────────────────────────────

def base_model(controller: dict[str, str], facts: TemplateFacts, classes: dict[str, JavaClass]) -> dict:
    """The model of the page as first shown: everything the controller sets,
    and everything the template outputs; variables only tested are left unset."""
    model = {}
    for name in sorted(controller):
        model[name] = value_for(controller[name], facts.shapes.get(name), name, classes)
    for name, shape in sorted(facts.shapes.items()):
        if name in model or name in ("param", "session", "request", "application"):
            continue
        if not shape.content:
            continue
        model[name] = _from_shape(shape, name, 1, 0)
    return model


@dataclass
class PageState:
    name: str                  # "default", "no jobs", "error shown", "signed in without roles", ...
    model: dict
    roles: list
    authenticated: bool
    description: str


def states(controller: dict[str, str], facts: TemplateFacts, classes: dict[str, JavaClass],
           max_states: int) -> list[PageState]:
    """The default state, then one state per condition the page tests, in a fixed order:
    an empty list, a message or flag shown, a request parameter present, fewer roles, signed out."""
    model = base_model(controller, facts, classes)
    roles = list(facts.roles)
    role_text = f"signed in as sample.user with role{'s' if len(roles) != 1 else ''} {', '.join(roles)}" \
        if roles else "signed in as sample.user"
    out = [PageState("default", model, roles, True, role_text)]
    for name, shape in sorted(facts.shapes.items()):
        if shape.tested_empty and isinstance(model.get(name), list):
            out.append(PageState(f"no {_words(name).lower()}", {**model, name: []}, roles, True,
                                 f"`{name}` is empty"))
    for name, kind in sorted(facts.flags.items()):
        if kind == "flag" and name not in model and name not in controller \
                and name not in ("param", "session", "request", "application"):
            value = _string_by_name(name, 1) if re.search(r"error|message|msg|warning|info|alert|notice|success",
                                                          name, re.I) else True
            out.append(PageState(f"{_words(name).lower()} shown", {**model, name: value}, roles, True,
                                 f"`{name}` is set"))
        elif kind == "param":
            out.append(PageState(f"`{name}` parameter present", {**model, "param": {name: ["true"]}}, roles, True,
                                 f"the request has a `{name}` parameter"))
    if roles:
        out.append(PageState("signed in without roles", model, [], True, "signed in as sample.user with no roles"))
    if facts.auth_tests:
        out.append(PageState("signed out", model, [], False, "not signed in"))
    return out[:max(1, max_states)]
