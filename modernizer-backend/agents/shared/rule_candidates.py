"""
Business-rule candidates: every place in the code where a business rule can
live, found by parsing — no model involved.

This is the denominator of the business-rules ledger (rules_ledger.py). The
extraction agent classifies each candidate, so "every candidate was classified"
is a statement the pipeline can check, and the coverage report can say which
candidates were not.

Parsers:
- Java, JavaScript, TypeScript/TSX: tree-sitter syntax trees.
- Python: the standard `ast` module.
- SQL / PL/SQL, JSP, Drools (.drl): statement patterns — these languages have no
  parser installed here, and the coverage report says so.
Any other language is counted and reported as "not analysed for rules".

Candidate kinds:
- `method`      a method/function with decision logic: conditionals, switch
                cases, ternaries, comparisons, or a thrown exception
- `validation`  validation annotations on a class's fields/parameters
- `enum`        an enumeration (states, types, codes)
- `constants`   a class's literal constants (limits, thresholds, codes)
- `sql-routine` a stored procedure/function/package body/trigger
- `sql-constraint` a table's CHECK constraints
- `view-logic`  a JSP's conditional rendering (<c:if>/<c:when>/scriptlet branches)
- `rules-engine` a Drools rule
Methods whose only decisions are null checks, and accessors/equals/hashCode/
toString, are classified `auto-technical` here and never sent to the model.
"""
import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from .dependency_graph import EXCLUDED_DIRS

try:  # tree-sitter is a hard requirement (requirements.txt); guarded so a broken install degrades loudly
    from tree_sitter import Language, Parser
    import tree_sitter_java
    import tree_sitter_javascript
    import tree_sitter_typescript
    _TS_LANGUAGES = {
        "java": Language(tree_sitter_java.language()),
        "javascript": Language(tree_sitter_javascript.language()),
        "typescript": Language(tree_sitter_typescript.language_typescript()),
        "tsx": Language(tree_sitter_typescript.language_tsx()),
    }
    TREE_SITTER_ERROR = ""
except Exception as exc:  # pragma: no cover - exercised only on a broken install
    _TS_LANGUAGES = {}
    TREE_SITTER_ERROR = str(exc)

_MAX_FILE_BYTES = 2_000_000
_VENDORED = re.compile(r"(?:^|/)(?:lib|libs|vendor|vendors|third[-_]?party|external|bower_components)/", re.I)
_TEST_PATH = re.compile(r"(?:^|/)(?:src/test|test|tests|__tests__|spec|specs|it)/|(?:Test|Tests|IT|Spec)\.(?:java|kt)$|"
                        r"(?:^|/)test_[^/]+\.py$|_test\.py$|\.(?:test|spec)\.[jt]sx?$", re.I)

VALIDATION_ANNOTATIONS = {
    "NotNull", "NotEmpty", "NotBlank", "Null", "Size", "Min", "Max", "DecimalMin", "DecimalMax", "Digits",
    "Pattern", "Email", "Past", "PastOrPresent", "Future", "FutureOrPresent", "Positive", "PositiveOrZero",
    "Negative", "NegativeOrZero", "AssertTrue", "AssertFalse", "Length", "Range", "CreditCardNumber",
    "URL", "Valid", "Column",
}
_ACCESSOR = re.compile(r"^(?:get|set|is|has)[A-Z]\w*$")
_SKIP_METHODS = {"equals", "hashCode", "toString", "main"}
_COMPARISON_OPS = {">", "<", ">=", "<=", "==", "!=", "===", "!=="}


@dataclass
class Candidate:
    id: str
    path: str
    start: int                 # 1-based, inclusive
    end: int
    kind: str
    symbol: str
    language: str
    parser: str
    signals: list[str] = field(default_factory=list)
    source: str = ""
    truncated: bool = False
    area: str = ""
    status: str = "pending"    # pending | auto-technical
    reason: str = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "path", "start", "end", "kind", "symbol", "language",
                                              "parser", "signals", "truncated", "area", "status", "reason")}


