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
- `view-logic`  a template's rendering decisions: Thymeleaf `th:if`/`th:unless`/
                `th:switch`/`th:case`, lists (`th:each`), conditional styling and
                state (`th:classappend`, `th:disabled`…), formatting (`#numbers`,
                `#dates`, `#temporals`), forms (`th:field`, `th:errors`), calls into
                server beans (`${@bean.method(..)}`), `sec:authorize`; JSP
                `<c:if>`/`<c:when>`/scriptlet branches
- `validator`   a custom validator (`ConstraintValidator.isValid`, Spring
                `Validator.validate`, `rejectValue`)
- `global-model` data or settings every page gets: `@ModelAttribute` and
                `@InitBinder` methods (application-wide in a `@ControllerAdvice`)
- `interceptor` a request interceptor or filter (`HandlerInterceptor.preHandle`…)
- `error-mapping` an `@ExceptionHandler`: which failure the user sees and how
- `session-state` state the server keeps between requests: session attributes,
                `@SessionAttributes`, flash attributes
- `rules-engine` a Drools rule

Every candidate carries its **decision points** — each condition, branch,
comparison, access rule, validation annotation, rendering decision, session or
model write, with its line — numbered `DP-00001`… across the scan. The ledger
requires the extraction agent to account for every one: mapped to a rule, or
dismissed as technical with a reason. A candidate with no finer structure has one
decision point, itself. A candidate longer than the per-candidate limit is split
into parts, never truncated. Inline `<script>` blocks of templates are parsed as
JavaScript.
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
    #: [{"id": "DP-00001", "line": n, "kind": "if", "text": the line}] — every decision the candidate makes
    decisions: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "path", "start", "end", "kind", "symbol", "language",
                                              "parser", "signals", "truncated", "area", "status", "reason",
                                              "decisions")}


def _dp(line: int, kind: str, text: str) -> dict:
    return {"id": "", "line": line, "kind": kind, "text": re.sub(r"\s+", " ", text or "").strip()[:200]}


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

# Only named type declarations are separate: a lambda or anonymous class belongs
# to the method that contains it — a reactive pipeline's
# `filter(p -> p.getPrice() > 0)` is that method's rule.
_JAVA_NESTED = ("class_declaration", "interface_declaration", "enum_declaration", "record_declaration")

#: Spring Security's authorization DSL (`antMatchers(...).hasRole(...)`) — rules
#: with no `if` in them.
_AUTHZ_CALLS = {"hasRole", "hasAnyRole", "hasAuthority", "hasAnyAuthority", "permitAll", "denyAll",
                "authenticated", "fullyAuthenticated", "anonymous", "access", "hasIpAddress", "rememberMe"}
_AUTHZ_ANNOTATIONS = {"PreAuthorize", "PostAuthorize", "Secured", "RolesAllowed", "PreFilter", "PostFilter",
                      "DenyAll", "PermitAll"}
_SCHEDULE_ANNOTATIONS = {"Scheduled", "Schedules"}

_SQL_VERB = re.compile(r"\b(?:SELECT|UPDATE|DELETE|MERGE|INSERT\s+INTO)\b", re.I)
_SQL_FILTER = re.compile(r"\bWHERE\b|\bHAVING\b|\bCASE\s+WHEN\b|\bJOIN\b[^;]*?\bON\b|\bQUALIFY\b", re.I)


def is_sql_filter(text: str) -> bool:
    """A SQL statement whose WHERE / HAVING / CASE / JOIN ... ON chooses or
    transforms rows — a business filter, not plumbing."""
    return bool(_SQL_VERB.search(text) and _SQL_FILTER.search(text))


#: Static tables and patterns: normalisation maps, allowed/excluded value sets,
#: code lists and regular expressions are rules expressed as data.
_LOOKUP_INIT = re.compile(
    r"=\s*(?:Map\.(?:of|ofEntries|entry)|Set\.of|List\.of|Arrays\.asList|EnumSet\.(?:of|range)|"
    r"Immutable(?:Map|Set|List|SortedMap|SortedSet)\.|Collections\.(?:unmodifiable\w+|singleton\w*)|"
    r"Stream\.of|new\s+[\w.]+(?:<[^>]*>)?\s*\[\s*\]\s*\{|\{\s*[\"'\d{-]|Pattern\.compile|"
    r"new\s+(?:Hash|Linked|Tree|Enum)(?:Map|Set)\s*<[^>]*>\s*\(\s*\)\s*\{\s*\{)")
_JAVA_TYPES = ("class_declaration", "interface_declaration", "enum_declaration", "record_declaration")


