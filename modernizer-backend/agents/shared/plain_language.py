"""
Keeps the BRD in business language: the deterministic backstop to the Product
Owner skill's "no code" instruction, as current_state.py is to its "no
migration" one. No model involved; the same text always gives the same result.

What it does to a BRD (Markdown):

- **Evidence citations** (`EV-java-0012`) are taken out and returned with the
  statement that carried them, for the evidence file's traceability section.
  Business-rule ids (`BR-0042`) stay: they point at the BRD's own catalog.
- **Code blocks** are removed.
- **Inline code** (`` `…` ``): file paths and locations (`Order.java:12`,
  `src/main/…`), expressions and calls (`a > 5`, `save()`, `${…}`, markup) and
  qualified names (`com.acme.Order`) are removed; a plain name is turned into
  words — `OrderService` → "Order Service", `PENDING_APPROVAL` → "Pending Approval".
- **Bare code references** outside backticks — file names with a source
  extension, `Class.method()` calls, `@Annotations` — are removed.
- What is left is tidied: empty brackets, dangling "in"/"at", doubled
  punctuation; a list item, table row or paragraph left with no words goes.
"""
import re

from .evidence_pack import EV_ID, REMOVED

_FENCE = re.compile(r"^\s*(```|~~~)")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_SOURCE_EXT = (r"java|jsp|jspx|jspf|js|jsx|ts|tsx|mjs|py|sql|pls|pkb|pks|xml|properties|ya?ml|html?|kt|kts|"
               r"groovy|scala|cs|go|rb|php|vue|json|gradle|drl|xsd|wsdl|sh|bat|cfg|conf|ini|tag|ftl|vm")
_FILE = re.compile(rf"(?<![\w/])(?:[\w.-]+/)*[\w.-]+\.(?:{_SOURCE_EXT})(?::\d+(?:-\d+)?)?(?![\w/])", re.I)
_PRODUCT = re.compile(r"^[A-Z][A-Za-z0-9]*\.js$")      # Backbone.js, Node.js, Vue.js, D3.js
_PATH = re.compile(r"(?<![\w/])(?:[\w.-]+/){2,}[\w.-]*")
_CALL = re.compile(r"(?<![\w.])[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*\([^()\n]{0,40}\)")
_QUALIFIED = re.compile(r"(?<![\w.])[a-z][\w$]*(?:\.[a-z][\w$]*){2,}(?:\.[A-Z][\w$]*)?(?![\w(])")
_ANNOTATION = re.compile(r"(?<![\w@])@[A-Z][\w]*(?:\([^()\n]*\))?")
_IDENTIFIER = re.compile(r"^[A-Za-z_][\w]*$")
_EV_GROUP = re.compile(r"\[\s*(?:EV-[\w-]+\s*,?\s*)+\]")


def humanize(identifier: str) -> str:
    """`OrderService` → "Order Service", `orderTotal` → "order total", `PENDING_APPROVAL` → "Pending Approval"."""
    identifier = re.sub(r"^ROLE_", "", identifier)
    if identifier.isupper() or "_" in identifier:
        words = [w for w in identifier.split("_") if w]
        return " ".join(w.capitalize() if w.isupper() else w for w in words)
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", identifier).split()
    if identifier[:1].islower():                       # a variable: orderTotal → order total
        words = [w if w.isupper() and len(w) > 1 else w.lower() for w in words]
    return " ".join(words)


_M = "\x02"                 # where a code reference was taken out


def _span(match: re.Match) -> str:
    text = match.group(1).strip()
    if EV_ID.fullmatch(text):
        return text                                   # an evidence id in backticks: taken out with the others
    if _IDENTIFIER.match(text):
        return humanize(text)
    return _M                                          # a path, location, expression, call or markup


def _file(match: re.Match) -> str:
    """A file reference is taken out; a product named like one ("Backbone.js", "Node.js") stays."""
    return match.group(0) if _PRODUCT.match(match.group(0)) else _M


def _mark(line: str) -> tuple[str, list[str]]:
    """The line with every code reference replaced by a marker and evidence ids removed; the ids."""
    cited = EV_ID.findall(line)
    line = _CODE_SPAN.sub(_span, line)
    line = _EV_GROUP.sub("", line)
    line = EV_ID.sub("", line)
    line = _FILE.sub(_file, line)
    for pattern in (_PATH, _CALL, _QUALIFIED, _ANNOTATION):
        line = pattern.sub(_M, line)
    return line, cited


_PREFIX = re.compile(r"^(\s*(?:[-*+]|\d+[.)]|#{1,6}|>)\s+)")
_PREP = r"(?:in|at|from|via|inside|within|by|of|see|using|through|under|on|into|for)"


