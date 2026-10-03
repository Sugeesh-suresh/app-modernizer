"""
Business-rules extraction and large-repository discovery: candidates found by
parsing, every candidate accounted for, answers checked against the code, and a
stack too large for one run documented unit by unit.
"""
import asyncio
import json
import re
from pathlib import Path

import pytest

import main
from agents import APP_NAME, USER_ID, config, session_service
from agents.shared import rule_candidates as rc
from agents.shared import rules_ledger as rl


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


REPO = {
    "src/main/java/com/acme/orders/OrderService.java": """package com.acme.orders;

public class OrderService {
    public static final int MAX_ITEMS = 50;
    private static final long serialVersionUID = 1L;
    @NotNull @Size(max = 20) private String code;

    public void place(Order o) {
        if (o.getItems().size() > MAX_ITEMS) {
            throw new TooManyItemsException("max " + MAX_ITEMS);
        }
        if (o.getTotal() > 1000 && !o.getCustomer().isVip()) {
            o.setState(State.PENDING_APPROVAL);
        }
    }

    public void save(Order o) {
        if (o == null) { throw new IllegalArgumentException("o"); }
        repo.save(o);
    }

    public String getCode() { return code; }
    public boolean equals(Object x) { return x != null && x == this; }
}
""",
    "src/main/java/com/acme/billing/State.java": "package com.acme.billing;\npublic enum State { NEW, PENDING_APPROVAL, PLACED }\n",
    "src/test/java/com/acme/OrderServiceTest.java": "class OrderServiceTest { OrderService s; }\n",
    "web/js/models.js": """define(['backbone'], function (Backbone) {
  return Backbone.Model.extend({
    validate: function (attrs) {
      if (!attrs.email) { return 'Email is required'; }
      if (attrs.age < 18) { return 'Must be 18 or older'; }
    }
  });
});
""",
    "web/js/lib/jquery.js": "function x(a){ if (a > 1) return 1; }",
    "db/schema.sql": "CREATE TABLE orders (\n  qty NUMBER CHECK (qty BETWEEN 1 AND 50)\n);\n"
                     "CREATE OR REPLACE PROCEDURE apply_discount(p NUMBER) AS\nBEGIN\n  IF v > 1000 THEN NULL; END IF;\nEND;\n/\n",
    "scripts/fees.py": "def fee(amount):\n    if amount is None:\n        return 0\n    return 5 if amount < 100 else 0\n",
    "rules/pricing.drl": 'rule "Gold discount"\n  when Customer(tier == "GOLD")\n  then setDiscount(0.2);\nend\n',
    "web/order.jsp": '<%@ page %>\n<c:if test="${order.total > 1000}">Approval needed</c:if>\n',
    "svc/main.go": "package main\nfunc f(a int) bool { return a > 1 }\n",
}


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

def test_candidates_are_found_by_parsing_every_supported_language(tmp_path):
    scan = rc.scan(str(_write(tmp_path, REPO)))
    found = {(c.kind, c.symbol.rsplit(".", 1)[-1] if c.kind == "method" else c.symbol, c.status) for c in scan.candidates}
    assert ("method", "place", "pending") in found
    assert ("method", "save", "auto-technical") in found              # null guard only
    assert ("method", "equals", "auto-technical") in found
    assert ("validation", "com.acme.orders.OrderService", "pending") in found
    assert ("constants", "com.acme.orders.OrderService", "pending") in found
    assert ("enum", "com.acme.billing.State", "pending") in found
    assert ("method", "validate", "pending") in found                 # Backbone `validate: function`
    assert ("method", "fee", "pending") in found                      # Python via ast
    assert ("sql-constraint", "orders", "pending") in found
    assert ("sql-routine", "apply_discount", "pending") in found
    assert ("rules-engine", "Gold discount", "pending") in found
    assert ("view-logic", "order.jsp", "pending") in found
    assert not [c for c in scan.candidates if "lib/" in c.path or "/test/" in c.path]   # vendored, tests
    assert "getCode" not in {c.symbol.rsplit(".", 1)[-1] for c in scan.candidates}        # no decision
    assert scan.test_files == ["src/test/java/com/acme/OrderServiceTest.java"]
    assert scan.unparsed == {"Go": 1}
    assert scan.files_by_language["Java"] == {"files": 2, "parser": "tree-sitter"}
    assert [c.id for c in scan.candidates] == [f"C{i:05d}" for i in range(1, len(scan.candidates) + 1)]


def test_candidate_source_is_numbered_and_bounded(tmp_path):
    body = "\n".join(f"        if (x > {i}) y();" for i in range(30))
    _write(tmp_path, {"A.java": f"class A {{\n    void big(int x) {{\n{body}\n    }}\n}}\n"})
    [c] = rc.scan(str(tmp_path), max_lines=10).candidates
    assert c.truncated and c.source.splitlines()[0].startswith(" 2| ") and len(c.source.splitlines()) == 10