@dataclass
class Scan:
    candidates: list[Candidate]
    files_by_language: dict      # language -> {"files": n, "parser": str}
    unparsed: dict               # language -> files with no rule parser
    parse_errors: list[str]
    test_files: list[str]
    tree_sitter_error: str = ""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _snippet(lines: list[str], start: int, end: int, max_lines: int) -> tuple[str, bool]:
    body = lines[start - 1:end]
    truncated = len(body) > max_lines
    if truncated:
        body = body[:max_lines]
    width = len(str(start + len(body)))
    return "\n".join(f"{n:>{width}}| {text}" for n, text in enumerate(body, start)), truncated


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _walk(node, stop_types=()):
    """Descendants of `node`, not descending into nested functions/classes."""
    stack = list(node.children)
    while stack:
        n = stack.pop()
        yield n
        if n.type not in stop_types:
            stack.extend(n.children)


# ---------------------------------------------------------------------------
# Java (tree-sitter)
# ---------------------------------------------------------------------------

_JAVA_NESTED = ("class_declaration", "interface_declaration", "enum_declaration", "record_declaration",
                "lambda_expression", "class_body", "object_creation_expression")
_JAVA_TYPES = ("class_declaration", "interface_declaration", "enum_declaration", "record_declaration")


def _decision_signals(body, src: bytes, nested: tuple, lang: str) -> tuple[list[str], bool]:
    """(signals, only_null_checks)"""
    counts = {"if": 0, "switch-case": 0, "ternary": 0, "comparison": 0, "loop-condition": 0}
    throws: list[str] = []
    null_only = True
    for n in _walk(body, nested):
        t = n.type
        if t == "if_statement":
            counts["if"] += 1
            cond = n.child_by_field_name("condition")
            if cond is not None and not re.fullmatch(r"\(?\s*!?\s*[\w.()]+\s*[!=]==?\s*null\s*\)?|\(?\s*null\s*[!=]==?\s*[\w.()]+\s*\)?",
                                                     _text(cond, src).strip()):
                null_only = False
        elif t in ("switch_label", "switch_case", "switch_rule"):
            counts["switch-case"] += 1
            null_only = False
        elif t in ("ternary_expression",):
            counts["ternary"] += 1
            null_only = False
        elif t == "binary_expression":
            op = n.child_by_field_name("operator")
            if op is not None and _text(op, src) in _COMPARISON_OPS:
                expr = _text(n, src)
                if "null" not in expr and "undefined" not in expr:
                    counts["comparison"] += 1
                    null_only = False
        elif t == "throw_statement":
            m = re.search(r"new\s+([\w.]+)", _text(n, src))
            name = m.group(1) if m else "exception"
            throws.append(name)
            if not re.fullmatch(r"(?:java\.lang\.)?(?:NullPointer|IllegalArgument|IllegalState|UnsupportedOperation)Exception|Error", name):
                null_only = False
    signals = [f"{k} ×{v}" for k, v in counts.items() if v]
    signals += [f"throws {name}" for name in dict.fromkeys(throws)]
    return signals, null_only