def _decision_signals(body, src: bytes, nested: tuple, lang: str) -> tuple[list[str], bool]:
    """(signals, only_null_checks)"""
    counts = {"if": 0, "switch-case": 0, "ternary": 0, "comparison": 0, "loop-condition": 0}
    throws: list[str] = []
    null_only = True
    literals: list[str] = []
    for n in _walk(body, nested):
        t = n.type
        if lang == "java" and t in ("string_literal", "text_block"):
            literals.append(_text(n, src).strip('"'))
            continue
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
        elif t == "method_invocation" and lang == "java":
            name = n.child_by_field_name("name")
            if name is not None and _text(name, src) in _AUTHZ_CALLS:
                counts["authorization-rule"] = counts.get("authorization-rule", 0) + 1
                null_only = False
        elif t == "throw_statement":
            m = re.search(r"new\s+([\w.]+)", _text(n, src))
            name = m.group(1) if m else "exception"
            throws.append(name)
            if not re.fullmatch(r"(?:java\.lang\.)?(?:NullPointer|IllegalArgument|IllegalState|UnsupportedOperation)Exception|Error", name):
                null_only = False
    if literals and is_sql_filter(" ".join(literals)):
        counts["sql-filter"] = 1                    # the query decides which rows the business sees
        null_only = False
    signals = [f"{k} ×{v}" for k, v in counts.items() if v]
    signals += [f"throws {name}" for name in dict.fromkeys(throws)]
    return signals, null_only


def _decision_points(body, src: bytes, nested: tuple, lang: str) -> list[dict]:
    """Every decision in a body, with its line: each `if` (its condition), `case`,
    ternary, comparison outside an `if`/ternary condition, access-rule call, and SQL
    filter literal."""
    points = []
    conditions: list[tuple[int, int]] = []
    for n in _walk(body, nested):
        t = n.type
        if t == "if_statement":
            cond = n.child_by_field_name("condition")
            if cond is not None:
                conditions.append((cond.start_byte, cond.end_byte))
            points.append(_dp(n.start_point[0] + 1, "if", "if " + (_text(cond, src) if cond is not None else "")))
        elif t in ("switch_label", "switch_case", "switch_rule"):
            points.append(_dp(n.start_point[0] + 1, "case", _text(n, src).split("\n")[0]))
        elif t == "ternary_expression":
            cond = n.child_by_field_name("condition")
            if cond is not None:
                conditions.append((cond.start_byte, cond.end_byte))
            points.append(_dp(n.start_point[0] + 1, "ternary", _text(n, src).split("\n")[0]))
        elif t == "method_invocation" and lang == "java":
            name = n.child_by_field_name("name")
            if name is not None and _text(name, src) in _AUTHZ_CALLS:
                points.append(_dp(n.start_point[0] + 1, "access rule", _text(n, src).split("\n")[0]))
        elif lang == "java" and t in ("string_literal", "text_block") and is_sql_filter(_text(n, src)):
            points.append(_dp(n.start_point[0] + 1, "sql filter", _text(n, src)))
    for n in _walk(body, nested):
        if n.type == "binary_expression":
            op = n.child_by_field_name("operator")
            if op is None or _text(op, src) not in _COMPARISON_OPS:
                continue
            expr = _text(n, src)
            if "null" in expr or "undefined" in expr:
                continue
            if any(a <= n.start_byte and n.end_byte <= b for a, b in conditions):
                continue                                   # part of an if / ternary already listed
            if n.parent is not None and n.parent.type == "binary_expression":
                continue                                   # one point for `a > 1 && b < 2`
            points.append(_dp(n.start_point[0] + 1, "comparison", expr))
    return points


def _split_long(cands: list[Candidate], lines: list[str], max_lines: int) -> list[Candidate]:
    """Candidates longer than `max_lines` split into parts of `max_lines` lines — each
    part analysed, each starting with the candidate's first line for context — instead
    of only the first part being analysed."""
    out = []
    for c in cands:
        if not c.truncated or c.end - c.start + 1 <= max_lines:
            out.append(c)
            continue
        windows = [(a, min(a + max_lines - 1, c.end)) for a in range(c.start, c.end + 1, max_lines)]
        for k, (a, b) in enumerate(windows, 1):
            head = "" if a == c.start else _snippet(lines, c.start, c.start, 1)[0] + "\n   …\n"
            out.append(Candidate(
                id="", path=c.path, start=a, end=b, kind=c.kind, symbol=f"{c.symbol} (part {k} of {len(windows)})",
                language=c.language, parser=c.parser, signals=list(c.signals),
                source=head + _snippet(lines, a, b, max_lines)[0], truncated=False, status=c.status,
                reason=c.reason, decisions=[d for d in c.decisions if a <= d["line"] <= b
                                            or (k == 1 and d["line"] < a)]))
    return out


#: Constraint annotations the repository declares (`@Constraint(validatedBy = …) @interface ValidSku`),
#: found before the Java files are scanned; set by `scan`.
_CUSTOM_CONSTRAINTS: set[str] = set()
_CONSTRAINT_DECL = re.compile(r"@(?:[\w.]+\.)?Constraint\s*\((?:[^()]|\([^()]*\))*\)[\s\S]{0,400}?@interface\s+(\w+)")


def _validation_annotations() -> set[str]:
    return VALIDATION_ANNOTATIONS | _CUSTOM_CONSTRAINTS


#: Classes whose methods carry framework-wide behaviour.
_VALIDATOR_IMPL = re.compile(r"\bimplements\b[^{]*\b(?:ConstraintValidator|Validator)\b")
_INTERCEPTOR_IMPL = re.compile(r"\b(?:implements\b[^{]*\b(?:HandlerInterceptor|WebRequestInterceptor|AsyncHandlerInterceptor|"
                               r"Filter)\b|extends\s+(?:HandlerInterceptorAdapter|OncePerRequestFilter|GenericFilterBean))")
