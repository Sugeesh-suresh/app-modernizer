"""
The business-rules ledger: every rule candidate (rule_candidates.py) ends up
classified — as one or more business rules, as technical with a reason, or as
unclassified with the reason it could not be — so coverage is counted, not
assumed.

The model never chooses what to read. Each batch hands the extraction agent the
exact source of its candidates, and its answer is checked here in code:

- an answer about a candidate that was not in the batch is ignored;
- a candidate the answer leaves out is retried once, then marked unclassified;
- a rule's cited lines must lie inside its candidate; otherwise they are
  clamped to the candidate and the rule is flagged;
- every `identifier` a rule names in backticks must appear in its candidate's
  source; otherwise the rule is flagged (kept, so a reviewer can judge it);
- the same rule found in several places is merged into one rule with several
  sources;
- tests are attached by name: test files that mention the rule's class or file;
- every statement must be plain English (no code): a candidate whose rules name
  code is asked once more to restate them (`needs_rewording` / `render_batch`
  with `reword`); a statement still technical after that is reworded here from
  the rule's own condition and outcome, or, failing that, stated generically and
  marked inferred / low confidence for the business to confirm;
- every rule and every scenario must be traceable to the candidate's code
  (grounding.py): values and quoted messages present, key terms related, each
  scenario backed by the kind of check it describes. What is not is sent back
  once with the reasons; then an untraceable rule is left out of the BRD
  (`verified` False, an `UV-` id, listed in the audit file) and an untraceable
  scenario entry is dropped (kept in `dropped` for the audit file);
- ids carry the rule's business capability: `BR-<CAPABILITY>-<nnn>`;
- every decision point of a candidate (rule_candidates: each condition, branch,
  comparison, access rule, validation annotation, rendering decision, session or
  model write) must be accounted for — named by a rule's `decision_points`, or
  dismissed in `technical_decisions` with a reason. A candidate answered with
  points left over is asked once more for exactly those (`unaccounted`); what is
  still unaccounted is reported point by point (`decision_report`), never dropped.
"""
import csv
import io
import json
import re
from collections import defaultdict
from pathlib import Path

from . import grounding
from .rule_candidates import Candidate

RULE_TYPES = ("validation", "calculation", "eligibility", "state-transition", "authorization", "constraint",
              "default", "workflow", "notification", "data-integrity", "other")


# ---------------------------------------------------------------------------
# Batching and the extraction request
# ---------------------------------------------------------------------------

def batches(candidates: list[Candidate], max_candidates: int, max_chars: int) -> list[list[Candidate]]:
    """Consecutive candidates (already in area/path order) packed into batches."""
    out: list[list[Candidate]] = []
    size = 0
    for c in candidates:
        cost = len(c.source) + 300
        if out and len(out[-1]) < max_candidates and size + cost <= max_chars:
            out[-1].append(c)
            size += cost
        else:
            out.append([c])
            size = cost
    return out


def render_batch(batch: list[Candidate], reword: dict[str, list[str]] | None = None,
                 account: dict[str, list[str]] | None = None) -> str:
    """The candidates as the extraction agent sees them. `reword`: {candidate id:
    what was wrong with its earlier answer} — the candidate is asked again, with that.
    `account`: {candidate id: decision points its earlier answer left out} — asked for those."""
    parts = []
    for c in batch:
        points = c.decisions
        if account and account.get(c.id):
            points = [d for d in c.decisions if d["id"] in account[c.id]]
        note = ""
        if reword and reword.get(c.id):
            note = ("\n**Restate from this code, in plain English.** Parts of your earlier answer for this candidate "
                    "contained code, or could not be traced to the code below. Give every rule again — statement, "
                    "use cases, negative scenarios and edge cases — using only what this code shows (its values, "
                    "messages and checks), as sentences with no code, names, expressions or backticks. Leave out "
                    "any case the code does not contain:\n" + "\n".join(f"- {s}" for s in reword[c.id][:8]))
        if account and account.get(c.id):
            note += ("\n**Account for these decision points.** Your earlier answer for this candidate did not "
                     "account for the points below. For each, give the rule it implements (with the point in its "
                     "`decision_points`) or dismiss it in `technical_decisions` with the reason. Do not repeat "
                     "rules you already gave.")
        parts.append(
            f"### {c.id} — {c.kind} `{c.symbol}`\n"
            f"File: `{c.path}` lines {c.start}-{c.end} ({c.language}; signals: {', '.join(c.signals) or '—'})"
            + ("\n**Truncated:** only the first part of this code is shown." if c.truncated else "")
            + note
            + "\nDecision points:\n" + "\n".join(f"- {d['id']} line {d['line']} [{d['kind']}] {d['text']}"
                                                  for d in points)
            + f"\n```\n{c.source}\n```"
        )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Parsing and checking the answer