def _java(path: str, src: bytes, lines: list[str], max_lines: int, out: list[Candidate]) -> None:
    tree = _PARSERS["java"].parse(src)
    package = ""
    for child in tree.root_node.children:
        if child.type == "package_declaration":
            package = re.sub(r"^package\s+|;\s*$", "", _text(child, src)).strip()

    def visit(node, owner: str):
        for child in node.children:
            if child.type in _JAVA_TYPES:
                name_node = child.child_by_field_name("name")
                name = _text(name_node, src) if name_node else "?"
                qualified = f"{owner}.{name}" if owner else name
                _java_type(child, qualified)
                body = child.child_by_field_name("body")
                if body is not None:
                    visit(body, qualified)
            elif child.type in ("class_body", "enum_body_declarations", "interface_body"):
                visit(child, owner)

    def _java_type(node, owner: str):
        start_row = node.start_point[0] + 1
        if node.type == "enum_declaration":
            body = node.child_by_field_name("body")
            constants = [_text(c.child_by_field_name("name") or c, src) for c in (body.children if body else [])
                         if c.type == "enum_constant"]
            end = max((c.end_point[0] + 1 for c in (body.children if body else []) if c.type == "enum_constant"),
                      default=start_row)
            add(start_row, end, "enum", owner, [f"{len(constants)} values: " + ", ".join(constants[:12])])
        body = node.child_by_field_name("body")
        if body is None:
            return
        validation_rows, constant_rows, validation_signals, constant_names = [], [], [], []
        for member in body.children:
            if member.type == "field_declaration":
                text = _text(member, src)
                annos = [a for a in re.findall(r"@(\w+)", text) if a in VALIDATION_ANNOTATIONS and a != "Valid"]
                if annos:
                    validation_rows.append((member.start_point[0] + 1, member.end_point[0] + 1))
                    validation_signals += annos
                if re.search(r"\bstatic\b", text) and re.search(r"\bfinal\b", text) and "=" in text:
                    name_m = re.search(r"(\w+)\s*=", text)
                    value = text.split("=", 1)[1]
                    name = name_m.group(1) if name_m else ""
                    if (name and name not in ("serialVersionUID",) and not re.search(r"(?i)log(ger)?$", name)
                            and re.search(r"^\s*(?:-?\d[\d_.]*[LlFfDd]?|\"[^\"]*\"|'.'|true|false)\s*;", value)):
                        constant_rows.append((member.start_point[0] + 1, member.end_point[0] + 1))
                        constant_names.append(name)
            elif member.type in ("method_declaration", "constructor_declaration"):
                _java_method(member, owner)
            elif member.type == "enum_body_declarations":
                for inner in member.children:
                    if inner.type in ("method_declaration", "constructor_declaration"):
                        _java_method(inner, owner)
        if validation_rows:
            add(validation_rows[0][0], validation_rows[-1][1], "validation", owner,
                [f"@{a}" for a in dict.fromkeys(validation_signals)], rows=validation_rows)
        if constant_rows:
            add(constant_rows[0][0], constant_rows[-1][1], "constants", owner,
                [", ".join(constant_names[:12])], rows=constant_rows)

    def _java_method(node, owner: str):
        name_node = node.child_by_field_name("name")
        name = _text(name_node, src) if name_node else "<init>"
        body = node.child_by_field_name("body")
        start, end = node.start_point[0] + 1, node.end_point[0] + 1
        params = node.child_by_field_name("parameters")
        param_annos = [a for a in re.findall(r"@(\w+)", _text(params, src) if params else "")
                       if a in VALIDATION_ANNOTATIONS and a != "Valid"]
        if body is None:
            return
        signals, null_only = _decision_signals(body, src, _JAVA_NESTED, "java")
        signals += [f"@{a} parameter" for a in dict.fromkeys(param_annos)]
        if not signals:
            return
        status, reason = "pending", ""
        if name in _SKIP_METHODS or (_ACCESSOR.match(name) and end - start <= 3):
            status, reason = "auto-technical", f"`{name}` is an accessor/object method"
        elif null_only and not param_annos:
            status, reason = "auto-technical", "decisions are null checks only"
        add(start, end, "method", f"{owner}.{name}", signals, status=status, reason=reason)

    def add(start, end, kind, symbol, signals, rows=None, status="pending", reason=""):
        if rows and kind in ("validation", "constants"):
            text = "\n".join(_snippet(lines, a, b, max_lines)[0] for a, b in rows)
            truncated = False
        else:
            text, truncated = _snippet(lines, start, end, max_lines)
        out.append(Candidate(id="", path=path, start=start, end=end, kind=kind,
                             symbol=f"{package}.{symbol}" if package else symbol, language="Java",
                             parser="tree-sitter", signals=signals, source=text, truncated=truncated,
                             status=status, reason=reason))

    visit(tree.root_node, "")


# ---------------------------------------------------------------------------
# JavaScript / TypeScript (tree-sitter)
# ---------------------------------------------------------------------------

_JS_FUNCS = ("function_declaration", "function_expression", "function", "arrow_function", "method_definition",
             "generator_function_declaration")
_JS_NESTED = _JS_FUNCS + ("class_declaration", "class")


def _js_name(node, src: bytes) -> str:
    name = node.child_by_field_name("name")
    if name is not None:
        return _text(name, src)
    parent = node.parent
    if parent is not None:
        if parent.type == "variable_declarator":
            n = parent.child_by_field_name("name")
            return _text(n, src) if n is not None else "anonymous"
        if parent.type == "pair":                         # Backbone: validate: function (attrs) {…}
            k = parent.child_by_field_name("key")
            return _text(k, src).strip("'\"") if k is not None else "anonymous"
        if parent.type in ("assignment_expression",):
            left = parent.child_by_field_name("left")
            return _text(left, src) if left is not None else "anonymous"
    return "anonymous"


