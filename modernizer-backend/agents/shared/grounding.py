"""
Grounding checks: every fact the documents state must be traceable to the
repository's code. Deterministic — no model checks a model.

Three levels, each run before anything reaches a document:

1. **Evidence items** (`verify_pack`) — what the evidence specialists report.
   An item must cite a file that exists in the repository (and a line inside
   it), and any code it quotes must occur in a file it cites. Items that fail
   are withheld from the writers.

2. **Business rules and their scenarios** (`check_rule`) — against the exact
   code the rule was extracted from:
   - every number and every quoted message in the text must appear in that code
     (numbers: also one either side, for "exactly 50" / "51"; a percentage also
     as a fraction) or, for a message, in the repository's message files;
   - the statement's key words must relate to the code's own names and strings;
   - a scenario must match something the code does: a missing-value case needs
     a null / empty check, a boundary case a comparison, an access case a role
     or authentication check, a date case date or schedule logic, an error case
     an error path.

3. **BRD statements** (`check_brd`) — every statement must cite evidence or a
   rule that passed the checks above, and its numbers and quoted messages must
   appear in what it cites.

4. **The Technical Specification's UI Interaction Contracts** (`check_ui_section`)
   — every UI element id must be one the scan found, every `METHOD /path` a call
   or handler it found, every name in backticks and every number or quoted
   message must appear in the computed UI-to-Backend Contracts or in the
   evidence items the statement cites.

What fails is never shown in the business documents; the audit file lists it
with the reason.
"""
import re
from pathlib import Path

from .dependency_graph import EXCLUDED_DIRS

# ── values ──────────────────────────────────────────────────────────────────

_NUMBER_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
                 "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
                 "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
                 "hundred": 100, "thousand": 1000}
_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(\s*%)?(?![\w])")
_QUOTED = re.compile(r"[“\"]([^”\"]{3,200})[”\"]|(?<![\w])'([^']{3,200})'(?![\w])")
_ALWAYS_OK = {0.0, 1.0}           # "no", "one", "a single": ordinary language, not a claim about the code


def numbers_in(text: str, words: bool = True) -> set[float]:
    """Numbers stated in `text` ("50", "1,000", "10%", "fifty")."""
    out = set()
    for m in _NUMBER.finditer(text or ""):
        value = float(m.group(1).replace(",", ""))
        out.add(value)
        if m.group(2):
            out.add(round(value / 100, 6))
    if words:
        for w in re.findall(r"[a-z]+", (text or "").lower()):
            if w in _NUMBER_WORDS:
                out.add(float(_NUMBER_WORDS[w]))
    return out


def code_numbers(code: str) -> set[float]:
    found = set()
    for m in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)", code or ""):
        try:
            found.add(float(m.group(1)))
        except ValueError:
            continue
    return found


def _number_ok(value: float, available: set[float]) -> bool:
    if value in _ALWAYS_OK or value in available:
        return True
    if value == int(value) and (value - 1 in available or value + 1 in available):
        return True                                   # boundary arithmetic: "more than 50" ↔ "51"
    return any(abs(value * 100 - a) < 1e-6 or abs(value - a * 100) < 1e-6 for a in available)


def quoted_in(text: str) -> list[str]:
    return [a or b for a, b in _QUOTED.findall(text or "")]


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w%$€£]+", " ", (text or "").lower()).split())


def strip_line_numbers(source: str) -> str:
    """Candidate source as the model saw it ("  12| code") → the code."""
    return "\n".join(re.sub(r"^\s*\d+\|\s?", "", line) for line in (source or "").splitlines())