_INTERCEPTOR_METHODS = {"preHandle", "postHandle", "afterCompletion", "doFilter", "doFilterInternal", "afterConcurrentHandlingStarted"}
_SESSION_CALL = re.compile(r"getSession\s*\(|\b\w*[sS]ession\s*\.\s*(?:set|get|remove)Attribute\s*\(|"
                           r"\b\w*[sS]ession\s*\.\s*invalidate\s*\(|addFlashAttribute\s*\(|\.setComplete\s*\(\s*\)|"
                           r"getFlashAttributes?\s*\(|RequestContextUtils\.getInputFlashMap")
_REJECT_CALL = re.compile(r"\.\s*(?:rejectValue|reject|addConstraintViolation|buildConstraintViolationWithTemplate)\s*\(|"
                          r"\.\s*has(?:Field|Global)?Errors\s*\(")
_MODEL_WRITE = re.compile(r"\.\s*(?:addAttribute|addObject|put|setAttribute|setStatus|sendRedirect|sendError)\s*\(")


def _java(path: str, src: bytes, lines: list[str], max_lines: int, out: list[Candidate]) -> None:
    tree = _PARSERS["java"].parse(src)
    package = ""
    for child in tree.root_node.children:
        if child.type == "package_declaration":
            package = re.sub(r"^package\s+|;\s*$", "", _text(child, src)).strip()

    classes: dict[str, dict] = {}                    # qualified name -> what the class is

    def visit(node, owner: str):
        for child in node.children:
            if child.type in _JAVA_TYPES:
                name_node = child.child_by_field_name("name")
                name = _text(name_node, src) if name_node else "?"
                qualified = f"{owner}.{name}" if owner else name
                header = _text(child, src).split("{", 1)[0]
                annos = {a for a, _ in _annotations(child)}
                classes[qualified] = {
                    "validator": bool(_VALIDATOR_IMPL.search(header)),
                    "interceptor": bool(_INTERCEPTOR_IMPL.search(header)),
                    "advice": bool(annos & {"ControllerAdvice", "RestControllerAdvice"}),
                }
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
        class_annos = _annotations(node)
        class_authz = [a for a in class_annos if a[0] in _AUTHZ_ANNOTATIONS]
        if class_authz:
            add(start_row, start_row + len(class_authz), "authorization", owner,
                [f"@{a}{args}" for a, args in class_authz],
                decisions=[_dp(start_row, "access rule", f"@{a}{args}") for a, args in class_authz])
        session = [(a, args) for a, args in class_annos if a == "SessionAttributes"]
        if session:
            add(start_row, start_row + 1, "session-state", owner, [f"@SessionAttributes{session[0][1]}"],
                decisions=[_dp(start_row, "session", f"@SessionAttributes{session[0][1]}")])
        body = node.child_by_field_name("body")
        if body is None:
            return
        validation_rows, constant_rows, validation_signals, constant_names = [], [], [], []
        lookup_rows, lookup_names = [], []
        query_rows, query_names = [], []
        for member in body.children:
            if member.type == "static_initializer":
                text = _text(member, src)
                if re.search(r"\.(?:put|putIfAbsent|add|addAll)\s*\(", text):
                    lookup_rows.append((member.start_point[0] + 1, member.end_point[0] + 1))
                    lookup_names.append("static { … }")
                continue
            if member.type == "field_declaration":
                text = _text(member, src)
                if re.search(r"\bString\b", text) and "=" in text and is_sql_filter(text.split("=", 1)[1]):
                    name_m = re.search(r"(\w+)\s*=", text)
                    query_rows.append((member.start_point[0] + 1, member.end_point[0] + 1))
                    query_names.append(name_m.group(1) if name_m else "?")
                elif re.search(r"\bstatic\b", text) and _LOOKUP_INIT.search(text):
                    name_m = re.search(r"(\w+)\s*=", text)
                    lookup_rows.append((member.start_point[0] + 1, member.end_point[0] + 1))
                    lookup_names.append(name_m.group(1) if name_m else "?")
                annos = [a for a in re.findall(r"@(\w+)", text) if a in _validation_annotations() and a != "Valid"]
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
        def row_points(rows, kind):
            return [_dp(a, kind, " ".join(l.strip() for l in lines[a - 1:b])) for a, b in rows]
        if validation_rows:
            points = [_dp(a, "validation", f"@{anno} on " + " ".join(l.strip() for l in lines[a - 1:b]))
                      for a, b in validation_rows
                      for anno in re.findall(r"@(\w+)", "\n".join(lines[a - 1:b]))
                      if anno in _validation_annotations() and anno != "Valid"]
            add(validation_rows[0][0], validation_rows[-1][1], "validation", owner,
                [f"@{a}" for a in dict.fromkeys(validation_signals)], rows=validation_rows, decisions=points)
        if constant_rows:
            add(constant_rows[0][0], constant_rows[-1][1], "constants", owner,
                [", ".join(constant_names[:12])], rows=constant_rows, decisions=row_points(constant_rows, "constant"))
        if lookup_rows:
            add(lookup_rows[0][0], lookup_rows[-1][1], "lookup", owner,
                [", ".join(lookup_names[:12])], rows=lookup_rows, decisions=row_points(lookup_rows, "lookup"))
        if query_rows:
            add(query_rows[0][0], query_rows[-1][1], "query", owner,
                ["SQL constants: " + ", ".join(query_names[:12])], rows=query_rows,
                decisions=row_points(query_rows, "sql filter"))

    def _java_method(node, owner: str):
        name_node = node.child_by_field_name("name")
        name = _text(name_node, src) if name_node else "<init>"
        body = node.child_by_field_name("body")
        start, end = node.start_point[0] + 1, node.end_point[0] + 1
        params = node.child_by_field_name("parameters")
        params_text = _text(params, src) if params else ""
        param_annos = [a for a in re.findall(r"@(\w+)", params_text)
                       if a in _validation_annotations() and a != "Valid"]
        annotations = _annotations(node)
        anno_names = {a for a, _ in annotations}
        authz = [a for a in annotations if a[0] in _AUTHZ_ANNOTATIONS]
        sched = [a for a in annotations if a[0] in _SCHEDULE_ANNOTATIONS]
        if body is None and not authz:
            return
        signals, null_only = (_decision_signals(body, src, _JAVA_NESTED, "java") if body is not None
                              else ([], True))
        decisions = bool(signals)
        points = _decision_points(body, src, _JAVA_NESTED, "java") if body is not None else []
        body_text = _text(body, src) if body is not None else ""
        body_line = body.start_point[0] + 1 if body is not None else start
        # Framework-wide behaviour: these are candidates even with no branch in them.
        info = classes.get(owner, {})
        special = ""
        if info.get("validator") and name in ("isValid", "validate"):
            special = "validator"
        elif info.get("interceptor") and name in _INTERCEPTOR_METHODS:
            special = "interceptor"
        elif "ExceptionHandler" in anno_names:
            special = "error-mapping"
        elif anno_names & {"ModelAttribute", "InitBinder"}:
            special = "global-model"
        session_lines = [i for i, l in enumerate(body_text.split("\n")) if _SESSION_CALL.search(l)]
        if not special and session_lines:
            special = "session-state"
        for i, line in enumerate(body_text.split("\n")):
            at = body_line + i
            if _REJECT_CALL.search(line):
                points.append(_dp(at, "validation outcome", line))
            elif _SESSION_CALL.search(line):
                points.append(_dp(at, "session", line))
            elif special in ("global-model", "interceptor", "error-mapping") and _MODEL_WRITE.search(line):
                points.append(_dp(at, "model / response", line))
        for a in dict.fromkeys(param_annos):
            points.append(_dp(start, "validation", f"@{a} parameter"))
        for a, args in authz + sched:
            points.append(_dp(start, "access rule" if (a, args) in authz else "schedule", f"@{a}{args}"))
        if "BindingResult" in params_text or re.search(r"\bErrors\s+\w+", params_text):
            signals.append("BindingResult")
        if special:
            signals.append({"validator": "custom validator", "interceptor": "request interceptor/filter",
                            "error-mapping": "@ExceptionHandler", "session-state": "session / flash state",
                            "global-model": "@ModelAttribute/@InitBinder" + (
                                " in @ControllerAdvice (every page)" if info.get("advice") else "")}[special])
        signals += [f"@{a} parameter" for a in dict.fromkeys(param_annos)]
        signals += [f"@{a}{args}" for a, args in authz + sched]
        if not signals:
            return
        status, reason = "pending", ""
        if authz or sched or special:
            pass                                   # an access rule, schedule or framework hook is never plumbing
        elif name in _SKIP_METHODS or (_ACCESSOR.match(name) and end - start <= 3):
            status, reason = "auto-technical", f"`{name}` is an accessor/object method"
        elif null_only and not param_annos:
            status, reason = "auto-technical", "decisions are null checks only"
        only_sql = decisions and all(s.startswith("sql-filter") for s in signals if not s.startswith("@"))
        kind = (special if special else
                "query" if only_sql and not authz and not sched else
                "method" if decisions or param_annos else "authorization" if authz else "scheduled")
        add(start, end, kind, f"{owner}.{name}", signals, status=status, reason=reason, decisions=points)

    def _annotations(node) -> list[tuple[str, str]]:
        """[(name, "(arguments)")] of the declaration's annotations, from its syntax tree."""
        out = []
        for child in node.children:
            if child.type != "modifiers":
                continue
            for a in child.children:
                if a.type in ("annotation", "marker_annotation"):
                    name_node = a.child_by_field_name("name")
                    args = a.child_by_field_name("arguments")
                    name = _text(name_node, src).rsplit(".", 1)[-1] if name_node else ""
                    out.append((name, re.sub(r"\s+", " ", _text(args, src))[:120] if args is not None else ""))
        return out

    def add(start, end, kind, symbol, signals, rows=None, status="pending", reason="", decisions=None):
        if rows and kind in ("validation", "constants", "lookup", "query"):
            text = "\n".join(_snippet(lines, a, b, max_lines)[0] for a, b in rows)
            truncated = False
        else:
            text, truncated = _snippet(lines, start, end, max_lines)
        points = sorted({(d["line"], d["kind"], d["text"]): d for d in (decisions or [])}.values(),
                        key=lambda d: (d["line"], d["kind"]))
        out.append(Candidate(id="", path=path, start=start, end=end, kind=kind,
                             symbol=f"{package}.{symbol}" if package else symbol, language="Java",
                             parser="tree-sitter", signals=signals, source=text, truncated=truncated,
                             status=status, reason=reason, decisions=points))

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
                             truncated=truncated, status=status, reason=reason,
                             decisions=_decision_points(body, src, _JS_NESTED, "js")))