def _settle(text: str, cell: bool = False) -> str:
    """Take the markers out. A reference that ends a phrase ("… approval in `X.approve()`.")
    or sits in brackets goes with its connecting word; a sentence with a reference in
    the middle cannot be read without it, so the sentence goes (a table cell keeps its words)."""
    if _M not in text:
        return text
    text = re.sub(r"\(\s*[,;:\s]*\)|\[\s*[,;:\s]*\]", "", text)      # brackets a removed citation emptied
    text = re.sub(rf"{_M}(?:\s*(?:,|and|or|&|/)\s*{_M})+", _M, text)
    text = re.sub(rf"\(\s*{_M}\s*\)", "", text)
    text = re.sub(rf"\s*\b{_PREP}\s+(?:the\s+)?{_M}(?=\s*(?:[.,;:)!?]|$))", "", text, flags=re.I)
    text = re.sub(rf"\s*[–—:-]\s*{_M}(?=\s*(?:[.;:!?]|[–—]|$))", "", text)
    if _M not in text:
        return text
    if cell:
        return text.replace(_M, "")
    prefix = _PREFIX.match(text)
    head, body = (prefix.group(1), text[prefix.end():]) if prefix else ("", text)
    sentences = re.split(r"(?<=[.!?])\s+", body)
    return head + " ".join(s for s in sentences if _M not in s)


def _tidy(text: str) -> str:
    text = re.sub(r"(?:\s*,\s*){2,}", ", ", text)
    text = re.sub(r"\(\s*[,;:/–—-]*\s*\)|\[\s*[,;:/–—-]*\s*\]", "", text)
    text = re.sub(r"\(\s*[,;]\s*", "(", text)
    text = re.sub(r"\s*[,;]\s*\)", ")", text)
    text = re.sub(r"\s+([,.;:)])", r"\1", text)
    text = re.sub(r"([,;:])\s*(?=[,.;:])", "", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+[–—-]\s*(?=[.,;:]|$)", "", text)
    text = re.sub(r"^(\s*(?:[-*+]|\d+[.)])\s+)[–—:,;\s]+", r"\1", text)
    return text.rstrip()


def _clean_line(line: str) -> tuple[str, list[str], int]:
    """A line without code references; the evidence ids it cited; how many references it lost."""
    marked, cited = _mark(line)
    lost = marked.count(_M)
    if marked.lstrip().startswith("|"):
        settled = "|".join(_settle(cell, cell=True) for cell in marked.split("|"))
    else:
        settled = _settle(marked)
    return _tidy(settled), cited, lost


def _words(line: str) -> int:
    body = re.sub(r"^\s*(?:[-*+]|\d+[.)]|#{1,6}|>|\|)\s*", "", line)
    body = re.sub(r"\bBR-\d{4,}\b", "", body)
    return len(re.findall(r"[A-Za-z]{2,}", body))


def _keeps_meaning(line: str, lost: int) -> bool:
    """A line that lost code keeps its place only with words left to read
    ("Orders above 100 units need approval."), not leftovers ("— decision:")."""
    return _words(line) >= (3 if lost else 1)


EMPTIED = "_Every statement the writer made here was in technical terms; they are recorded in the evidence file._"


def business_only(markdown: str) -> tuple[str, list[tuple[str, list[str]]], int]:
    """(BRD without code references, [(statement, evidence ids it cited)], code references removed).
    A statement that could not be kept is listed with its original wording; a section
    left with nothing but removed statements says so instead of standing empty."""
    out, cited, removed = [], [], 0
    in_fence = False
    section_lost = False                     # the current section lost a whole statement
    section_start = 0                        # index in `out` just after the current heading
    def close_section():
        if section_lost and not any(l.strip() for l in out[section_start:]):
            out[section_start:] = ["", EMPTIED, ""]
    for raw in _COMMENT.sub("", markdown or "").split("\n"):
        if _FENCE.match(raw):
            in_fence = not in_fence
            removed += 1 if in_fence else 0
            section_lost = True
            continue
        if in_fence:
            continue
        if not raw.strip():
            out.append(raw)
            continue
        if re.match(r"^\s*\|?\s*:?-{2,}", raw):        # a table's separator row
            out.append(raw)
            continue
        line, ids, lost = _clean_line(raw)
        removed += lost
        heading = line.lstrip().startswith("#")
        keep = line.strip().startswith("|") or (heading and _words(line) >= 1) or _keeps_meaning(line, lost)
        if heading and keep:
            close_section()
            out.append(line)
            section_start, section_lost = len(out), False
            continue
        if ids:
            statement = (re.sub(r"^\s*(?:[-*+]|\d+[.)]|#{1,6})\s*", "", line).strip(" |") if keep
                         else REMOVED + re.sub(r"^\s*(?:[-*+]|\d+[.)])\s*", "", raw).strip())
            cited.append((statement, sorted(set(ids))))
        if keep:
            out.append(line)
        else:
            section_lost = True
    close_section()
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"
    return text, cited, removed


def is_plain(text: str) -> bool:
    """True when `text` carries no code reference this module would remove."""
    if _CODE_SPAN.search(text) or EV_ID.search(text):
        return False
    files = [m.group(0) for m in _FILE.finditer(text) if not _PRODUCT.match(m.group(0))]
    return not files and not any(p.search(text) for p in (_PATH, _CALL, _QUALIFIED, _ANNOTATION))


def phrase(text: str) -> str:
    """One field (a rule statement, a condition) in business words; "" if nothing meaningful is left."""
    line, _, lost = _clean_line(text or "")
    return line.strip(" ,;:—–-") if _keeps_meaning(line, lost) else ""