def unsupported_values(text: str, code: str, extra_text: str = "", extra_numbers: set[float] = frozenset()) -> list[str]:
    """Numbers and quoted messages in `text` that `code` (or `extra_text`) does not contain."""
    problems = []
    available = code_numbers(code) | code_numbers(extra_text) | set(extra_numbers)
    for value in sorted(numbers_in(text)):
        if not _number_ok(value, available):
            problems.append(f"the value {value:g} does not appear in the code")
    haystack = _norm(code) + " " + _norm(extra_text)
    for q in quoted_in(text):
        if _norm(q) and _norm(q) not in haystack:
            problems.append(f"the text “{q}” does not appear in the code")
    return problems


# ── vocabulary ──────────────────────────────────────────────────────────────

_GENERIC = set("""
system systems user users rule rules apply applies applied applying step steps value values request requests data
record records process processes processed allowed allow allows rejected reject rejects accepted accept accepts
approved approve must when where which their there with without only more less than then that this those these
given into from have has having been being does done make makes made each every other another same such some
any none also back once again shown shows show sees seen message messages error errors check checks checked
condition conditions case cases scenario scenarios outcome outcomes stops stopped stop goes ahead proceed
proceeds continue continues treated treat within limit limits exactly least most above below greater fewer
under over missing empty blank provided valid invalid able unable cannot after before while during whether
because using used uses based following first second last next previous returns return returned true false
""".split())


def _stem(word: str) -> str:
    return word[:5] if len(word) > 5 else word


def code_vocabulary(code: str) -> set[str]:
    """Stems of the words in the code's names, strings and comments."""
    words = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_]*", code or ""):
        for part in re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", token).replace("_", " ").split():
            if len(part) >= 3:
                words.add(_stem(part.lower()))
    return words


def significant_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in _GENERIC]


def unrelated_terms(text: str, code: str, extra_text: str = "") -> list[str]:
    """When none of the statement's key words relate to the code's names or strings."""
    words = significant_words(text)
    if len(words) < 3:
        return []
    vocab = code_vocabulary(code) | code_vocabulary(extra_text)
    if any(_stem(w) in vocab for w in words):
        return []
    return ["none of its key terms (" + ", ".join(sorted(set(words))[:6]) + ") relate to the code"]


# ── scenario kinds ──────────────────────────────────────────────────────────

_KINDS = {
    "a missing or empty value": (
        r"\b(missing|empty|blank|not provided|not given|no value|left out|absent|without an?\b|null)\b",
        r"null|None\b|isEmpty|isBlank|empty\(|isNull|Optional|NOT\s+NULL|IS\s+NULL|required|@Not(?:Null|Blank|Empty)"
        r"|==\s*''|===\s*''|\.length\s*(?:==|===|<)|\.size\(\)\s*(?:==|<)|#(?:lists|strings|arrays)\.isEmpty|"
        r"th:unless|is_empty|nvl|coalesce|\bnot\s+\w|!\s*\w"),
    "a boundary or limit": (
        r"\b(exactly|boundary|limit|maximum|minimum|at least|at most|more than|less than|greater|fewer|up to|"
        r"largest|smallest|longest|shortest|threshold|above|below|exceed\w*|under|over)\b",
        r"[<>]=?|between|BETWEEN|\bmin\b|\bmax\b|Min|Max|@Size|@Range|@Decimal|compareTo|isAfter|isBefore|"
        r"limit|LIMIT|length|size\(|MAX_|MIN_|threshold|THRESHOLD"),
    "an access or role check": (
        r"\b(access|permission|role|roles|authori[sz]\w*|administrator|admin|signed in|signed out|sign in|"
        r"logged in|log in|not allowed to|privilege\w*|forbidden)\b",
        r"hasRole|hasAnyRole|hasAuthority|isUserInRole|@PreAuthorize|@Secured|@RolesAllowed|sec:authorize|"
        r"isAuthenticated|isAnonymous|principal|Principal|ROLE_|permitAll|denyAll|authenticated|Authentication|"
        r"j_security_check|security-constraint|login"),
    "a date, time or schedule": (
        r"\b(date|dates|time|times|expired?|expiry|schedule\w*|nightly|daily|weekly|monthly|deadline|days?|"
        r"hours?|minutes?|older|newer|past|future|overdue)\b",
        r"Date|Time|Instant|Clock|now\(|SYSDATE|CURRENT_DATE|CURRENT_TIMESTAMP|@Scheduled|cron|expir|isAfter|"
        r"isBefore|Duration|Period|TimeUnit|timestamp|TIMESTAMP|datetime|#temporals|#dates"),
}