# ---------------------------------------------------------------------------
# Python (ast)
# ---------------------------------------------------------------------------

def _python(path: str, text: str, lines: list[str], max_lines: int, out: list[Candidate]) -> None:
    tree = ast.parse(text)
    _python_lookups(path, tree, lines, max_lines, out)

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
                    points, branch_lines = [], set()
                    for n in _py_own_nodes(child):
                        kind = ("if" if isinstance(n, ast.If) else "ternary" if isinstance(n, ast.IfExp)
                                else "case" if type(n).__name__ == "match_case" else "")
                        if kind:
                            line = getattr(n, "lineno", None) or getattr(getattr(n, "pattern", None), "lineno", start)
                            branch_lines.add(line)
                            points.append(_dp(line, kind, lines[line - 1] if 0 < line <= len(lines) else ""))
                    for n in _py_own_nodes(child):
                        if isinstance(n, ast.Compare) and n.lineno not in branch_lines and not any(
                                isinstance(c, ast.Constant) and c.value is None for c in n.comparators):
                            points.append(_dp(n.lineno, "comparison", lines[n.lineno - 1]))
                    out.append(Candidate(id="", path=path, start=start, end=end, kind="method",
                                         symbol=f"{owner}.{child.name}" if owner else child.name, language="Python",
                                         parser="python-ast", signals=signals, source=snippet, truncated=truncated,
                                         status=status, reason=reason, decisions=points))
                visit(child, f"{owner}.{child.name}" if owner else child.name)

    visit(tree, "")