def _js(path: str, src: bytes, lines: list[str], max_lines: int, grammar: str, language: str,
        out: list[Candidate]) -> None:
    tree = _PARSERS[grammar].parse(src)
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        stack.extend(node.children)
        if node.type not in _JS_FUNCS:
            continue
        body = node.child_by_field_name("body")
        if body is None:
            continue
        signals, null_only = _decision_signals(body, src, _JS_NESTED, "js")
        if not signals:
            continue
        start, end = node.start_point[0] + 1, node.end_point[0] + 1
        name = _js_name(node, src)
        status, reason = "pending", ""
        if null_only:
            status, reason = "auto-technical", "decisions are null/undefined checks only"
        text, truncated = _snippet(lines, start, end, max_lines)
        out.append(Candidate(id="", path=path, start=start, end=end, kind="method", symbol=name,
                             language=language, parser="tree-sitter", signals=signals, source=text,
                             truncated=truncated, status=status, reason=reason))


# ---------------------------------------------------------------------------
# Python (ast)
# ---------------------------------------------------------------------------

def _python(path: str, text: str, lines: list[str], max_lines: int, out: list[Candidate]) -> None:
    tree = ast.parse(text)

    def visit(node, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, f"{owner}.{child.name}" if owner else child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                counts = {"if": 0, "ternary": 0, "comparison": 0, "match-case": 0}
                raises: list[str] = []
                null_only = True
                for n in _py_own_nodes(child):
                    if isinstance(n, ast.If):
                        counts["if"] += 1
                        if not (isinstance(n.test, ast.Compare) and any(
                                isinstance(c, ast.Constant) and c.value is None for c in n.test.comparators)):
                            null_only = False
                    elif isinstance(n, ast.IfExp):
                        counts["ternary"] += 1
                        null_only = False
                    elif isinstance(n, ast.Compare):
                        if not any(isinstance(c, ast.Constant) and c.value is None for c in n.comparators):
                            counts["comparison"] += 1
                            null_only = False
                    elif isinstance(n, ast.Raise):
                        exc = n.exc
                        name = (exc.func.id if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name)
                                else getattr(exc, "id", "exception"))
                        raises.append(name)
                        null_only = False
                    elif type(n).__name__ == "match_case":
                        counts["match-case"] += 1
                        null_only = False
                signals = [f"{k} ×{v}" for k, v in counts.items() if v] + [f"raises {r}" for r in dict.fromkeys(raises)]
                if signals:
                    start, end = child.lineno, child.end_lineno or child.lineno
                    status, reason = ("auto-technical", "decisions are None checks only") if null_only else ("pending", "")
                    if child.name.startswith("__") and child.name.endswith("__") and child.name != "__init__":
                        status, reason = "auto-technical", f"`{child.name}` is a dunder method"
                    snippet, truncated = _snippet(lines, start, end, max_lines)
                    out.append(Candidate(id="", path=path, start=start, end=end, kind="method",
                                         symbol=f"{owner}.{child.name}" if owner else child.name, language="Python",
                                         parser="python-ast", signals=signals, source=snippet, truncated=truncated,
                                         status=status, reason=reason))
                visit(child, f"{owner}.{child.name}" if owner else child.name)

    visit(tree, "")


def _py_own_nodes(func):
    stack = list(ast.iter_child_nodes(func))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(n))


# ---------------------------------------------------------------------------
# SQL / PL-SQL, JSP, Drools (statement patterns)
# ---------------------------------------------------------------------------

_SQL_ROUTINE = re.compile(r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:EDITIONABLE\s+|NONEDITIONABLE\s+)?"
                          r"(PROCEDURE|FUNCTION|TRIGGER|PACKAGE\s+BODY)\s+([\w.\"$]+)", re.I)
_SQL_TABLE = re.compile(r"^\s*(?:CREATE\s+TABLE|ALTER\s+TABLE)\s+([\w.\"$]+)", re.I)
_SQL_END = re.compile(r"^\s*/\s*$|^\s*CREATE\s+", re.I)


