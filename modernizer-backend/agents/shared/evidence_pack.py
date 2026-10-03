"""
Evidence packs: what the evidence specialists found, in one format, with stable
ids — the single fact base both document writers work from.

Stack discovery separates reading from writing. Evidence specialists (the
per-stack discovery agent, wildfly-re, the unit runs of a large stack) read the
code and write evidence packs; they write no documents. Two writers then work
only from those packs: the Product Owner agent writes the BRD, the Enterprise
Architect agent the Technical Specification and Test Inventory. Because both
cite the same ids, the two documents point at the same facts, and a check here
can say which citations are real.

Pack format (the skills ask for exactly this):

    ### Components
    - `path/to/File.java` — what it is … (one bullet per item)
    ### Entry Points & Interfaces
    ### Data
    ### Business Behaviour
    ### Actors & Roles
    ### Integrations & Configuration
    ### Tests
    ### Limitations

Ids are assigned here, never by the model: every top-level bullet under a known
section gets `[EV-<stack>-<nnnn>]`, numbered in order, so the same pack always
gets the same ids.
"""
import re

SECTIONS = ("Components", "Entry Points & Interfaces", "Data", "Business Behaviour", "Actors & Roles",
            "Integrations & Configuration", "Tests", "Limitations")

#: What each writer is given. Both see interfaces and data — they describe the
#: same system from two sides — and both see the limitations.
PO_SECTIONS = ("Actors & Roles", "Business Behaviour", "Entry Points & Interfaces", "Data", "Limitations")
EA_SECTIONS = ("Components", "Entry Points & Interfaces", "Data", "Integrations & Configuration", "Tests",
               "Limitations")

_ALIASES = {
    "components": "Components",
    "entry points & interfaces": "Entry Points & Interfaces", "entry points and interfaces": "Entry Points & Interfaces",
    "entry points": "Entry Points & Interfaces", "interfaces": "Entry Points & Interfaces",
    "data": "Data", "data model": "Data",
    "business behaviour": "Business Behaviour", "business behavior": "Business Behaviour",
    "actors & roles": "Actors & Roles", "actors and roles": "Actors & Roles", "actors": "Actors & Roles",
    "integrations & configuration": "Integrations & Configuration",
    "integrations and configuration": "Integrations & Configuration", "integrations": "Integrations & Configuration",
    "configuration": "Integrations & Configuration",
    "tests": "Tests", "limitations": "Limitations", "unit limitations": "Limitations",
    "discovery limitations": "Limitations",
}
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_BULLET = re.compile(r"^[-*+]\s+(?:\[EV-[^\]]*\]\s*)?")
EV_ID = re.compile(r"\bEV-[a-z0-9]+(?:-[a-z0-9]+)*-\d{4}\b")
BR_ID = re.compile(r"\bBR-\d{4,}\b")
_NONE = re.compile(r"^\s*[-*+]?\s*(?:none|n/a|nothing)\b.*$", re.I)


def canonical(heading: str) -> str | None:
    name = re.sub(r"[`*_]", "", heading).strip().lower().rstrip(":")
    return _ALIASES.get(name)