def _python_lookups(path: str, tree, lines: list[str], max_lines: int, out: list[Candidate]) -> None:
    """Module- and class-level dict/set/list/tuple literals with at least three
    literal entries, and re.compile patterns: rules expressed as data."""
    rows, names = [], []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.col_offset > 4:
            continue
        value = node.value
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        name = next((t.id for t in targets if isinstance(t, ast.Name)), None)
        is_table = (isinstance(value, ast.Dict) and len(value.keys) >= 3) or \
                   (isinstance(value, (ast.Set, ast.List, ast.Tuple)) and len(value.elts) >= 3
                    and all(isinstance(e, ast.Constant) for e in value.elts))
        is_pattern = (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                      and value.func.attr == "compile" and getattr(value.func.value, "id", "") == "re")
        if name and (is_table or is_pattern):
            rows.append((node.lineno, node.end_lineno or node.lineno))
            names.append(name)
    if rows:
        text = "\n".join(_snippet(lines, a, b, max_lines)[0] for a, b in rows)
        out.append(Candidate(id="", path=path, start=rows[0][0], end=rows[-1][1], kind="lookup",
                             symbol=Path(path).stem, language="Python", parser="python-ast",
                             signals=[", ".join(names[:12])], source=text))


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
_SQL_STATEMENT = re.compile(r"^\s*(?:(SELECT|UPDATE|DELETE|MERGE|INSERT)\b|CREATE\s+(?:OR\s+REPLACE\s+)?"
                            r"(?:MATERIALIZED\s+)?VIEW\s+([\w.\"$]+))", re.I)


def _sql(path: str, lines: list[str], max_lines: int, out: list[Candidate]) -> None:
    i = 0
    n = len(lines)
    while i < n:
        routine = _SQL_ROUTINE.match(lines[i])
        table = _SQL_TABLE.match(lines[i])
        statement = None if routine or table else _SQL_STATEMENT.match(lines[i])
        if statement:
            j = i + 1
            # A statement ends at ";", "/" or the next CREATE — never at a nested SELECT
            # (CREATE VIEW v AS <newline> SELECT ... WHERE ...).
            while j < n and not re.search(r";\s*$", lines[j - 1]) and not _SQL_END.match(lines[j]):
                j += 1
            body = "\n".join(lines[i:j])
            if _SQL_FILTER.search(body):
                snippet, truncated = _snippet(lines, i + 1, j, max_lines)
                name = (statement.group(2) or "").strip('"') or f"{statement.group(1).upper()} at line {i + 1}"
                out.append(Candidate(id="", path=path, start=i + 1, end=j, kind="query", symbol=name,
                                     language="SQL", parser="pattern", signals=["sql-filter"], source=snippet,
                                     truncated=truncated))
            i = j if j > i else i + 1
            continue
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


_JSP_DECISION = re.compile(r"<c:(?:if|when)\b[^>]*test\s*=|<%[^@=!-][^%]*\b(?:if|switch)\s*\(|\$\{[^}]*\?[^}]*:[^}]*\}"
                           r"|<sec:authorize\b")