def missing_behaviour(text: str, code: str) -> list[str]:
    """Kinds of case the text describes that the code has no sign of."""
    problems = []
    for kind, (says, shows) in _KINDS.items():
        if re.search(says, text or "", re.I) and not re.search(shows, code or ""):
            problems.append(f"it describes {kind}, which the code does not check")
    return problems


# ── rules ───────────────────────────────────────────────────────────────────

def check_rule(rule: dict, source: str, repo_text: str = "") -> dict:
    """{"statement": [reasons], "use_cases": [[reasons] per entry], ...} — empty lists when grounded."""
    code = strip_line_numbers(source)
    statement = rule.get("statement", "")
    verdict = {"statement": unsupported_values(statement, code, repo_text)
               + unrelated_terms(statement, code, repo_text)}
    for key in ("use_cases", "negative_scenarios", "edge_cases"):
        verdict[key] = [unsupported_values(entry, code, repo_text) + missing_behaviour(entry, code)
                        for entry in rule.get(key, [])]
    return verdict


def is_grounded(verdict: dict) -> bool:
    return not verdict.get("statement") and not any(r for key in ("use_cases", "negative_scenarios", "edge_cases")
                                                     for r in verdict.get(key, []))


def describe(verdict: dict, rule: dict) -> list[str]:
    """The verdict as feedback lines for the extraction agent."""
    lines = [f"statement “{rule.get('statement', '')}”: " + "; ".join(verdict["statement"])] \
        if verdict.get("statement") else []
    for key in ("use_cases", "negative_scenarios", "edge_cases"):
        for entry, reasons in zip(rule.get(key, []), verdict.get(key, [])):
            if reasons:
                lines.append(f"{key.replace('_', ' ')[:-1]} “{entry}”: " + "; ".join(reasons))
    return lines


def repo_text(workspace_dir: str, max_bytes: int = 4_000_000) -> str:
    """The repository's message and label texts (properties and message bundles), so a
    rule may quote the message a user is shown even when its code names only the key."""
    root = Path(workspace_dir or "/nonexistent")
    parts, size = [], 0
    if not root.is_dir():
        return ""
    for path in sorted(root.rglob("*.properties")):
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(Path(rel).parts) or path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        values = "\n".join(line.split("=", 1)[1] for line in text.splitlines() if "=" in line
                           and not line.lstrip().startswith(("#", "!")))
        size += len(values)
        if size > max_bytes:
            break
        parts.append(values)
    return "\n".join(parts)


# ── evidence items ──────────────────────────────────────────────────────────

_REF = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.[A-Za-z][\w]{0,9})(?::(\d+)(?:-(\d+))?)?")
_SNIPPET = re.compile(r"`([^`\n]{4,400})`")
_REDACTION = re.compile(r"\[(?:REDACTED|encrypted|secret reference)\]|\*{3,}|…|\.\.\.")
_EXEMPT = ("Limitations",)


class _Files:
    def __init__(self, workspace_dir: str):
        self.root = Path(workspace_dir or "/nonexistent")
        self.by_name: dict[str, list[str]] = {}
        self.cache: dict[str, str | None] = {}
        if self.root.is_dir():
            for p in self.root.rglob("*"):
                rel = p.relative_to(self.root).as_posix()
                if p.is_file() and not p.is_symlink() and not (EXCLUDED_DIRS & set(Path(rel).parts)):
                    self.by_name.setdefault(p.name, []).append(rel)

    def resolve(self, ref: str) -> str | None:
        """A cited path → the repository file it names (exact, or a unique path ending)."""
        ref = ref.lstrip("./")
        if (self.root / ref).is_file():
            return ref
        matches = [r for r in self.by_name.get(Path(ref).name, []) if r.endswith(ref)]
        return matches[0] if len(matches) == 1 else None

    def text(self, rel: str) -> str:
        if rel not in self.cache:
            try:
                self.cache[rel] = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                self.cache[rel] = None
        return self.cache[rel] or ""