def _sql(path: str, lines: list[str], max_lines: int, out: list[Candidate]) -> None:
    i = 0
    n = len(lines)
    while i < n:
        routine = _SQL_ROUTINE.match(lines[i])
        table = _SQL_TABLE.match(lines[i])
        if routine:
            j = i + 1
            while j < n and not _SQL_END.match(lines[j]):
                j += 1
            body = "\n".join(lines[i:j])
            signals = [f"{routine.group(1).upper()}"] + [f"{k} ×{len(re.findall(p, body, re.I))}" for k, p in
                                                         (("IF", r"\bIF\b"), ("CASE", r"\bCASE\b"),
                                                          ("RAISE", r"\bRAISE(?:_APPLICATION_ERROR)?\b"))
                                                         if re.search(p, body, re.I)]
            snippet, truncated = _snippet(lines, i + 1, j, max_lines)
            out.append(Candidate(id="", path=path, start=i + 1, end=j, kind="sql-routine",
                                 symbol=routine.group(2).strip('"'), language="SQL", parser="pattern",
                                 signals=signals, source=snippet, truncated=truncated))
            i = j if j > i else i + 1
            continue
        if table:
            j = i + 1
            while j < n and not re.search(r";\s*$", lines[j - 1]) and not _SQL_END.match(lines[j]):
                j += 1
            body = "\n".join(lines[i:j])
            checks = re.findall(r"\bCHECK\s*\(", body, re.I)
            if checks:
                snippet, truncated = _snippet(lines, i + 1, j, max_lines)
                out.append(Candidate(id="", path=path, start=i + 1, end=j, kind="sql-constraint",
                                     symbol=table.group(1).strip('"'), language="SQL", parser="pattern",
                                     signals=[f"CHECK ×{len(checks)}"], source=snippet, truncated=truncated))
            i = j if j > i else i + 1
            continue
        i += 1


_JSP_DECISION = re.compile(r"<c:(?:if|when)\b[^>]*test\s*=|<%[^@=!-][^%]*\b(?:if|switch)\s*\(|\$\{[^}]*\?[^}]*:[^}]*\}")


def _jsp(path: str, lines: list[str], max_lines: int, out: list[Candidate]) -> None:
    rows = [i + 1 for i, line in enumerate(lines) if _JSP_DECISION.search(line)]
    if not rows:
        return
    text = "\n".join(_snippet(lines, max(1, r - 1), min(len(lines), r + 2), max_lines)[0] for r in rows[:60])
    out.append(Candidate(id="", path=path, start=rows[0], end=rows[-1], kind="view-logic",
                         symbol=Path(path).name, language="JSP", parser="pattern",
                         signals=[f"conditional rendering ×{len(rows)}"], source=text,
                         truncated=len(rows) > 60))


_DRL_RULE = re.compile(r'^\s*rule\s+"([^"]+)"|^\s*rule\s+(\w+)', re.I)


def _drl(path: str, lines: list[str], max_lines: int, out: list[Candidate]) -> None:
    for i, line in enumerate(lines):
        m = _DRL_RULE.match(line)
        if not m:
            continue
        j = i + 1
        while j < len(lines) and not re.match(r"^\s*end\b", lines[j]):
            j += 1
        snippet, truncated = _snippet(lines, i + 1, min(j + 1, len(lines)), max_lines)
        out.append(Candidate(id="", path=path, start=i + 1, end=min(j + 1, len(lines)), kind="rules-engine",
                             symbol=m.group(1) or m.group(2), language="Drools", parser="pattern",
                             signals=["rule"], source=snippet, truncated=truncated))


# ---------------------------------------------------------------------------

_PARSERS = {k: Parser(v) for k, v in _TS_LANGUAGES.items()}

#: extension -> (language, handler key, parser label)
_HANDLERS = {
    ".java": ("Java", "java", "tree-sitter"),
    ".js": ("JavaScript", "javascript", "tree-sitter"), ".mjs": ("JavaScript", "javascript", "tree-sitter"),
    ".cjs": ("JavaScript", "javascript", "tree-sitter"), ".jsx": ("JavaScript", "javascript", "tree-sitter"),
    ".ts": ("TypeScript", "typescript", "tree-sitter"), ".tsx": ("TypeScript", "tsx", "tree-sitter"),
    ".py": ("Python", "python", "python-ast"),
    ".sql": ("SQL", "sql", "pattern"), ".pls": ("PL/SQL", "sql", "pattern"), ".pks": ("PL/SQL", "sql", "pattern"),
    ".pkb": ("PL/SQL", "sql", "pattern"), ".plsql": ("PL/SQL", "sql", "pattern"), ".trg": ("PL/SQL", "sql", "pattern"),
    ".jsp": ("JSP", "jsp", "pattern"), ".jspx": ("JSP", "jsp", "pattern"), ".jspf": ("JSP", "jsp", "pattern"),
    ".tag": ("JSP", "jsp", "pattern"),
    ".drl": ("Drools", "drl", "pattern"),
}
#: Program languages with no rule parser here — counted and reported, never silently skipped.
_UNPARSED = {".kt": "Kotlin", ".scala": "Scala", ".groovy": "Groovy", ".cs": "C#", ".vb": "VB.NET", ".go": "Go",
             ".rb": "Ruby", ".php": "PHP", ".rs": "Rust", ".swift": "Swift", ".c": "C", ".cpp": "C++",
             ".cc": "C++", ".cbl": "COBOL", ".cob": "COBOL", ".pl": "Perl", ".vue": "Vue", ".svelte": "Svelte"}