# ---------------------------------------------------------------------------

def parse_answer(raw: str) -> list[dict]:
    text = (raw or "").strip()
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    for candidate in [*reversed(blocks), text, text[text.find("{"): text.rfind("}") + 1]]:
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            data = data.get("results", [])
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
    return []


def _lines(spec, c: Candidate) -> tuple[int, int, bool]:
    m = re.match(r"\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*$", str(spec or ""))
    if not m:
        return c.start, c.end, True
    a, b = int(m.group(1)), int(m.group(2) or m.group(1))
    if a > b:
        a, b = b, a
    inside = c.start <= a and b <= c.end
    return (a, b, False) if inside else (max(c.start, min(a, c.end)), min(c.end, max(b, c.start)), True)


_IDENT = re.compile(r"`([^`\s]{2,80})`")


def apply_answer(batch: list[Candidate], results: list[dict], ledger: dict, replace: bool = False,
                 repo_text: str = "") -> list[Candidate]:
    """Record the answer for this batch in `ledger`; return the candidates it left out.
    `replace`: the answer restates candidates already answered — their earlier rules go.
    `repo_text`: the repository's message texts, which a rule may quote."""
    by_id = {c.id: c for c in batch}
    earlier: dict[str, list] = defaultdict(list)    # restated candidates: their rules' decision points
    if replace:
        restated = {str(r.get("candidate") or r.get("id") or "").strip() for r in results} & set(by_id)
        restated = {cid for cid in restated if any(isinstance(x, dict) and str(x.get("statement") or "").strip()
                                                   for r in results if str(r.get("candidate") or r.get("id") or "").strip() == cid
                                                   for x in (r.get("rules") or []))}
        for r in ledger["raw_rules"]:
            if r["sources"][0]["candidate"] in restated:
                earlier[r["sources"][0]["candidate"]].append(r.get("decision_points", []))
        ledger["raw_rules"] = [r for r in ledger["raw_rules"] if r["sources"][0]["candidate"] not in restated]
        for cid in restated:
            ledger["candidates"][cid]["rule_count"] = 0
    answered: set[str] = set()
    for result in results:
        cid = str(result.get("candidate") or result.get("id") or "").strip()
        c = by_id.get(cid)
        if c is None or cid in answered:
            continue
        rules = result.get("rules") if isinstance(result.get("rules"), list) else []
        rules = [r for r in rules if isinstance(r, dict) and str(r.get("statement") or "").strip()]
        technical = str(result.get("technical") or "").strip()
        own = {d["id"] for d in c.decisions}
        dismissed = {}
        for item in result.get("technical_decisions") or []:
            if isinstance(item, dict) and str(item.get("id") or "").strip() in own:
                dismissed[str(item["id"]).strip()] = str(item.get("reason") or "technical").strip()[:300]
            elif isinstance(item, str) and item.strip() in own:
                dismissed[item.strip()] = technical[:300] or "technical"
        if not rules and not dismissed and (not technical or replace):
            continue                         # a restatement without rules leaves the earlier answer standing
        answered.add(cid)
        entry = ledger["candidates"][cid]
        entry.setdefault("dismissed", {}).update(dismissed)
        if not rules:
            if technical and not replace:
                entry.update(status="technical" if entry["status"] != "rule" else "rule", reason=technical[:300])
                for d in own - set(entry["dismissed"]):
                    entry["dismissed"][d] = technical[:300]
            continue
        entry["status"] = "rule"
        carried = earlier.get(cid, []) if replace else []
        for k, r in enumerate(rules):
            if replace and not r.get("decision_points") and len(carried) == len(rules):
                r = {**r, "decision_points": carried[k]}     # restated in the same order: same decisions
            a, b, moved = _lines(r.get("lines"), c)
            flags = ["cited lines outside the candidate; clamped"] if moved else []
            named = {m for field in ("statement", "condition", "outcome") for m in _IDENT.findall(str(r.get(field) or ""))}
            source = c.source
            missing = sorted(i for i in named if i not in source)
            if missing:
                flags.append("not found in the cited code: " + ", ".join(f"`{m}`" for m in missing[:5]))
            rtype = str(r.get("type") or "other").strip().lower()
            ledger["raw_rules"].append({
                "statement": str(r["statement"]).strip()[:600],
                "capability": re.sub(r"\s+", " ", str(r.get("capability") or "")).strip()[:60],
                "use_cases": _scenario_list(r.get("use_cases", r.get("use_case"))),
                "negative_scenarios": _scenario_list(r.get("negative_scenarios", r.get("negative_scenario"))),
                "edge_cases": _scenario_list(r.get("edge_cases", r.get("edge_case"))),
                "type": rtype if rtype in RULE_TYPES else "other",
                "condition": str(r.get("condition") or "").strip()[:400],
                "outcome": str(r.get("outcome") or "").strip()[:400],
                "basis": "inferred" if str(r.get("basis") or "").lower().startswith("infer") else "explicit",
                "confidence": str(r.get("confidence") or "").lower() if str(r.get("confidence") or "").lower()
                in ("high", "medium", "low") else "medium",
                "area": c.area,
                "sources": [{"candidate": cid, "path": c.path, "start": a, "end": b, "symbol": c.symbol}],
                "flags": flags,
                "decision_points": [d for d in dict.fromkeys(str(x).strip() for x in (r.get("decision_points") or []))
                                    if d in own],
            })
            raw = ledger["raw_rules"][-1]
            raw["grounding"] = grounding.check_rule(raw, c.source, repo_text)
            code = grounding.strip_line_numbers(c.source)
            raw["grounding"]["condition"] = grounding.unsupported_values(raw["condition"], code, repo_text)
            raw["grounding"]["outcome"] = grounding.unsupported_values(raw["outcome"], code, repo_text)
            entry.setdefault("rule_count", 0)
            entry["rule_count"] += 1
    return [c for c in batch if c.id not in answered]