def _snippet_found(snippet: str, texts: list[str]) -> bool:
    pieces = [p.strip() for p in _REDACTION.split(snippet) if len(p.strip()) >= 4]
    if not pieces:
        return True
    flat = [" ".join(t.split()) for t in texts]
    return all(any(" ".join(p.split()) in f for f in flat) for p in pieces)


def verify_item(text: str, files: "_Files") -> str | None:
    """Why an evidence item cannot be traced to the repository, or None when it can."""
    refs = [(m.group(1), m.group(2)) for m in _REF.finditer(text)]
    resolved = []
    for ref, line in refs:
        rel = files.resolve(ref)
        if rel is None:
            continue
        if line and int(line) > max(1, files.text(rel).count("\n") + 1):
            return f"`{ref}` has no line {line}"
        resolved.append(rel)
    if not resolved:
        return "it cites no file of the repository" if not refs else \
            "the file it cites (" + ", ".join(sorted({r for r, _ in refs})[:3]) + ") is not in the repository"
    snippets = [s for s in _SNIPPET.findall(text) if not _REF.fullmatch(s.strip()) and files.resolve(s.strip()) is None]
    texts = [files.text(r) for r in resolved]
    missing = [s for s in snippets if not _snippet_found(s, texts)]
    if snippets and len(missing) == len(snippets):
        return f"the code it quotes (`{missing[0][:60]}`) is not in the file it cites"
    return None


def verify_pack(text: str, workspace_dir: str, files: "_Files | None" = None) -> tuple[str, list[tuple[str, str]]]:
    """(pack without the items that cannot be traced, [(evidence id, reason)])."""
    from .evidence_pack import _HEADING, canonical
    files = files or _Files(workspace_dir)
    out, rejected, section, skipping = [], [], None, False
    for line in (text or "").splitlines():
        heading = _HEADING.match(line)
        if heading:
            section, skipping = canonical(heading.group(2)), False
            out.append(line)
            continue
        m = re.match(r"^- \[(EV-[^\]]+)\]\s*(.*)$", line)
        if m:
            skipping = False
            if section not in _EXEMPT:
                reason = verify_item(m.group(2), files)
                if reason:
                    rejected.append((m.group(1), reason))
                    skipping = True
                    continue
        elif skipping and line.startswith((" ", "\t")):
            continue                                   # a continuation line of a withheld item
        else:
            skipping = False
        out.append(line)
    return "\n".join(out), rejected


def files_index(workspace_dir: str) -> "_Files":
    return _Files(workspace_dir)


# ── BRD statements ──────────────────────────────────────────────────────────

_EXEMPT_SECTIONS = ("executive summary", "open questions", "business rules by capability")