_THYMELEAF_MARK = re.compile(r"xmlns:th\s*=|\bth:[\w-]+\s*=|\bsec:authorize")
_TH = r"\b(?:th|data-th)"
_ATTR = r"\s*=\s*(?:\"[^\"]*\"|'[^']*')"
#: Every rendering decision of a Thymeleaf template, by kind; one decision point per occurrence.
_THYMELEAF_RULES = [
    ("visibility", re.compile(_TH + r"-?:?(?:if|unless)" + _ATTR)),
    ("case", re.compile(_TH + r"-?:?(?:switch|case)" + _ATTR)),
    ("access rule", re.compile(r"\bsec:authorize(?:-url|-expr|-acl)?" + _ATTR)),
    ("list", re.compile(_TH + r"-?:?each" + _ATTR)),
    ("conditional state", re.compile(_TH + r"-?:?(?:disabled|readonly|required|checked|selected|hidden|multiple)"
                                     + _ATTR)),
    ("conditional styling", re.compile(_TH + r"-?:?(?:classappend|class|styleappend|style|attrappend)"
                                       r"\s*=\s*(?:\"[^\"]*(?:\$\{|\*\{|\?)[^\"]*\"|'[^']*(?:\$\{|\*\{|\?)[^']*')")),
    ("formatting", re.compile(r"#(?:numbers|dates|temporals|calendars)\.\w+\s*\([^)]*\)")),
    ("form field", re.compile(_TH + r"-?:?field" + _ATTR)),
    ("form errors", re.compile(_TH + r"-?:?errors" + _ATTR
                               + r"|#fields\.(?:hasErrors|hasAnyErrors|errors|allErrors|hasGlobalErrors)\s*\([^)]*\)")),
    ("server call", re.compile(r"\$\{\s*@\w+\.\w+\s*\([^}]*\}")),
    ("ternary", re.compile(_TH + r"-?:?[\w-]+\s*=\s*\"[^\"]*\?[^\"]*:[^\"]*\"")),
]
#: How many template lines with decisions one candidate holds; more make several candidates.
VIEW_CHUNK_ROWS = 40


def _view_points(lines: list[str], rules) -> list[dict]:
    points = []
    for i, line in enumerate(lines, 1):
        taken: list[tuple[int, int]] = []
        for kind, pattern in rules:
            for m in pattern.finditer(line):
                if any(a < m.end() and m.start() < b for a, b in taken):
                    continue                       # one point per expression, by its most specific kind
                taken.append((m.start(), m.end()))
                points.append(_dp(i, kind, m.group(0)))
    return points


def _view_candidates(path: str, lines: list[str], max_lines: int, points: list[dict], language: str,
                     out: list[Candidate]) -> None:
    """A template's decisions as candidates of at most VIEW_CHUNK_ROWS lines each — every one analysed."""
    rows = sorted({d["line"] for d in points})
    chunks = [rows[i:i + VIEW_CHUNK_ROWS] for i in range(0, len(rows), VIEW_CHUNK_ROWS)]
    for k, chunk in enumerate(chunks, 1):
        text = "\n".join(_snippet(lines, max(1, r - 1), min(len(lines), r + 2), max_lines)[0] for r in chunk)
        mine = [d for d in points if chunk[0] <= d["line"] <= chunk[-1] and d["line"] in chunk]
        kinds = {}
        for d in mine:
            kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
        out.append(Candidate(id="", path=path, start=chunk[0], end=chunk[-1], kind="view-logic",
                             symbol=Path(path).name + (f" (part {k} of {len(chunks)})" if len(chunks) > 1 else ""),
                             language=language, parser="pattern",
                             signals=[f"{kind} ×{n}" for kind, n in kinds.items()], source=text,
                             decisions=mine))


def _jsp(path: str, lines: list[str], max_lines: int, out: list[Candidate]) -> None:
    points = [_dp(i, "visibility", line) for i, line in enumerate(lines, 1) if _JSP_DECISION.search(line)]
    if points:
        _view_candidates(path, lines, max_lines, points, "JSP", out)


def _thymeleaf(path: str, lines: list[str], max_lines: int, out: list[Candidate]) -> bool:
    """A template's rendering decisions, as candidates. False when the file is not a
    Thymeleaf template at all (plain HTML is not scanned for rules)."""
    if not any(_THYMELEAF_MARK.search(line) for line in lines):
        return False
    points = _view_points(lines, _THYMELEAF_RULES)
    if points:
        _view_candidates(path, lines, max_lines, points, "Thymeleaf", out)
    return True


_SCRIPT_BLOCK = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)