def slug(stack_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", stack_id.lower()).strip("-") or "stack"


def assign_ids(text: str, stack_id: str) -> str:
    """Prefix every top-level bullet under a known section with its evidence id
    (any id the model wrote is replaced). Lines outside known sections are kept
    as they are."""
    prefix = f"EV-{slug(stack_id)}-"
    out: list[str] = []
    section: str | None = None
    n = 0
    for line in (text or "").splitlines():
        heading = _HEADING.match(line)
        if heading:
            section = canonical(heading.group(2))
            out.append(line)
            continue
        if section and _BULLET.match(line) and not _NONE.match(line):
            n += 1
            out.append(f"- [{prefix}{n:04d}] " + _BULLET.sub("", line, count=1))
            continue
        out.append(line)
    return "\n".join(out)


def parse(text: str) -> dict[str, list[str]]:
    """{section: [item text (with its continuation lines)]} for the known sections."""
    items: dict[str, list[str]] = {s: [] for s in SECTIONS}
    section: str | None = None
    for line in (text or "").splitlines():
        heading = _HEADING.match(line)
        if heading:
            section = canonical(heading.group(2))
            continue
        if section is None or not line.strip() or _NONE.match(line):
            continue
        if _BULLET.match(line):
            items[section].append(line.rstrip())
        elif items[section]:
            items[section][-1] += "\n" + line.rstrip()
        else:
            items[section].append(line.rstrip())
    return items


def ids(text: str) -> set[str]:
    return {m.group(0) for line in (text or "").splitlines()
            if line.startswith("- [EV-") for m in [EV_ID.search(line)] if m}


def view(packs: list[tuple[str, str, str]], sections: tuple[str, ...]) -> list[str]:
    """One piece per stack — `(stack id, label, pack text)` — holding only the
    given sections, in that order."""
    pieces = []
    for stack_id, label, text in packs:
        parsed = parse(text)
        body = [f"### {s}\n" + "\n".join(parsed[s]) for s in sections if parsed[s]]
        if body:
            pieces.append(f"## {label} (`{stack_id}`)\n\n" + "\n\n".join(body))
    return pieces


def split_piece(text: str, limit: int) -> list[str]:
    """A piece longer than `limit` cut at item boundaries (never mid-item)."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    header = text.split("\n", 1)[0] if text.startswith("## ") else ""
    for block in re.split(r"\n(?=- \[EV-|### )", text):
        if current and len(current) + len(block) + 1 > limit:
            parts.append(current)
            current = (header + " (continued)\n" if header else "") + block
        else:
            current = f"{current}\n{block}" if current else block
    if current:
        parts.append(current)
    return parts


def rules_index(ledger: dict | None, max_chars: int) -> str:
    """The business-rules catalog in brief for the Product Owner: counts by area
    and the rules themselves by id, cut at `max_chars` (and saying so)."""
    rules = (ledger or {}).get("rules") or []
    if not rules:
        return "No business-rules catalog was produced for this run."
    by_area: dict[str, list[dict]] = {}
    for r in rules:
        by_area.setdefault(r.get("area", ""), []).append(r)
    lines = [f"{len(rules)} rules in {len(by_area)} areas. Reference them by id (BR-nnnn); the full catalog "
             "is appended to the BRD, so do not re-list it."]
    shown = 0
    for area, items in by_area.items():
        lines.append(f"\n### {area or '(no area)'} — {len(items)} rules")
        for r in items:
            line = f"- {r['id']} ({r.get('type', 'other')}, {r.get('basis', 'explicit')}): {r.get('statement', '')}"
            if sum(len(x) + 1 for x in lines) + len(line) > max_chars:
                lines.append(f"\n… {len(rules) - shown} more rules not listed here (they are in the catalog).")
                return "\n".join(lines)
            lines.append(line)
            shown += 1
    return "\n".join(lines)


def check(document: str, evidence_ids: set[str], rule_ids: set[str]) -> dict:
    cited_ev = set(EV_ID.findall(document or ""))
    cited_br = set(BR_ID.findall(document or ""))
    return {"evidence": cited_ev, "rules": cited_br,
            "unknown_evidence": sorted(cited_ev - evidence_ids), "unknown_rules": sorted(cited_br - rule_ids)}


def check_markdown(brd: dict, spec: dict, evidence_ids: set[str]) -> str:
    """The Evidence Check section: what each document cites, and any citation
    that points at nothing."""
    cited = brd["evidence"] | spec["evidence"]
    lines = ["## Evidence Check", "",
             "_Computed by the pipeline, not written by an agent. The BRD (Product Owner agent) and the "
             "Technical Specification (Enterprise Architect agent) were written from the same evidence packs; "
             "every id below was checked against them._", "",
             f"- **Evidence items gathered:** {len(evidence_ids):,}",
             f"- **Cited by the BRD:** {len(brd['evidence'] & evidence_ids):,} evidence items, "
             f"{len(brd['rules']):,} business rules",
             f"- **Cited by the Technical Specification / Test Inventory:** {len(spec['evidence'] & evidence_ids):,} "
             "evidence items",
             f"- **Cited by neither:** {len(evidence_ids - cited):,}"]
    unknown = [(name, i) for name, c in (("BRD", brd), ("Technical Specification", spec))
               for i in c["unknown_evidence"] + c["unknown_rules"]]
    if unknown:
        lines += ["", f"**Citations that match no evidence item or rule ({len(unknown)}) — treat the statements "
                  "carrying them as unverified:**"]
        lines += [f"- {name}: `{i}`" for name, i in unknown[:50]]
        if len(unknown) > 50:
            lines.append(f"- …and {len(unknown) - 50} more")
    else:
        lines += ["", "Every evidence and rule id cited by either document exists."]
    return "\n".join(lines)


def split_spec(text: str) -> tuple[str, str]:
    """The Enterprise Architect's answer -> (technical specification, test inventory)."""
    text = re.sub(r"<!--\s*SECTION:\s*END\s*-->.*\Z", "", text or "", flags=re.S)
    text = re.sub(r"<!--\s*SECTION:\s*TECHNICAL_SPECIFICATION\s*-->", "", text)
    parts = re.split(r"<!--\s*SECTION:\s*TEST_INVENTORY\s*-->", text, maxsplit=1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")