def check_brd(markdown: str, evidence: dict[str, str], rules: dict[str, str],
              allowed_numbers: set[float] = frozenset()) -> tuple[str, list[tuple[str, str]]]:
    """(BRD without the statements that cannot be traced, [(statement, reason)]).

    A statement is a paragraph, a list item or a table row. In the sections that
    state facts it must cite at least one evidence item or rule that exists (and
    passed the checks), and its numbers and quoted messages must appear in what
    it cites. A numbered list (a scenario's steps) is one statement: citations
    anywhere in it cover its steps. The Executive Summary need not cite, but its
    values must appear in the evidence or rules; Open Questions are not claims."""
    from .evidence_pack import BR_ID, EV_ID
    every_text = "\n".join(list(evidence.values()) + list(rules.values()))
    lines = (markdown or "").split("\n")
    out: list[str] = []
    removed: list[tuple[str, str]] = []
    section = ""
    heading_at = -1                       # index in `out` of the current heading
    emptied: set[int] = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            if len(heading.group(1)) <= 2:
                section = heading.group(2).strip().lower()
            out.append(line)
            heading_at = len(out) - 1
            i += 1
            continue
        if not line.strip() or re.match(r"^\s*\|?\s*:?-{2,}", line) or line.strip().startswith("<!--"):
            out.append(line)
            i += 1
            continue
        # One statement: a numbered list as a whole, else the line with its continuation lines.
        j = i + 1
        if re.match(r"^\s*\d+[.)]\s", line):
            while j < len(lines) and (re.match(r"^\s*\d+[.)]\s", lines[j]) or
                                      (lines[j].startswith(("   ", "\t")) and lines[j].strip())):
                j += 1
        elif not line.lstrip().startswith("|"):
            while j < len(lines) and lines[j].strip() and lines[j].startswith(("  ", "\t")) \
                    and not re.match(r"^\s*(?:[-*+]|\d+[.)])\s", lines[j]):
                j += 1
        block = "\n".join(lines[i:j])
        if section.startswith(_EXEMPT_SECTIONS[1]) or section.startswith(_EXEMPT_SECTIONS[2]):
            out.extend(lines[i:j])
            i = j
            continue
        header_row = block.lstrip().startswith("|") and j < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[j])
        if header_row:
            out.extend(lines[i:j])
            i = j
            continue
        ev = [e for e in EV_ID.findall(block) if e in evidence]
        br = [b for b in BR_ID.findall(block) if b in rules]
        reason = None
        if section.startswith(_EXEMPT_SECTIONS[0]):
            problems = unsupported_values(_without_ids(block), every_text, extra_numbers=allowed_numbers)
            reason = "; ".join(problems) if problems else None
        elif not ev and not br:
            reason = "it cites no evidence or business rule that could be traced to the code"
        else:
            cited = "\n".join([evidence[e] for e in ev] + [rules[b] for b in br])
            problems = unsupported_values(_without_ids(block), cited, extra_numbers=allowed_numbers)
            reason = "; ".join(problems) if problems else None
        if reason:
            removed.append((" ".join(block.split())[:300], reason))
            emptied.add(heading_at)
        else:
            out.extend(lines[i:j])
        i = j
    # A heading left with nothing under it says what is missing, instead of standing empty.
    from .plain_language import EMPTIED
    for at in sorted((h for h in emptied if h >= 0), reverse=True):
        nxt = next((k for k in range(at + 1, len(out)) if re.match(r"^#{1,6}\s", out[k])), len(out))
        if not any(l.strip() and not re.match(r"^\s*\|?\s*:?-{2,}", l) for l in out[at + 1:nxt]):
            out[at + 1:nxt] = ["", EMPTIED, ""]
    return "\n".join(out), removed


# ── UI interaction contracts (Technical Specification) ──────────────────────

UI_SECTION = re.compile(r"^##\s+(?:\d+[.)]\s*)?UI Interaction Contracts\b", re.I)
UI_EMPTIED = ("_Nothing written here could be traced to the computed UI-to-Backend Contracts or the evidence; "
              "use the computed section._")
_UI_ID = re.compile(r"\bUI-\d{3,}\b")
_HTTP_CALL = re.compile(r"\b(GET|POST|PUT|DELETE|PATCH|ANY)\s+`?(/[^\s`|),;]*)")
_TICKED = re.compile(r"`([^`\n]{1,160})`")
_TICK_SKIP = {"get", "post", "put", "delete", "patch", "any", "json", "query", "path", "form", "body", "header",
              "string", "integer", "number", "boolean", "date", "time", "list", "map", "object", "null", "true",
              "false", "id", "ids"}