MAX_SCENARIOS = 8          # per kind, per rule


def _scenario_list(value) -> list[str]:
    """Scenarios as a list, whether the agent gave a list or one text ("a; b")."""
    items = value if isinstance(value, list) else re.split(r"\s*;\s*|\n+", str(value or ""))
    out = []
    for i in items:
        text = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", str(i)).strip()[:400]
        if text and text not in out:
            out.append(text)
    return out[:MAX_SCENARIOS]


#: The scenario lists every rule carries besides its statement, each holding as many as the code shows.
SCENARIO_FIELDS = ("use_cases", "negative_scenarios", "edge_cases")


def _texts(rule: dict) -> list[str]:
    """The rule's statement and its scenario texts, as written."""
    return [rule["statement"], *(s for key in SCENARIO_FIELDS for s in rule.get(key, []))]


def is_business_language(statement: str) -> bool:
    """A statement the BRD can carry as written: no code, and a sentence's worth of words."""
    from .plain_language import is_plain
    return is_plain(statement) and len(re.findall(r"[A-Za-z]{2,}", statement)) >= 4


def needs_rewording(batch: list[Candidate], ledger: dict) -> dict[str, list[str]]:
    """{candidate id: what is wrong with its rules} for this batch: texts that are
    not plain English, and statements or scenarios that cannot be traced to its code."""
    ids = {c.id for c in batch}
    out: dict[str, list[str]] = defaultdict(list)
    from .plain_language import is_plain
    for r in ledger["raw_rules"]:
        cid = r["sources"][0]["candidate"]
        if cid not in ids:
            continue
        if not is_business_language(r["statement"]):
            out[cid].append(f"not plain English: “{r['statement']}”")
        out[cid] += [f"not plain English: “{s}”" for s in _texts(r)[1:] if s and not is_plain(s)]
        if r.get("grounding"):
            out[cid] += [f"not in the code — {line}" for line in grounding.describe(r["grounding"], r)]
    return {k: v for k, v in out.items() if v}


def new_ledger(candidates: list[Candidate]) -> dict:
    ledger = {
        "candidates": {c.id: {**c.to_dict(), "status": c.status if c.status != "pending" else "pending",
                              "reason": c.reason, "dismissed": {}} for c in candidates},
        "raw_rules": [],
        "rules": [],
    }
    for c in candidates:
        if c.status == "auto-technical":            # dismissed by the parser, with its reason
            ledger["candidates"][c.id]["dismissed"] = {d["id"]: f"auto: {c.reason}" for d in c.decisions}
    return ledger