def test_a_file_that_does_not_parse_is_reported_not_fatal(tmp_path):
    _write(tmp_path, {"bad.py": "def f(:\n", "ok.py": "def g(a):\n    return a > 1\n"})
    scan = rc.scan(str(tmp_path))
    assert [c.symbol for c in scan.candidates] == ["g"]
    assert any("bad.py" in e for e in scan.parse_errors)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def _place(tmp_path):
    scan = rc.scan(str(_write(tmp_path, REPO)))
    return scan, next(c for c in scan.candidates if c.symbol.endswith(".place"))


def test_answers_are_checked_against_the_code(tmp_path):
    scan, place = _place(tmp_path)
    ledger = rl.new_ledger(scan.candidates)
    missing = rl.apply_answer([place], [
        {"candidate": "C99999", "rules": [{"statement": "invented"}]},                  # not in the batch
        {"candidate": place.id, "rules": [
            {"statement": "Orders over `MAX_ITEMS` items are rejected.", "type": "validation",
             "lines": "9-11", "basis": "explicit", "confidence": "high"},
            {"statement": "Uses `FraudScore` above 0.9.", "type": "made-up", "lines": "200-210"},
        ]},
    ], ledger)
    assert missing == []
    good, bad = ledger["raw_rules"]
    assert good["flags"] == [] and good["type"] == "validation" and good["sources"][0]["start"] == 9
    assert bad["type"] == "other"
    assert any("clamped" in f for f in bad["flags"]) and any("FraudScore" in f for f in bad["flags"])
    assert bad["sources"][0]["start"] >= place.start and bad["sources"][0]["end"] <= place.end
    assert ledger["candidates"][place.id]["status"] == "rule"


def test_unanswered_candidates_are_returned_and_then_marked(tmp_path):
    scan, place = _place(tmp_path)
    ledger = rl.new_ledger(scan.candidates)
    pending = [c for c in scan.candidates if c.status == "pending"]
    missing = rl.apply_answer(pending, [{"candidate": place.id, "rules": [], "technical": "plumbing"}], ledger)
    assert place not in missing and len(missing) == len(pending) - 1
    rl.mark_unclassified(missing, ledger, "the agent's answer did not cover it")
    statuses = {e["status"] for e in ledger["candidates"].values()}
    assert statuses == {"technical", "unclassified", "auto-technical"}


def test_duplicates_merge_tests_attach_and_ids_are_stable(tmp_path):
    scan, place = _place(tmp_path)
    validate = next(c for c in scan.candidates if c.symbol == "validate")
    ledger = rl.new_ledger(scan.candidates)
    rl.apply_answer([place], [{"candidate": place.id, "rules": [
        {"statement": "A customer must be 18 or older.", "type": "eligibility", "lines": "12-14"}]}], ledger)
    rl.apply_answer([validate], [{"candidate": validate.id, "rules": [
        {"statement": "A customer must be 18 or older!", "type": "eligibility", "lines": "5"}]}], ledger)
    rl.finalize(ledger, str(tmp_path), scan.test_files)
    [rule] = ledger["rules"]
    assert rule["id"] == "BR-0001" and len(rule["sources"]) == 2
    assert rule["tests"] == ["src/test/java/com/acme/OrderServiceTest.java"]          # names OrderService
    assert ledger["candidates"][place.id]["rule_ids"] == ["BR-0001"]


def test_reports_count_every_candidate(tmp_path):
    scan, place = _place(tmp_path)
    ledger = rl.new_ledger(scan.candidates)
    rl.apply_answer([place], [{"candidate": place.id, "rules": [
        {"statement": "Orders over 1000 for non-VIP customers need approval.", "type": "workflow", "lines": "12-14",
         "basis": "inferred"}]}], ledger)
    rl.mark_unclassified([c for c in scan.candidates if c.status == "pending" and c is not place], ledger, "x")
    rl.finalize(ledger, str(tmp_path), [])
    cov = rl.coverage(ledger, {"languages": scan.files_by_language, "unparsed": scan.unparsed,
                               "parse_errors": [], "excluded": 3})
    assert sum(cov["statuses"].values()) == cov["candidates"] == len(scan.candidates)
    md = rl.coverage_markdown(cov)
    assert "**Business rules:** 1" in md and "Go | 1 | **not analysed for rules**" in md and "**Not analysed:** 3" in md
    catalog = rl.catalog_markdown(ledger, 10)
    assert "| BR-0001 | Orders over 1000 for non-VIP customers need approval. | workflow |" in catalog
    assert "inferred" in catalog
    csv_text = rl.to_csv(ledger)
    assert csv_text.count("\ncandidate,") == len(scan.candidates) and "\nrule,BR-0001," in csv_text