def _inline_scripts(path: str, text: str, lines: list[str], max_lines: int, language: str,
                    out: list[Candidate]) -> None:
    """Inline `<script>` blocks of a template parsed as JavaScript, at their own line numbers."""
    if "javascript" not in _PARSERS or "<script" not in text.lower():
        return
    kept = []
    for m in _SCRIPT_BLOCK.finditer(text):
        attrs = m.group(1)
        kind = re.search(r"\btype\s*=\s*[\"']([^\"']+)", attrs)
        if re.search(r"\bsrc\s*=", attrs) or (kind and not re.search(r"javascript|module|babel|jsx", kind.group(1), re.I)):
            continue
        kept.append((m.start(2), m.end(2)))
    if not kept:
        return
    chars = ["\n" if ch == "\n" else " " for ch in text]
    for a, b in kept:
        chars[a:b] = list(text[a:b])
    # Thymeleaf inlined expressions ([[${x}]], /*[[...]]*/) are values to the script.
    code = re.sub(r"\[\[(.*?)\]\]|\[\((.*?)\)\]", lambda m: "0" + " " * (len(m.group(0)) - 1), "".join(chars))
    before = len(out)
    _js(path, code.encode("utf-8", "replace"), lines, max_lines, "javascript", language, out)
    for c in out[before:]:
        c.symbol = f"<script> {c.symbol}"
        c.signals.append("inline script")


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

# ---------------------------------------------------------------------------
# Template / configuration data files
# ---------------------------------------------------------------------------

_DATA_SUFFIXES = {".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".xml": "XML", ".properties": "Properties",
                  ".csv": "CSV"}
#: Folders whose structured files define behaviour: category templates, rule
#: sets, mappings, lookups, reference data.
_RULE_DATA_DIRS = re.compile(r"(?:^|/)(?:templates?|rules?|rulesets?|mappings?|lookups?|refdata|reference[-_]?data|"
                             r"standards?|standardi[sz]ation|categories|dictionar(?:y|ies)|validations?|"
                             r"transformations?|normali[sz]ations?)/", re.I)
#: Build, deployment, logging and environment files are not rule data (the
#: environment files are covered by the configuration matrix instead).
_NOT_RULE_DATA = re.compile(r"(?:^|/)(?:pom\.xml|package(?:-lock)?\.json|tsconfig[\w.-]*\.json|\.eslintrc[\w.]*|"
                            r"log4j2?[\w.-]*|logback[\w.-]*|application(?:-[\w.-]+)?\.(?:ya?ml|properties)|"
                            r"bootstrap(?:-[\w.-]+)?\.(?:ya?ml|properties)|docker-compose[\w.-]*|"
                            r"\.gitlab-ci\.yml|web\.xml|persistence\.xml|beans\.xml|[\w-]*context\.xml)$|"
                            r"(?:^|/)(?:\.github|\.circleci|k8s|kubernetes|helm|charts|deploy(?:ment)?s?|"
                            r"META-INF)/", re.I)


_MYBATIS_STATEMENT = re.compile(r"<(select|update|delete|insert)\b[^>]*\bid\s*=\s*\"([^\"]+)\"", re.I)


def _mybatis(path: str, lines: list[str], max_lines: int, out: list[Candidate]) -> None:
    """Each mapped statement whose SQL filters rows or whose dynamic SQL decides
    (<if test>, <choose>/<when>)."""
    i = 0
    while i < len(lines):
        m = _MYBATIS_STATEMENT.search(lines[i])
        if not m:
            i += 1
            continue
        j = i
        close = re.compile(rf"</{m.group(1)}\s*>", re.I)
        while j < len(lines) and not close.search(lines[j]):
            j += 1
        body = "\n".join(lines[i:j + 1])
        dynamic = len(re.findall(r"<(?:if|when)\b[^>]*\btest\s*=", body, re.I))
        if _SQL_FILTER.search(body) or dynamic:
            snippet, truncated = _snippet(lines, i + 1, min(j + 1, len(lines)), max_lines)
            out.append(Candidate(id="", path=path, start=i + 1, end=min(j + 1, len(lines)), kind="query",
                                 symbol=m.group(2), language="MyBatis XML", parser="pattern",
                                 signals=["sql-filter"] + ([f"dynamic condition ×{dynamic}"] if dynamic else []),
                                 source=snippet, truncated=truncated))
        i = j + 1


def is_rule_data(rel: str) -> bool:
    if _NOT_RULE_DATA.search(rel):
        return False
    return bool(_RULE_DATA_DIRS.search(rel)) or (rel.lower().endswith(".csv") and "/resources/" in f"/{rel}")