def unaccounted(batch: list[Candidate], ledger: dict) -> dict[str, list[str]]:
    """{candidate id: its decision points no rule names and no dismissal covers}, for the
    answered candidates of this batch."""
    ids = {c.id for c in batch}
    named: dict[str, set] = defaultdict(set)
    for r in ledger["raw_rules"]:
        cid = r["sources"][0]["candidate"]
        if cid in ids:
            named[cid].update(r.get("decision_points", []))
    out = {}
    for c in batch:
        entry = ledger["candidates"][c.id]
        if entry["status"] in ("pending", "unclassified"):
            continue
        left = [d["id"] for d in c.decisions if d["id"] not in named[c.id] and d["id"] not in entry.get("dismissed", {})]
        if left:
            out[c.id] = left
    return out


def decision_report(ledger: dict) -> list[dict]:
    """Every decision point and how it was accounted for: `rule` (verified rule ids),
    `unverified rule`, `technical` (the agent's reason), `auto-technical` (the parser's),
    or `unaccounted` (with why) — computed after `finalize`."""
    by_point: dict[str, list[dict]] = defaultdict(list)
    for rule in ledger.get("rules", []):
        for d in rule.get("decision_points", []):
            by_point[d].append(rule)
    rows = []
    for cid, entry in ledger["candidates"].items():
        for d in entry.get("decisions", []):
            rules = by_point.get(d["id"], [])
            verified = [r["id"] for r in rules if r.get("verified", True)]
            reason = entry.get("dismissed", {}).get(d["id"], "")
            if verified:
                status, why = "rule", ""
            elif rules:
                status, why = "unverified rule", "; ".join(r["id"] for r in rules)
            elif reason:
                status, why = ("auto-technical" if reason.startswith("auto: ") else "technical"), \
                    reason.removeprefix("auto: ")
            elif entry["status"] == "unclassified":
                status, why = "unaccounted", f"candidate unclassified: {entry.get('reason', '')}"
            else:
                status, why = "unaccounted", "no rule names it and it was not dismissed (asked twice)"
            rows.append({"id": d["id"], "candidate": cid, "path": entry["path"], "line": d["line"],
                         "kind": d["kind"], "text": d["text"], "status": status,
                         "rules": [r["id"] for r in rules], "reason": why, "area": entry.get("area", "")})
    return rows


def mark_unclassified(candidates: list[Candidate], ledger: dict, reason: str) -> None:
    for c in candidates:
        entry = ledger["candidates"][c.id]
        if entry["status"] == "pending":
            entry.update(status="unclassified", reason=reason[:300])