def test_the_document_lists_up_to_the_limit_and_says_so():
    ledger = {"rules": [{"id": f"BR-{i:04d}", "statement": f"r{i}", "type": "other", "condition": "", "outcome": "",
                         "basis": "explicit", "confidence": "high", "area": "a", "flags": [], "tests": [],
                         "sources": [{"path": "a.py", "start": 1, "end": 1}]} for i in range(5)]}
    md = rl.catalog_markdown(ledger, 2)
    assert "Showing 2 of 5 rules" in md and "BR-0002" not in md


@pytest.mark.parametrize("answer", [
    '```json\n{"results": [{"candidate": "C1", "rules": []}]}\n```',
    'prose {"results": [{"candidate": "C1"}]} more',
    '[{"candidate": "C1"}]',
])
def test_answers_are_parsed_in_any_reasonable_shape(answer):
    assert rl.parse_answer(answer)[0]["candidate"] == "C1"


def test_batches_respect_both_limits(tmp_path):
    scan = rc.scan(str(_write(tmp_path, REPO)))
    pending = [c for c in scan.candidates if c.status == "pending"]
    out = rl.batches(pending, 3, 10_000)
    assert [c for b in out for c in b] == pending and all(len(b) <= 3 for b in out)


# ---------------------------------------------------------------------------
# Orchestration (agents replaced by fakes that answer from the request)
# ---------------------------------------------------------------------------

def _session(tmp_path, stacks: list[dict]) -> str:
    state = main._initial_state("stack-discovery", str(tmp_path), str(tmp_path), "[]", "bigbang", False, False,
                                json.dumps(stacks))
    state["companion_patterns_json"] = json.dumps([s["pattern"] for s in stacks])
    sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
    main._sse_queues[sid] = asyncio.Queue()
    return sid


def _answer_every_candidate(batch_text: str) -> str:
    results = []
    for cid, start in re.findall(r"### (C\d{5}) .*?\nFile: `[^`]+` lines (\d+)-", batch_text):
        results.append({"candidate": cid, "rules": [
            {"statement": f"Rule of {cid}.", "type": "validation", "lines": start, "basis": "explicit"}]})
    return "```json\n" + json.dumps({"results": results}) + "\n```"


