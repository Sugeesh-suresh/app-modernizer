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
- tests are attached by name: test files that mention the rule's class or file.
"""
import csv
import io
import json
import re
from collections import defaultdict
from pathlib import Path

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


def render_batch(batch: list[Candidate]) -> str:
    parts = []
    for c in batch:
        parts.append(
            f"### {c.id} — {c.kind} `{c.symbol}`\n"
            f"File: `{c.path}` lines {c.start}-{c.end} ({c.language}; signals: {', '.join(c.signals) or '—'})"
            + ("\n**Truncated:** only the first part of this code is shown." if c.truncated else "")
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


def apply_answer(batch: list[Candidate], results: list[dict], ledger: dict) -> list[Candidate]:
    """Record the answer for this batch in `ledger`; return the candidates it left out."""
    by_id = {c.id: c for c in batch}
    answered: set[str] = set()
    for result in results:
        cid = str(result.get("candidate") or result.get("id") or "").strip()
        c = by_id.get(cid)
        if c is None or cid in answered:
            continue
        rules = result.get("rules") if isinstance(result.get("rules"), list) else []
        rules = [r for r in rules if isinstance(r, dict) and str(r.get("statement") or "").strip()]
        technical = str(result.get("technical") or "").strip()
        if not rules and not technical:
            continue
        answered.add(cid)
        entry = ledger["candidates"][cid]
        if not rules:
            entry.update(status="technical", reason=technical[:300])
            continue
        entry["status"] = "rule"
        for r in rules:
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
                "type": rtype if rtype in RULE_TYPES else "other",
                "condition": str(r.get("condition") or "").strip()[:400],
                "outcome": str(r.get("outcome") or "").strip()[:400],
                "basis": "inferred" if str(r.get("basis") or "").lower().startswith("infer") else "explicit",
                "confidence": str(r.get("confidence") or "").lower() if str(r.get("confidence") or "").lower()
                in ("high", "medium", "low") else "medium",
                "area": c.area,
                "sources": [{"candidate": cid, "path": c.path, "start": a, "end": b, "symbol": c.symbol}],
                "flags": flags,
            })
            entry.setdefault("rule_count", 0)
            entry["rule_count"] += 1
    return [c for c in batch if c.id not in answered]


def new_ledger(candidates: list[Candidate]) -> dict:
    return {
        "candidates": {c.id: {**c.to_dict(), "status": c.status if c.status != "pending" else "pending",
                              "reason": c.reason} for c in candidates},
        "raw_rules": [],
        "rules": [],
    }


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


def _similar(a: str, b: str) -> bool:
    sa, sb = set(a.split()), set(b.split())
    return bool(sa and sb) and len(sa & sb) / len(sa | sb) >= 0.9


def finalize(ledger: dict, workspace_dir: str, test_files: list[str]) -> None:
    """Merge duplicates, attach tests, assign BR ids. Idempotent on `raw_rules`."""
    merged: list[dict] = []
    exact: dict[tuple, dict] = {}
    # Near-duplicates are only looked for among rules of the same type that share
    # their first words — linear overall, where comparing every pair would not be.
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for rule in ledger["raw_rules"]:
        norm = _norm(rule["statement"])
        key = (rule["type"], " ".join(norm.split()[:3]))
        target = exact.get((rule["type"], norm)) or next(
            (m for m in buckets[key][-50:] if _similar(m["_norm"], norm)), None)
        if target is None:
            rule = {**rule, "sources": list(rule["sources"]), "flags": list(rule["flags"]), "_norm": norm}
            exact[(rule["type"], norm)] = rule
            buckets[key].append(rule)
            merged.append(rule)
        else:
            target["sources"] += [s for s in rule["sources"] if s not in target["sources"]]
            target["flags"] += [f for f in rule["flags"] if f not in target["flags"]]
            if rule["basis"] == "explicit":
                target["basis"] = "explicit"
    index = _test_index(workspace_dir, test_files)
    merged.sort(key=lambda r: (r["area"], r["sources"][0]["path"], r["sources"][0]["start"]))
    for i, rule in enumerate(merged, 1):
        rule.pop("_norm", None)
        rule["id"] = f"BR-{i:04d}"
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
    return {
        "candidates": len(ledger["candidates"]),
        "statuses": dict(statuses),
        "by_kind": {k: dict(v) for k, v in by_kind.items()},
        "truncated": truncated,
        "rules": len(rules),
        "raw_rules": len(ledger["raw_rules"]),
        "flagged": sum(1 for r in rules if r["flags"]),
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
    ]
    if cov.get("excluded"):
        lines.append(f"- **Not analysed:** {cov['excluded']:,} candidates in code of stacks that were not "
                     "confirmed for documentation.")
    if cov.get("parser_error"):
        lines.append(f"- **Parser unavailable:** {cov['parser_error']} — Java/JavaScript/TypeScript were not "
                     "analysed for rules.")
    if cov.get("truncated"):
        lines.append(f"- **Truncated candidates:** {cov['truncated']:,} were longer than the per-candidate limit; "
                     "only their first part was analysed (raise `RULES_CANDIDATE_MAX_LINES`).")
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
    rules = ledger["rules"]
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
        lines.append(f"| {rule['id']} | {_cell(rule['statement'])} | {rule['type']} | {_cell(cond)} | {src} | "
                     f"{tests} | {_cell(basis)} |")
    return "\n".join(lines)


def to_csv(ledger: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["record", "id", "statement_or_symbol", "type_or_kind", "condition", "outcome", "basis",
                "confidence", "area", "sources", "tests", "flags_or_reason", "status"])
    for r in ledger["rules"]:
        w.writerow(["rule", r["id"], r["statement"], r["type"], r["condition"], r["outcome"], r["basis"],
                    r["confidence"], r["area"],
                    "; ".join(f"{s['path']}:{s['start']}-{s['end']}" for s in r["sources"]),
                    "; ".join(r["tests"]), "; ".join(r["flags"]), "rule"])
    for cid, c in ledger["candidates"].items():
        w.writerow(["candidate", cid, c["symbol"], c["kind"], "", "", "", "", c["area"],
                    f"{c['path']}:{c['start']}-{c['end']}", "", c.get("reason", ""),
                    c["status"] + (f" ({', '.join(c.get('rule_ids', []))})" if c.get("rule_ids") else "")])
    return out.getvalue()