# ---------------------------------------------------------------------------
# De-duplication, tests, ids
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower().replace("`", "")).split())


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`")
_QUALIFIER = re.compile(r"\b[A-Z][A-Z0-9_]{1,}\b")   # BCOM, MCOM, PDS_ADMIN, US …


def _facts(statement: str) -> tuple:
    """What two rules must share to be the same rule: every number, quoted or
    code value, and upper-case qualifier (brand, role, code). Wording may differ;
    these may not — "height above 20 inches" and "above 22 inches" are two rules."""
    return (tuple(sorted(_NUMBER.findall(statement))), tuple(sorted(q.lower() for q in _QUOTED.findall(statement))),
            tuple(sorted(set(_QUALIFIER.findall(statement)))))


def _similar(a: str, b: str) -> bool:
    sa, sb = set(a.split()), set(b.split())
    return bool(sa and sb) and len(sa & sb) / len(sa | sb) >= 0.9


def finalize(ledger: dict, workspace_dir: str, test_files: list[str]) -> None:
    """Merge duplicates, attach tests, assign BR ids. Idempotent on `raw_rules`."""
    raw_rules = [_grounded(r) for r in ledger["raw_rules"]]
    merged: list[dict] = []
    exact: dict[tuple, dict] = {}
    # Near-duplicates are only looked for among rules of the same type that share
    # their first words — linear overall, where comparing every pair would not be.
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for rule in raw_rules:
        norm = _norm(rule["statement"])
        key = (rule["type"], " ".join(norm.split()[:3]))
        target = exact.get((rule["type"], norm, _facts(rule["statement"]))) or next(
            (m for m in buckets[key][-50:]
             if m["_facts"] == _facts(rule["statement"]) and _similar(m["_norm"], norm)), None)
        if target is None:
            rule = {**rule, "sources": list(rule["sources"]), "flags": list(rule["flags"]), "_norm": norm,
                    "_facts": _facts(rule["statement"])}
            exact[(rule["type"], norm, rule["_facts"])] = rule
            buckets[key].append(rule)
            merged.append(rule)
        else:
            target["sources"] += [s for s in rule["sources"] if s not in target["sources"]]
            target["flags"] += [f for f in rule["flags"] if f not in target["flags"]]
            target["decision_points"] = list(dict.fromkeys(target.get("decision_points", [])
                                                           + rule.get("decision_points", [])))
            for key in SCENARIO_FIELDS:
                target[key] = (target.get(key, []) + [s for s in rule.get(key, [])
                                                      if s not in target.get(key, [])])[:MAX_SCENARIOS]
            target["dropped"] = target.get("dropped", []) + rule.get("dropped", [])
            if rule["verified"] and not target["verified"]:     # another place in the code supports it
                target.update(verified=True, unverified_reasons=[])
            if rule["basis"] == "explicit":
                target["basis"] = "explicit"
    index = _test_index(workspace_dir, test_files)
    for rule in merged:
        _business_wording(rule)
        name = capability_name(rule.get("capability", ""), rule["area"])
        rule["capability"], rule["_code"] = name, capability_code(name)
    merged.sort(key=lambda r: (r["_code"], r["area"], r["sources"][0]["path"], r["sources"][0]["start"]))
    numbers: dict[str, int] = defaultdict(int)
    unverified = 0
    for rule in merged:
        rule.pop("_norm", None)
        rule.pop("_facts", None)
        code = rule.pop("_code")
        if rule["verified"]:
            numbers[code] += 1
            rule["id"] = f"BR-{code}-{numbers[code]:03d}"
        else:                                   # not a business rule of the document: audit id only
            unverified += 1
            rule["id"] = f"UV-{unverified:04d}"
        names = set()
        for s in rule["sources"]:
            names.add(Path(s["path"]).stem)
            parts = s["symbol"].split(".")
            names.update(p for p in parts if p[:1].isupper())
        rule["tests"] = sorted({t for n in names for t in index.get(n, ())})[:5]
    by_candidate = defaultdict(list)
    for rule in merged:
        for s in rule["sources"]:
            by_candidate[s["candidate"]].append(rule["id"])
    for cid, entry in ledger["candidates"].items():
        entry["rule_ids"] = sorted(set(by_candidate.get(cid, [])))
    ledger["rules"] = merged


def _grounded(raw: dict) -> dict:
    """A copy of the raw rule with its untraceable scenario entries dropped (kept in
    `dropped` with the reasons) and `verified` saying whether its statement is traceable."""
    rule = {k: v for k, v in raw.items() if k != "grounding"}
    verdict = raw.get("grounding") or {}
    rule["dropped"] = []
    for key in SCENARIO_FIELDS:
        kept = []
        for entry, reasons in zip(raw.get(key, []), verdict.get(key, [[]] * len(raw.get(key, [])))):
            if reasons:
                rule["dropped"].append({"kind": key, "text": entry, "reasons": reasons})
            else:
                kept.append(entry)
        rule[key] = kept
    rule["verified"] = not verdict.get("statement")
    rule["unverified_reasons"] = list(verdict.get("statement", []))
    # The fallback wording may use the condition and outcome only when they are traceable too.
    for key in ("condition", "outcome"):
        if verdict.get(key):
            rule[key] = ""
    return rule


def verified_rules(ledger: dict | None) -> list[dict]:
    """The rules the business documents may state: those traceable to the code."""
    return [r for r in (ledger or {}).get("rules", []) if r.get("verified", True)]


def capability_name(capability: str, area: str) -> str:
    """The capability as the BRD heads it; from the area when the agent named none."""
    name = re.sub(r"[^\w &/-]+", " ", capability or "").strip()
    if not name:
        last = re.split(r"[./]", area or "")[-1] if area and not area.startswith("(") else ""
        from .plain_language import humanize
        name = humanize(last) if last else "General"
    name = " ".join(name.split())
    return name[:1].upper() + name[1:]


def capability_code(name: str) -> str:
    """`Product standardization` → PRODUCT-STANDARDIZATION (two words at most), for ids."""
    words = re.findall(r"[A-Za-z0-9]+", name.upper())[:2]
    return "-".join(words)[:24].strip("-") or "GENERAL"


_TYPE_WORDS = {"state-transition": "status change", "data-integrity": "data integrity",
               "authorization": "access", "other": "business"}


def _business_wording(rule: dict) -> None:
    """Guarantee a plain-English statement. The agent's own wording when it is plain;
    else its statement, or condition and outcome, with the code taken out; else a
    generic sentence marked inferred / low for the business owner to confirm.
    The agent's original wording is kept as `statement_original` for the audit file."""
    from .plain_language import humanize, is_plain, phrase
    # Scenario texts: kept when plain, else with the code taken out, else left out.
    for key in SCENARIO_FIELDS:
        cleaned = [s if is_plain(s) else phrase(s) for s in rule.get(key, [])]
        rule[key] = [s for s in dict.fromkeys(cleaned) if s]
    original = rule["statement"]
    if is_business_language(original):
        return
    rule["statement_original"] = original
    stripped = phrase(original)
    cond, outcome = phrase(rule.get("condition", "")), phrase(rule.get("outcome", ""))
    if stripped and is_business_language(stripped):
        text = stripped
    elif cond and outcome:
        text = f"When {cond[:1].lower() + cond[1:]}, {outcome[:1].lower() + outcome[1:]}"
    else:
        symbol = rule["sources"][0].get("symbol", "")
        where = " ".join(humanize(p) for p in symbol.replace("#", ".").split(".")[-2:] if p).lower() or "this part"
        text = (f"The system applies a {_TYPE_WORDS.get(rule['type'], rule['type'])} rule in {where}; "
                "its business meaning is to be confirmed with the business owner")
        rule["basis"], rule["confidence"] = "inferred", "low"
    rule["statement"] = text.rstrip(" .") + "."


def _test_index(workspace_dir: str, test_files: list[str]) -> dict[str, set[str]]:
    """Identifier -> test files that mention it (capitalised words only)."""
    root = Path(workspace_dir)
    index: dict[str, set[str]] = defaultdict(set)
    for rel in test_files:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")[:400_000]
        except OSError:
            continue
        for word in set(re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", text)) | {Path(rel).stem}:
            index[word].add(rel)
    return index


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def coverage(ledger: dict, scan_stats: dict) -> dict:
    statuses = defaultdict(int)
    by_kind: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    truncated = 0
    for entry in ledger["candidates"].values():
        statuses[entry["status"]] += 1
        by_kind[entry["kind"]][entry["status"]] += 1
        truncated += bool(entry.get("truncated"))
    rules = ledger["rules"]
    points = defaultdict(int)
    for row in decision_report(ledger):
        points[row["status"]] += 1
    return {
        "decision_points": dict(points),
        "candidates": len(ledger["candidates"]),
        "statuses": dict(statuses),
        "by_kind": {k: dict(v) for k, v in by_kind.items()},
        "truncated": truncated,
        "rules": len(rules),
        "raw_rules": len(ledger["raw_rules"]),
        "flagged": sum(1 for r in rules if r["flags"]),
        "unverified": sum(1 for r in rules if not r.get("verified", True)),
        "dropped_scenarios": sum(len(r.get("dropped", [])) for r in rules),
        "inferred": sum(1 for r in rules if r["basis"] == "inferred"),
        "with_tests": sum(1 for r in rules if r["tests"]),
        **scan_stats,
    }


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def coverage_markdown(cov: dict) -> str:
    s = cov["statuses"]
    lines = [
        "## Business Rules Coverage", "",
        "_Every candidate below was found by parsing the code; every one is accounted for._", "",
        f"- **Rule candidates found:** {cov['candidates']:,}",
        f"- **Contain business rules:** {s.get('rule', 0):,}",
        f"- **Technical, classified by the agent:** {s.get('technical', 0):,}",
        f"- **Technical, classified without the agent** (accessors, null checks only): {s.get('auto-technical', 0):,}",
        f"- **Unclassified:** {s.get('unclassified', 0):,}" + (" — see the ledger download for each reason"
                                                               if s.get("unclassified") else ""),
        f"- **Business rules:** {cov['rules']:,} (from {cov['raw_rules']:,} findings after merging duplicates); "
        f"{cov['inferred']:,} inferred, {cov['flagged']:,} with citation flags, {cov['with_tests']:,} with a "
        "test that names their class or file",
        f"- **Not traceable to the code, left out of the BRD:** {cov.get('unverified', 0):,} rules and "
        f"{cov.get('dropped_scenarios', 0):,} scenario entries — see Grounding Checks",
    ]
    dp = cov.get("decision_points") or {}
    if dp:
        total = sum(dp.values())
        lines += [
            f"- **Decision points found:** {total:,} — each condition, branch, comparison, access rule, "
            "validation, rendering decision, session or model write; every one accounted for below:",
            f"  - implement a business rule in the BRD: {dp.get('rule', 0):,}",
            f"  - named by a rule that could not be traced to the code: {dp.get('unverified rule', 0):,}",
            f"  - technical, dismissed by the agent with a reason: {dp.get('technical', 0):,}",
            f"  - technical, dismissed without the agent (accessors, null checks only): {dp.get('auto-technical', 0):,}",
            f"  - **unaccounted for: {dp.get('unaccounted', 0):,}**" + (" — listed under Decision Points Not "
                                                                         "Accounted For" if dp.get("unaccounted")
                                                                         else ""),
        ]
    if cov.get("excluded"):
        lines.append(f"- **Not analysed:** {cov['excluded']:,} candidates in code of stacks that were not "
                     "confirmed for documentation.")
    if cov.get("parser_error"):
        lines.append(f"- **Parser unavailable:** {cov['parser_error']} — Java/JavaScript/TypeScript were not "
                     "analysed for rules.")
    if cov.get("truncated"):
        lines.append(f"- **Truncated candidates:** {cov['truncated']:,} were longer than the per-candidate limit "
                     "and could not be split; only their first part was analysed (raise "
                     "`RULES_CANDIDATE_MAX_LINES`).")
    lines += ["", "| Candidate kind | Rules | Technical | Auto-technical | Unclassified |", "|---|---|---|---|---|"]
    for kind, counts in sorted(cov["by_kind"].items()):
        lines.append(f"| {kind} | {counts.get('rule', 0)} | {counts.get('technical', 0)} | "
                     f"{counts.get('auto-technical', 0)} | {counts.get('unclassified', 0)} |")
    lines += ["", "| Language | Files scanned | Parser |", "|---|---|---|"]
    for lang, info in sorted(cov.get("languages", {}).items()):
        lines.append(f"| {lang} | {info['files']:,} | {info['parser']} |")
    for lang, n in sorted(cov.get("unparsed", {}).items()):
        lines.append(f"| {lang} | {n:,} | **not analysed for rules** (no parser) |")
    if cov.get("parse_errors"):
        lines += ["", f"**Files not scanned ({len(cov['parse_errors'])}):** "
                  + "; ".join(_cell(e) for e in cov["parse_errors"][:10])
                  + (" …" if len(cov["parse_errors"]) > 10 else "")]
    lines += ["", "Not covered by any parser, whatever the counts above say: rules held in database rows, "
              "configuration managed outside the repository, external services, and code generated at build time."]
    return "\n".join(lines)


def catalog_markdown(ledger: dict, max_rules: int) -> str:
    rules = verified_rules(ledger)
    lines = ["## Business Rules Catalog", ""]
    if not rules:
        return "\n".join(lines + ["No business rules were found in the analysed code."])
    shown = rules[:max_rules]
    if len(rules) > max_rules:
        lines += [f"> Showing {max_rules:,} of {len(rules):,} rules. The complete list is in the business-rules "
                  "download (CSV), which has every rule and every candidate.", ""]
    area = None
    for rule in shown:
        if rule["area"] != area:
            area = rule["area"]
            lines += ["", f"### {area}", "", "| ID | Rule | Type | Condition → Outcome | Source | Tests | Basis |",
                      "|---|---|---|---|---|---|---|"]
        src = "; ".join(f"`{s['path']}:{s['start']}-{s['end']}`" for s in rule["sources"][:3])
        if len(rule["sources"]) > 3:
            src += f"; +{len(rule['sources']) - 3} more"
        cond = " → ".join(x for x in (rule["condition"], rule["outcome"]) if x) or "—"
        tests = "; ".join(f"`{t}`" for t in rule["tests"][:2]) or "none found"
        basis = f"{rule['basis']}, {rule['confidence']}" + (" ⚠ " + "; ".join(rule["flags"]) if rule["flags"] else "")
        stated = rule["statement"] + (f" (as extracted: {rule['statement_original']})"
                                      if rule.get("statement_original") else "")
        lines.append(f"| {rule['id']} | {_cell(stated)} | {rule['type']} | {_cell(cond)} | {src} | "
                     f"{tests} | {_cell(basis)} |")
    return "\n".join(lines)


BUSINESS_RULES_HEADING = "## Business Rules by Capability"


NONE_IDENTIFIED = "None identified"


def bullets(items: list[str]) -> str:
    """Several entries in one table cell: "• a • b" (the review screen and Word
    show each on its own line); "None identified" when there are none."""
    return " ".join(f"• {i}" for i in items) if items else NONE_IDENTIFIED


def business_rules_markdown(ledger: dict | None, max_rules: int) -> str:
    """The BRD's business rules: one table per capability, one row per rule — rule id,
    the rule, its use cases, negative scenarios and edge cases (as many of each as
    the code shows, one "•" entry each), observed or inferred,
    confidence. Plain English only; where a rule is implemented is never shown here."""
    rules = verified_rules(ledger)
    lines = [BUSINESS_RULES_HEADING]
    if not rules:
        return "\n".join(lines + ["", "No business rules were found in the analysed parts of the system."])
    shown = rules[:max_rules]
    if len(rules) > max_rules:
        lines += ["", f"> Showing {max_rules:,} of {len(rules):,} rules. The business-rules download (CSV) "
                  "lists all of them."]
    capability = None
    for rule in shown:
        if rule.get("capability") != capability:
            capability = rule.get("capability")
            lines += ["", f"### {capability}", "",
                      "| Rule ID | Business rule | Use cases | Negative scenarios | Edge cases | "
                      "Observed or inferred | Confidence |", "|---|---|---|---|---|---|---|"]
        lines.append(" | ".join([
            f"| {rule['id']}", _cell(rule["statement"]),
            *(_cell(bullets(rule.get(key) or [])) for key in SCENARIO_FIELDS),
            "Observed" if rule.get("basis") == "explicit" else "Inferred",
            str(rule.get("confidence") or "medium").capitalize()]) + " |")
    return "\n".join(lines)


def decisions_markdown(ledger: dict) -> str:
    """The audit view of the decision points: every one not accounted for, every one the
    agent dismissed as technical (with its reason), every one only an untraceable rule names."""
    rows = decision_report(ledger)
    if not rows:
        return ""
    lines = ["## Decision Points", "",
             "_Every decision the code makes was listed by parsing and had to be accounted for: named by a "
             "business rule, or dismissed as technical with a reason. Review the dismissals: a business decision "
             "dismissed here is missing from the BRD. The full list, with the rule each point implements, is in "
             "the decision-points download._", ""]
    for status, title in (("unaccounted", "Decision Points Not Accounted For"),
                          ("unverified rule", "Decision Points Only an Untraceable Rule Names"),
                          ("technical", "Decision Points Dismissed as Technical by the Agent")):
        group = [r for r in rows if r["status"] == status]
        lines += [f"### {title} ({len(group):,})", ""]
        if not group:
            lines += ["None.", ""]
            continue
        lines += ["| Point | Where | Kind | Code | Reason |", "|---|---|---|---|---|"]
        lines += [f"| {r['id']} | `{r['path']}:{r['line']}` | {r['kind']} | `{_cell(r['text'][:120])}` | "
                  f"{_cell(r['reason']) or '—'} |" for r in group]
        lines.append("")
    auto = sum(1 for r in rows if r["status"] == "auto-technical")
    lines.append(f"{auto:,} decision point(s) were dismissed without the agent (accessors, null checks only); "
                 "they are in the decision-points download.")
    return "\n".join(lines)


def decisions_csv(ledger: dict) -> str:
    """Every decision point: where, what, how it was accounted for, and the rules it implements."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["decision_point", "file", "line", "kind", "code", "status", "rules", "reason", "candidate", "area"])
    for r in decision_report(ledger):
        w.writerow([r["id"], r["path"], r["line"], r["kind"], r["text"], r["status"], "; ".join(r["rules"]),
                    r["reason"], r["candidate"], r["area"]])
    return out.getvalue()


def to_csv(ledger: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["record", "id", "statement_or_symbol", "type_or_kind", "condition", "outcome", "basis",
                "confidence", "area", "sources", "tests", "flags_or_reason", "status", "capability",
                "statement_as_extracted", "use_cases", "negative_scenarios", "edge_cases"])
    for r in ledger["rules"]:
        w.writerow(["rule", r["id"], r["statement"], r["type"], r["condition"], r["outcome"], r["basis"],
                    r["confidence"], r["area"],
                    "; ".join(f"{s['path']}:{s['start']}-{s['end']}" for s in r["sources"]),
                    "; ".join(r["tests"]), "; ".join(r["flags"] + r.get("unverified_reasons", [])
                                                     + [f"dropped {d['kind'][:-1].replace('_', ' ')} “{d['text']}”: "
                                                        + "; ".join(d["reasons"]) for d in r.get("dropped", [])]),
                    "rule" if r.get("verified", True) else "unverified", r.get("capability", ""),
                    r.get("statement_original", ""), *("; ".join(r.get(k, [])) for k in SCENARIO_FIELDS)])
    for cid, c in ledger["candidates"].items():
        w.writerow(["candidate", cid, c["symbol"], c["kind"], "", "", "", "", c["area"],
                    f"{c['path']}:{c['start']}-{c['end']}", "", c.get("reason", ""),
                    c["status"] + (f" ({', '.join(c.get('rule_ids', []))})" if c.get("rule_ids") else "")])
    return out.getvalue()