def _data_file(path: str, language: str, lines: list[str], max_lines: int, out: list[Candidate]) -> None:
    """One candidate per file, or per consecutive part of a long one — every line
    is shown to the extractor, none is cut."""
    body = [i for i, line in enumerate(lines, 1) if line.strip()]
    if not body:
        return
    first, last = body[0], body[-1]
    parts = list(range(first, last + 1, max_lines))
    for n, start in enumerate(parts, 1):
        end = min(start + max_lines - 1, last)
        snippet, _ = _snippet(lines, start, end, max_lines)
        label = Path(path).name + (f" (part {n}/{len(parts)})" if len(parts) > 1 else "")
        out.append(Candidate(id="", path=path, start=start, end=end, kind="config-rule", symbol=label,
                             language=language, parser="structured file",
                             signals=[f"{language} definition, lines {start}-{end}"], source=snippet))

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
    ".html": ("Thymeleaf", "thymeleaf", "pattern"), ".htm": ("Thymeleaf", "thymeleaf", "pattern"),
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
    # Constraint annotations the repository declares itself count as validation everywhere.
    _CUSTOM_CONSTRAINTS.clear()
    for path in sorted(root.rglob("*.java")):
        if EXCLUDED_DIRS & set(path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace") if path.stat().st_size <= _MAX_FILE_BYTES else ""
        except OSError:
            continue
        if "@interface" in text and "Constraint" in text:
            _CUSTOM_CONSTRAINTS.update(_CONSTRAINT_DECL.findall(text))
    templates: dict[str, str] = {}                  # Thymeleaf template -> its text, for fragment links
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        parts = set(Path(rel).parts)
        if EXCLUDED_DIRS & parts or "node_modules" in parts:
            continue
        suffix = path.suffix.lower()
        if suffix == ".xml" and not _TEST_PATH.search(rel):
            try:
                head = path.read_text(encoding="utf-8", errors="replace")[:4000] \
                    if path.stat().st_size <= _MAX_FILE_BYTES else ""
            except OSError:
                head = ""
            if re.search(r"<mapper\b[^>]*namespace\s*=", head) or "mybatis.org//DTD Mapper" in head:
                entry = by_language.setdefault("MyBatis XML", {"files": 0, "parser": "pattern"})
                entry["files"] += 1
                _mybatis(rel, path.read_text(encoding="utf-8", errors="replace").splitlines(), max_lines, candidates)
                continue
        if suffix in _DATA_SUFFIXES and is_rule_data(rel) and not _TEST_PATH.search(rel):
            try:
                data_text = path.read_text(encoding="utf-8", errors="replace") \
                    if path.stat().st_size <= _MAX_FILE_BYTES else ""
            except OSError as exc:
                errors.append(f"{rel}: {exc}")
                continue
            if not data_text:
                errors.append(f"{rel}: larger than {_MAX_FILE_BYTES // 1_000_000} MB, not scanned")
                continue
            language = _DATA_SUFFIXES[suffix]
            entry = by_language.setdefault(language, {"files": 0, "parser": "structured file"})
            entry["files"] += 1
            _data_file(rel, language, data_text.splitlines(), max_lines, candidates)
            continue
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
        before = len(candidates)
        if key == "thymeleaf":
            # Only templates count; plain HTML pages carry no rules to parse.
            if _thymeleaf(rel, lines, max_lines, candidates):
                entry = by_language.setdefault(language, {"files": 0, "parser": parser})
                entry["files"] += 1
                templates[rel] = text
                _inline_scripts(rel, text, lines, max_lines, language, candidates)
                candidates[before:] = _split_long(candidates[before:], lines, max_lines)
            continue
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
                _inline_scripts(rel, text, lines, max_lines, language, candidates)
            elif key == "drl":
                _drl(rel, lines, max_lines, candidates)
            else:
                unparsed[language] = unparsed.get(language, 0) + 1
        except (SyntaxError, ValueError, RecursionError) as exc:
            errors.append(f"{rel}: could not be parsed ({type(exc).__name__})")
        candidates[before:] = _split_long(candidates[before:], lines, max_lines)
    _link_fragments(candidates, templates)
    _assign_areas(candidates)
    candidates.sort(key=lambda c: (c.area, c.path, c.start))
    n = 0
    for i, c in enumerate(candidates, 1):
        c.id = f"C{i:05d}"
        if not c.decisions:                    # no finer structure: the candidate is its one decision point
            c.decisions = [_dp(c.start, c.kind, c.symbol)]
        for d in c.decisions:
            n += 1
            d["id"] = f"DP-{n:05d}"
    return Scan(candidates, by_language, unparsed, errors, tests, TREE_SITTER_ERROR)


_INCLUDE = re.compile(r"\b(?:th|data-th)[-:](?:replace|insert|include|substituteby|decorate)\s*=\s*[\"']~?\{?\s*([\w/.-]+)|"
                      r"\blayout:decorate\s*=\s*[\"']~?\{?\s*([\w/.-]+)|\bdata-layout-decorate\s*=\s*[\"']~?\{?\s*([\w/.-]+)")


def _link_fragments(candidates: list[Candidate], templates: dict[str, str]) -> None:
    """A fragment's or layout's decisions apply on every page that includes it: say which pages."""
    def name_of(rel: str) -> str:
        m = re.search(r"(?:^|/)templates/(.+?)\.html?$", rel)
        return m.group(1) if m else re.sub(r"\.html?$", "", rel.rsplit("/", 1)[-1])
    used: dict[str, set] = {}
    for rel, text in templates.items():
        for m in _INCLUDE.finditer(text):
            target = next(g for g in m.groups() if g).split("::")[0].strip()
            if target and target != name_of(rel):
                used.setdefault(target, set()).add(rel)
    for c in candidates:
        if c.path in templates:
            pages = sorted(used.get(name_of(c.path), ()))
            if pages:
                c.signals.append("included by: " + ", ".join(pages))


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
            root = _SOURCE_ROOTS.match(c.path)
            rel = c.path[root.end():] if root else c.path
            parent = str(Path(rel).parent)
            if parent != ".":
                c.area = "/".join(Path(parent).parts[:2])
            else:
                # Directly under a source root (src/main/webapp/orders.jsp): name the root
                # ("webapp"), not "(root)", which reads as the repository root.
                c.area = root.group(0).rstrip("/").rsplit("/", 1)[-1] if root else "(root)"