def scan(workspace_dir: str, max_lines: int = 250) -> Scan:
    root = Path(workspace_dir).resolve()
    candidates: list[Candidate] = []
    by_language: dict[str, dict] = {}
    unparsed: dict[str, int] = {}
    errors: list[str] = []
    tests: list[str] = []
    if not root.exists():
        return Scan([], {}, {}, [], [], TREE_SITTER_ERROR)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        parts = set(Path(rel).parts)
        if EXCLUDED_DIRS & parts or "node_modules" in parts:
            continue
        suffix = path.suffix.lower()
        if suffix in _UNPARSED:
            unparsed[_UNPARSED[suffix]] = unparsed.get(_UNPARSED[suffix], 0) + 1
            continue
        handler = _HANDLERS.get(suffix)
        if not handler:
            continue
        language, key, parser = handler
        if _TEST_PATH.search(rel):
            tests.append(rel)
            continue
        if suffix in (".js", ".mjs", ".cjs") and (_VENDORED.search(rel) or path.name.endswith(".min.js")):
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                errors.append(f"{rel}: larger than {_MAX_FILE_BYTES // 1_000_000} MB, not scanned")
                continue
            raw = path.read_bytes()
        except OSError as exc:
            errors.append(f"{rel}: {exc}")
            continue
        text = raw.decode("utf-8", "replace")
        lines = text.splitlines()
        if key in _PARSERS or key in ("python", "sql", "jsp", "drl"):
            entry = by_language.setdefault(language, {"files": 0, "parser": parser})
            entry["files"] += 1
        try:
            if key == "java" and "java" in _PARSERS:
                _java(rel, raw, lines, max_lines, candidates)
            elif key in ("javascript", "typescript", "tsx") and key in _PARSERS:
                _js(rel, raw, lines, max_lines, key, language, candidates)
            elif key == "python":
                _python(rel, text, lines, max_lines, candidates)
            elif key == "sql":
                _sql(rel, lines, max_lines, candidates)
            elif key == "jsp":
                _jsp(rel, lines, max_lines, candidates)
            elif key == "drl":
                _drl(rel, lines, max_lines, candidates)
            else:
                unparsed[language] = unparsed.get(language, 0) + 1
        except (SyntaxError, ValueError, RecursionError) as exc:
            errors.append(f"{rel}: could not be parsed ({type(exc).__name__})")
    _assign_areas(candidates)
    candidates.sort(key=lambda c: (c.area, c.path, c.start))
    for i, c in enumerate(candidates, 1):
        c.id = f"C{i:05d}"
    return Scan(candidates, by_language, unparsed, errors, tests, TREE_SITTER_ERROR)


_SOURCE_ROOTS = re.compile(r"^(?:[^/]+/)?src/(?:main/(?:java|webapp|resources|js|javascript|ts|python)/)?")


def _assign_areas(candidates: list[Candidate]) -> None:
    """Group candidates into functional areas: the Java package (minus the prefix
    every package shares), or the directory below the source root."""
    def package_of(c: Candidate) -> list[str]:
        return c.symbol.split(".")[:-2] if c.kind == "method" else c.symbol.split(".")[:-1]

    packages = [package_of(c) for c in candidates if c.language == "Java" and c.symbol.count(".") >= 2]
    prefix: list[str] = []
    if packages:
        prefix = packages[0]
        for p in packages[1:]:
            k = 0
            while k < min(len(prefix), len(p)) and prefix[k] == p[k]:
                k += 1
            prefix = prefix[:k]
    for c in candidates:
        if c.language == "Java" and c.symbol.count(".") >= 2:
            pkg = package_of(c)
            rest = pkg[len(prefix):]
            c.area = ".".join(rest[:2]) if rest else (".".join(pkg[-1:]) or "(default package)")
        else:
            rel = _SOURCE_ROOTS.sub("", c.path)
            parent = str(Path(rel).parent)
            c.area = "/".join(Path(parent).parts[:2]) if parent != "." else "(root)"