def test_rules_extraction_classifies_every_candidate_of_the_confirmed_stacks(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RULES_EXTRACTION", "on")
    monkeypatch.setattr(config, "RULES_BATCH_MAX_CANDIDATES", 2)
    _write(tmp_path, REPO)
    calls = []

    async def fake(step, pattern, state, message, output_key):
        calls.append(step)
        text = state["rule_batch"]
        if "validate" in text and calls.count("rules") == 1:
            raise RuntimeError("quota")                       # the first try of one batch fails…
        answer = json.loads(_answer_every_candidate(text)[8:-4])
        answer["results"] = answer["results"][1:] if "Gold discount" in text and "retry" not in calls else answer["results"]
        if "Gold discount" in text:
            calls.append("retry")                            # …another answers partially, then fully
        return "```json\n" + json.dumps(answer) + "\n```"

    monkeypatch.setattr(main, "_run_isolated", fake)
    stacks = [{"pattern": "java", "kind": "application"}, {"pattern": "backbone", "kind": "frontend"}]
    sid = _session(tmp_path, stacks)
    asyncio.run(main._run_rules_extraction(sid))
    state = asyncio.run(main._get_state(sid))
    ledger = json.loads(Path(state["rules_ledger_path"]).read_text())
    languages = {e["language"] for e in ledger["candidates"].values()}
    assert languages == {"Java", "JavaScript", "Drools"}                   # Python/SQL/JSP: stacks not confirmed
    pending = [e for e in ledger["candidates"].values() if e["status"] not in ("auto-technical",)]
    assert pending and all(e["status"] == "rule" for e in pending), pending
    cov = json.loads(state["rules_coverage_json"])
    assert cov["excluded"] > 0 and cov["statuses"].get("unclassified", 0) == 0
    assert "## Business Rules Catalog" in state["rules_markdown"]
    assert "## Business Rules Coverage" in state["rules_markdown"]


def test_a_batch_that_keeps_failing_is_unclassified_with_the_reason(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RULES_EXTRACTION", "on")
    _write(tmp_path, {"a.py": "def f(a):\n    return a > 1\n"})

    async def failing(*a, **k):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(main, "_run_isolated", failing)
    sid = _session(tmp_path, [{"pattern": "python", "kind": "language"}])
    asyncio.run(main._run_rules_extraction(sid))
    ledger = json.loads(Path(asyncio.run(main._get_state(sid))["rules_ledger_path"]).read_text())
    [entry] = ledger["candidates"].values()
    assert entry["status"] == "unclassified" and "model unavailable" in entry["reason"]


def test_file_units_cover_every_file_once_within_the_limit():
    files = [f"a/{i}.java" for i in range(7)] + [f"b/c/{i}.java" for i in range(3)] + ["d/x.java"]
    units = main._file_units(files, 4)
    assert sorted(f for u in units for f in u) == sorted(files)
    assert all(len(u) <= 4 for u in units)
    assert ["b/c/0.java", "b/c/1.java", "b/c/2.java", "d/x.java"] in units      # small directories share


def test_a_large_stack_is_gathered_unit_by_unit(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DISCOVERY_UNIT_MAX_FILES", 3)
    files = [f"src/m{i // 3}/F{i}.java" for i in range(8)]
    _write(tmp_path, {f: "class X {}" for f in files})
    runs = []

    async def fake(step, pattern, state, message, output_key):
        runs.append(step)
        listed = re.findall(r"- `([^`]+)`", state["unit_scope"])
        if "F7" in state["unit_scope"]:
            raise RuntimeError("quota")
        return "### Components\n" + "\n".join(f"- `{f}` component" for f in listed)

    monkeypatch.setattr(main, "_run_isolated", fake)
    sid = _session(tmp_path, [{"pattern": "java", "kind": "application"}])
    text = asyncio.run(main._gather_unit_evidence(sid, {"pattern": "java", "kind": "application"},
                                                  "Java application", "java.md", files))
    assert runs == ["discover_unit"] * 3                                    # 8 files, units of 3
    assert all(f"`{f}` component" in text for f in files[:6])
    assert "**Not analysed** — quota" in text and "`src/m2/F7.java`" in text   # a failed unit is stated


def test_evidence_too_large_for_one_request_is_merged_keeping_every_id(monkeypatch):
    pieces = [f"## Stack {s} (`s{s}`)\n\n### Components\n" + "\n".join(
        f"- [EV-s{s}-{i:04d}] component {i} " + "detail " * 10 for i in range(1, 11)) for s in range(3)]
    merged_requests = []

    async def fake(step, pattern, state, message, output_key):
        assert step == "discover_merge"
        merged_requests.append(state["findings_batch"])
        return "\n".join(re.findall(r"\[EV-[^\]]+\]", state["findings_batch"]))

    monkeypatch.setattr(main, "_run_isolated", fake)
    out = asyncio.run(main._merge_to_budget(pieces, 2_000, "test"))
    assert merged_requests and sum(len(p) for p in out) <= 2_000 * 2
    ids = set(re.findall(r"EV-s\d-\d{4}", "\n".join(out)))
    assert ids == {f"EV-s{s}-{i:04d}" for s in range(3) for i in range(1, 11)}


def test_stack_files_are_the_stacks_own_sources(tmp_path):
    _write(tmp_path, {"a/A.java": "", "web/app.js": "", "web/lib/backbone-min.js": "", "web/x.min.js": "",
                      "db/s.sql": "", "tools/t.py": ""})
    assert main._stack_files(str(tmp_path), {"pattern": "java"}) == ["a/A.java"]
    assert main._stack_files(str(tmp_path), {"pattern": "backbone", "kind": "frontend"}) == ["web/app.js"]
    assert main._stack_files(str(tmp_path), {"pattern": "python", "kind": "language"}) == ["tools/t.py"]
    assert main._stack_files(str(tmp_path), {"pattern": "oracle", "kind": "database"}) is None


def test_merge_batches_always_shrink_even_when_nothing_fits_together():
    items = ["x" * 600] * 3
    batches = main._batch_by_size(items, 900)
    assert len(batches) < len(items) and [i for b in batches for i in b] == items


def test_the_ledger_downloads_as_csv_and_is_not_kept_in_session_state(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(config, "RULES_EXTRACTION", "on")
    _write(tmp_path, {"a.py": "def f(a):\n    return a > 1\n"})

    async def answer(step, pattern, state, message, output_key):
        return _answer_every_candidate(state["rule_batch"])

    monkeypatch.setattr(main, "_run_isolated", answer)
    sid = _session(tmp_path, [{"pattern": "python", "kind": "language"}])
    asyncio.run(main._run_rules_extraction(sid))
    state = asyncio.run(main._get_state(sid))
    assert not any(k.startswith("rules_ledger_json") for k in state)
    with TestClient(main.app) as client:
        res = client.get(f"/api/sessions/{sid}/download/business-rules")
        missing = client.get(f"/api/sessions/{_session(tmp_path, [])}/download/business-rules")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    assert "\nrule,BR-0001,Rule of C00001." in res.text and "\ncandidate,C00001," in res.text
    assert missing.status_code == 404