def _call_key(verb: str, path: str) -> tuple[str, str]:
    path = re.sub(r"\{[^}/]*\}", "{}", path.split("?", 1)[0].rstrip(".:!'\"")).rstrip("/") or "/"
    return verb.upper(), path


def check_ui_section(markdown: str, contracts_md: str, element_ids: set[str],
                     calls: set[tuple[str, str]], evidence: dict[str, str],
                     placeholder: bool = True) -> tuple[str, list[tuple[str, str]]]:
    """(specification without the UI Interaction Contracts statements that cannot be
    traced, [(statement, reason)]).

    Only the `## UI Interaction Contracts` section is checked. A statement (a
    paragraph, a list item with its continuation lines, a numbered list, a table
    row) is removed when it names a UI element id the scan did not find, an HTTP
    call (`POST /api/jobs`) that is neither a call the UI makes nor a handler
    path, a name in backticks that appears neither in the computed contracts nor
    in the evidence items it cites, or a number or quoted message that appears
    in neither."""
    from .evidence_pack import EV_ID
    lines = (markdown or "").split("\n")
    start = next((i for i, l in enumerate(lines) if UI_SECTION.match(l)), None)
    if start is None:
        return markdown, []
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^#{1,2}\s", lines[i])), len(lines))
    known_calls = {_call_key(v, p) for v, p in calls}
    any_verb = {p for v, p in known_calls if v == "ANY"}
    out: list[str] = lines[:start + 1]
    removed: list[tuple[str, str]] = []
    heading_at, emptied = start, set()
    i = start + 1
    while i < end:
        line = lines[i]
        if re.match(r"^#{3,6}\s", line):
            out.append(line)
            heading_at = len(out) - 1
            i += 1
            continue
        if not line.strip() or re.match(r"^\s*\|?\s*:?-{2,}", line) or line.strip().startswith("<!--"):
            out.append(line)
            i += 1
            continue
        j = i + 1
        if re.match(r"^\s*\d+[.)]\s", line):
            while j < end and (re.match(r"^\s*\d+[.)]\s", lines[j]) or
                               (lines[j].startswith(("   ", "\t")) and lines[j].strip())):
                j += 1
        elif not line.lstrip().startswith("|"):
            while j < end and lines[j].strip() and lines[j].startswith(("  ", "\t")) \
                    and not re.match(r"^\s*(?:[-*+]|\d+[.)])\s", lines[j]):
                j += 1
        block = "\n".join(lines[i:j])
        if block.lstrip().startswith("|") and j < end and re.match(r"^\s*\|?\s*:?-{2,}", lines[j]):
            out.extend(lines[i:j])                          # a table's header row
            i = j
            continue
        cited = "\n".join(evidence[e] for e in EV_ID.findall(block) if e in evidence)
        vocabulary = contracts_md + "\n" + cited
        words = {w.lower() for w in re.findall(r"[A-Za-z_]\w*", vocabulary)}
        problems = []
        unknown_ids = sorted(set(_UI_ID.findall(block)) - element_ids)
        if unknown_ids:
            problems.append(f"names UI element {', '.join(unknown_ids)}, which the scan did not find")
        for verb, path in _HTTP_CALL.findall(block):
            key = _call_key(verb, path)
            if key not in known_calls and key[1] not in any_verb and not (verb == "ANY" and
                                                                          any(p == key[1] for _, p in known_calls)):
                problems.append(f"the call {verb} {key[1]} is not one the UI makes or a handler serves")
        for ticked in _TICKED.findall(block):
            if _HTTP_CALL.search(ticked) or ticked.startswith("/") or EV_ID.fullmatch(ticked) or \
                    _UI_ID.fullmatch(ticked):
                continue
            unknown = [w for w in re.findall(r"[A-Za-z_]\w*", ticked)
                       if len(w) > 1 and w.lower() not in _TICK_SKIP and w.lower() not in words]
            if unknown:
                problems.append(f"`{ticked}` is not in the computed contracts or the evidence it cites")
        problems += unsupported_values(_UI_ID.sub("", _without_ids(block)), vocabulary)
        if problems:
            removed.append((" ".join(block.split())[:300], "; ".join(dict.fromkeys(problems))))
            emptied.add(heading_at)
        else:
            out.extend(lines[i:j])
        i = j
    tail = lines[end:]
    for at in sorted(emptied if placeholder else (), reverse=True):
        nxt = next((k for k in range(at + 1, len(out)) if re.match(r"^#{1,6}\s", out[k])), len(out))
        if not any(l.strip() and not re.match(r"^\s*\|?\s*:?-{2,}", l) for l in out[at + 1:nxt]):
            out[at + 1:nxt] = ["", UI_EMPTIED, ""]
    return "\n".join(out + tail), removed


# ── abbreviated lists ───────────────────────────────────────────────────────

_NOUNS = (r"(?:web\s+)?(?:pages?|end-?\s?points?|screens?|routes?|apis?|services?|classes|interfaces|tables|jobs|"
          r"listeners|queues|topics|fields|files|tests?|test\s+cases|controllers|components|rows|items|templates|"
          r"properties|keys|entities|methods|handlers|operations|modules|dependencies|parameters|views|forms|"
          r"elements|controls|rules|scenarios|columns|resources|beans|packages|stacks)")
ELISION = re.compile(
    r"\[\s*(?:\.{3}|…)[^\]\n]{0,80}\]"                                       # [...27 more web pages]
    r"|(?:\.{3}|…)\s*(?:and\s+|\+\s*)?\d[\d,]*\s+(?:more|others?|additional|further)\b[^|\n.;)]{0,60}"
    r"|\b(?:and|plus)\s+\d[\d,]*\s+(?:more|other|additional|further|remaining)\b[^|\n.;)]{0,60}"
    r"|\(\s*(?:\+\s*)?\d[\d,]*\s+(?:more|others?)\b[^)\n]{0,60}\)"
    r"|\b\d[\d,]*\s+(?:more|other|additional|further|remaining)\s+(?:[A-Za-z/-]+\s+){0,2}" + _NOUNS
    + r"\b[^|\n.;)]{0,40}"
    r"|\b(?:the\s+)?(?:rest|remaining\s+(?:ones|items|entries))\s+(?:are\s+)?(?:omitted|not\s+(?:listed|shown))"
    r"\b[^|\n.;)]{0,40}"
    r"|\b(?:and\s+so\s+on|etc\.?)(?=\s*(?:\||\)|\]|$))"
    r"|^\s*[-*]?\s*(?:\.{3}|…)\s*$"                                            # a line that is only "..."
    r"|^\s*\|(?:\s*(?:\.{3}|…)\s*\|)+\s*$",                                      # a table row of "…" cells
    re.I | re.M)


_BEHAVIOUR_VERBS = {"load", "loads", "loading", "fetch", "fetches", "fetching", "show", "shows", "showing",
                    "display", "displays", "add", "adds", "adding", "return", "returns", "retry", "retries", "allow",
                    "allows", "accept", "accepts", "request", "requests", "append", "appends", "read", "reads",
                    "take", "takes", "wait", "waits", "need", "needs", "require", "requires", "get", "gets",
                    "creates", "create", "send", "sends", "generate", "generates"}


def replace_elisions(markdown: str, pointer: str) -> tuple[str, list[str]]:
    """An agent's abbreviated list ("[...27 more web pages]", "…and 84 more REST endpoints",
    "etc.") replaced by `pointer` — where the complete list is — with what was replaced."""
    found: list[str] = []

    def sub(m: re.Match) -> str:
        before = re.findall(r"[A-Za-z]+", m.string[max(0, m.start() - 30):m.start()])
        if before and before[-1].lower() in _BEHAVIOUR_VERBS:
            return m.group(0)                     # "loads 10 more rows": what the system does, not a cut list
        found.append(m.group(0).strip())
        return pointer
    out = ELISION.sub(sub, markdown or "")
    return out, found


def _without_ids(text: str) -> str:
    """The statement without ids and list numbering ("1.", "2)"), which are not values."""
    from .evidence_pack import BR_ID, EV_ID
    text = re.sub(r"(?m)^\s*(?:\d+[.)]|[-*+])\s+", "", text)
    return BR_ID.sub("", EV_ID.sub("", text))


# ── audit report ────────────────────────────────────────────────────────────

def report_markdown(withheld: list[tuple[str, str]], ledger: dict | None,
                    removed: list[tuple[str, str]], spec_removed: list[tuple[str, str]] | None = None,
                    elisions: list[str] | None = None) -> str:
    """The audit file's Grounding Checks: everything kept out of the business
    documents because it could not be traced to the repository, with the reason."""
    rules = (ledger or {}).get("rules") or []
    unverified = [r for r in rules if not r.get("verified", True)]
    dropped = [(r["id"], d) for r in rules if r.get("verified", True) for d in r.get("dropped", [])]
    lines = ["## Grounding Checks", "",
             "_Computed by the pipeline. Every evidence item, business rule, scenario and BRD statement was checked "
             "against the repository's code; what could not be traced to it was kept out of the business documents "
             "and is listed here._", "",
             f"- **Evidence items withheld from the writers:** {len(withheld):,}",
             f"- **Business rules left out of the BRD:** {len(unverified):,}",
             f"- **Scenario entries dropped from rules in the BRD:** {len(dropped):,}",
             f"- **BRD statements removed:** {len(removed):,}"]
    if spec_removed is not None:
        lines.append(f"- **Technical Specification statements removed (UI Interaction Contracts):** "
                     f"{len(spec_removed):,}")
    if elisions is not None:
        lines.append(f"- **Abbreviated lists replaced in the technical documents:** {len(elisions):,}")
    if withheld:
        lines += ["", "### Evidence items withheld", "", "| Evidence | Reason |", "|---|---|"]
        lines += [f"| `{i}` | {_cell(reason)} |" for i, reason in withheld]
    if unverified:
        lines += ["", "### Business rules left out of the BRD", "", "| Rule | Source | Reason |", "|---|---|---|"]
        for r in unverified:
            src = "; ".join(f"`{s['path']}:{s['start']}-{s['end']}`" for s in r["sources"][:2])
            lines.append(f"| {_cell(r.get('statement_original') or r['statement'])} | {src} | "
                         f"{_cell('; '.join(r.get('unverified_reasons', [])))} |")
    if dropped:
        lines += ["", "### Scenario entries dropped", "", "| Rule | Kind | Entry | Reason |", "|---|---|---|---|"]
        for rid, d in dropped:
            lines.append(f"| {rid} | {d['kind'].replace('_', ' ')} | {_cell(d['text'])} | {_cell('; '.join(d['reasons']))} |")
    if removed:
        lines += ["", "### BRD statements removed", "", "| Statement | Reason |", "|---|---|"]
        lines += [f"| {_cell(s)} | {_cell(reason)} |" for s, reason in removed]
    if elisions:
        lines += ["", "### Abbreviated lists replaced in the technical documents", "",
                  "_An agent shortened a list instead of giving every item; each was replaced with a pointer to the "
                  "complete computed list._", ""]
        lines += [f"- “{_cell(e)}”" for e in elisions]
    if spec_removed:
        lines += ["", "### Technical Specification statements removed (UI Interaction Contracts)", "",
                  "| Statement | Reason |", "|---|---|"]
        lines += [f"| {_cell(s)} | {_cell(reason)} |" for s, reason in spec_removed]
    return "\n".join(lines)


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")
