"""The BRD in business language: no code and no code references, with the
evidence each statement rests on moved to evidence.md beside the evidence packs."""
import asyncio

from fastapi.testclient import TestClient

import main
from agents.shared import evidence_pack as ep
from agents.shared import plain_language as pl
from agents.shared import rules_ledger
from tests.test_stack_discovery_workflow import PRESCAN, _session

PO_OUTPUT = """## Executive Summary
The application takes customer orders (EV-java-0005, EV-jsp-0003, BR-0001). It runs every night.

## Business Rules by Capability
### Order approval
- EV-jsp-0007: `src/main/webapp/order.jsp:4` — decision: `<c:if test="${order.total > 100}">` — see BR-0001
- Orders above 100 units need approval in `OrderService.approve()` (EV-java-0012).
- The `OrderService` puts such orders in `PENDING_APPROVAL` status (BR-0007).
- See app.js and OrderService.java:12 for the rules. Managers approve refunds (BR-0002).
- Uses `com.acme.order.OrderValidator` checks.
- A journey through the Backbone.js front end.

| Actor | Can do |
|---|---|
| Manager `ROLE_MANAGER` | approves orders via `OrderController.approve()` [EV-java-0002] |

```java
if (total > 100) { approve(); }
```
<!-- SECTION: END -->
"""


def test_the_brd_keeps_business_sentences_and_loses_every_code_reference():
    text, cited, removed = pl.business_only(PO_OUTPUT)
    assert pl.is_plain(text) and "`" not in text and "EV-" not in text and "<!--" not in text
    assert "The application takes customer orders (BR-0001). It runs every night." in text
    assert "- Orders above 100 units need approval." in text                  # the location goes, the rule stays
    assert "- The Order Service puts such orders in Pending Approval status (BR-0007)." in text
    assert "- Managers approve refunds (BR-0002)." in text                    # a code-only sentence goes
    assert "Backbone.js" in text                                              # a product name is not a file
    assert "decision" not in text and "Validator" not in text and "approve()" not in text
    assert "| Manager Manager | approves orders |" in text
    assert removed >= 8
    statements = dict((s, ids) for s, ids in cited)
    assert statements["The application takes customer orders (BR-0001). It runs every night."] == [
        "EV-java-0005", "EV-jsp-0003"]
    assert statements["Orders above 100 units need approval."] == ["EV-java-0012"]
    removed_statement = next(s for s in statements if s.startswith(pl.REMOVED))
    assert "`src/main/webapp/order.jsp:4`" in removed_statement and statements[removed_statement] == ["EV-jsp-0007"]


def test_a_section_emptied_by_the_guard_says_so():
    text, _, _ = pl.business_only("## Business Rules by Capability\n- `a > 5` in `X.java:3` (EV-java-0001)\n"
                                   "## Open Questions\n- Who approves refunds?\n")
    assert "## Business Rules by Capability\n\n" + pl.EMPTIED in text
    assert "## Open Questions\n- Who approves refunds?" in text


def test_names_become_words():
    assert pl.humanize("OrderService") == "Order Service"
    assert pl.humanize("orderTotal") == "order total"
    assert pl.humanize("PENDING_APPROVAL") == "Pending Approval"
    assert pl.humanize("ROLE_ADMIN") == "Admin"
    assert pl.humanize("HTTPClient") == "HTTP Client"


def test_the_same_text_always_gives_the_same_brd():
    assert pl.business_only(PO_OUTPUT) == pl.business_only(PO_OUTPUT)
    once = pl.business_only(PO_OUTPUT)[0]
    assert pl.business_only(once)[0] == once                                   # idempotent


def _raw(cid, statement, capability="", rtype="validation", basis="explicit", confidence="high",
         condition="", outcome="", area="claims", symbol="ClaimService.approve"):
    return {"statement": statement, "capability": capability, "type": rtype, "condition": condition,
            "outcome": outcome, "basis": basis, "confidence": confidence, "area": area, "flags": [],
            "sources": [{"candidate": cid, "path": f"src/{cid}.java", "start": 1, "end": 5, "symbol": symbol}]}


def _finalized(raw_rules):
    ledger = {"candidates": {r["sources"][0]["candidate"]: {} for r in raw_rules}, "raw_rules": raw_rules,
              "rules": []}
    rules_ledger.finalize(ledger, "/nonexistent", [])
    return ledger


def test_every_rule_is_a_table_row_with_its_scenarios_by_capability():
    claims = _raw("C1", "A claim may be auto-approved only when the amount is below the configured threshold and "
                        "no fraud flag exists.", "Claims")
    claims.update(use_cases=["A claim of 200 under a 500 threshold with no fraud flag is approved at once.",
                             "A corrected claim of 300 is approved at once."],
                  negative_scenarios=["A claim with a fraud flag waits for an adjuster.",
                                      "A claim of 800 waits for an adjuster."],
                  edge_cases=["A claim of exactly 500 is not auto-approved.", "A claim with no amount is rejected."])
    ledger = _finalized([
        claims,
        _raw("C2", "Only managers can reopen a closed claim.", "Claims", rtype="authorization", basis="inferred",
             confidence="medium"),
        _raw("C3", "An order with more than 50 items is rejected.", "Order entry"),
    ])
    assert [r["id"] for r in ledger["rules"]] == ["BR-CLAIMS-001", "BR-CLAIMS-002", "BR-ORDER-ENTRY-001"]
    md = rules_ledger.business_rules_markdown(ledger, 100)
    assert md.startswith("## Business Rules by Capability")
    assert md.index("### Claims") < md.index("### Order entry")
    header = ("| Rule ID | Business rule | Use cases | Negative scenarios | Edge cases | Observed or inferred "
              "| Confidence |")
    assert md.count(header) == 2
    assert ("| BR-CLAIMS-001 | A claim may be auto-approved only when the amount is below the configured threshold "
            "and no fraud flag exists. | • A claim of 200 under a 500 threshold with no fraud flag is approved at once. "
            "• A corrected claim of 300 is approved at once. | • A claim with a fraud flag waits for an adjuster. "
            "• A claim of 800 waits for an adjuster. | • A claim of exactly 500 is not auto-approved. • A claim "
            "with no amount is rejected. | Observed | High |") in md
    assert ("| BR-CLAIMS-002 | Only managers can reopen a closed claim. | None identified | None identified "
            "| None identified | Inferred | Medium |") in md
    # No reference to the audit file, no code, no locations.
    assert "evidence" not in md.lower() and ".java" not in md and "`" not in md and "Source" not in md


def test_scenarios_are_cleaned_merged_and_sent_back_when_worded_in_code():
    from agents.shared.rule_candidates import Candidate
    rule = _raw("C1", "Orders above 100 units need a manager's approval.", "Orders")
    rule.update(use_cases=["An order of 20 units goes straight through."],
                negative_scenarios=["`OrderService.hold()` is called.", "An order of 500 units waits for a manager."],
                edge_cases=["An order of exactly 100 units needs no approval.", "`qty == null`"])
    twin = _raw("C2", "Orders above 100 units need a manager's approval.", "Orders")
    twin.update(use_cases=["An order of 20 units goes straight through.", "A repeat order of 50 units goes through."],
                edge_cases=["An order with no quantity is rejected."])
    ledger = _finalized([rule, twin])
    [merged] = ledger["rules"]
    assert merged["use_cases"] == ["An order of 20 units goes straight through.",
                                   "A repeat order of 50 units goes through."]            # merged, no duplicates
    assert merged["negative_scenarios"] == ["An order of 500 units waits for a manager."]   # code-only entry gone
    assert merged["edge_cases"] == ["An order of exactly 100 units needs no approval.",
                                    "An order with no quantity is rejected."]
    c = Candidate(id="C00001", path="src/A.java", start=1, end=3, kind="method", symbol="A.f", language="Java",
                  parser="tree-sitter", source="1| if (x > 5) return;", signals=["if"])
    led = {"candidates": {"C00001": {"status": "pending"}}, "raw_rules": [], "rules": []}
    rules_ledger.apply_answer([c], [{"candidate": "C00001", "rules": [
        {"statement": "Requests with more than five items are refused.", "lines": "1",
         "use_case": "A request of three items is accepted.",                    # one text still accepted
         "negative_scenarios": ["Throws `TooManyItems`.", "A request of nine items is refused."],
         "edge_cases": "Exactly five items pass; `x == 6` fails"}]}], led)
    raw = led["raw_rules"][0]
    assert raw["use_cases"] == ["A request of three items is accepted."]
    assert raw["edge_cases"] == ["Exactly five items pass", "`x == 6` fails"]
    reasons = rules_ledger.needs_rewording([c], led)["C00001"]
    assert "not plain English: “Throws `TooManyItems`.”" in reasons and "not plain English: “`x == 6` fails”" in reasons
    # Nine is not in this code (it compares with 5): the scenario cannot be traced.
    assert any("“A request of nine items is refused.”: the value 9 does not appear in the code" in r for r in reasons)


def test_a_technical_statement_is_reworded_never_referred_elsewhere():
    ledger = _finalized([
        # Code in the statement, a plain sentence once it is taken out.
        _raw("C1", "Orders above 100 units need a manager's approval in `OrderService.approve()`.", "Orders"),
        # Statement unusable; the condition and outcome are plain.
        _raw("C2", "Applies `qty > 100`.", "Orders", condition="the order has more than 100 units",
             outcome="the order is held for approval"),
        # Nothing usable at all.
        _raw("C3", "The implementation applies `<div th:if=\"${param.error}\">`.", "Access", symbol="LoginPage.render"),
    ])
    by_cid = {r["sources"][0]["candidate"]: r for r in ledger["rules"]}
    assert by_cid["C1"]["statement"] == "Orders above 100 units need a manager's approval."
    assert by_cid["C2"]["statement"] == "When the order has more than 100 units, the order is held for approval."
    assert by_cid["C3"]["statement"] == ("The system applies a validation rule in login page render; its business "
                                         "meaning is to be confirmed with the business owner.")
    assert (by_cid["C3"]["basis"], by_cid["C3"]["confidence"]) == ("inferred", "low")
    assert by_cid["C1"]["statement_original"].endswith("`OrderService.approve()`.")   # kept for the audit file
    md = rules_ledger.business_rules_markdown(ledger, 100)
    assert "evidence" not in md.lower() and "technical terms" not in md and pl.is_plain(md.replace("“", ""))


def test_a_rule_worded_in_code_is_sent_back_once_with_its_wording():
    from agents.shared.rule_candidates import Candidate
    c = Candidate(id="C00001", path="src/A.java", start=1, end=3, kind="method", symbol="A.f", language="Java", parser="tree-sitter",
                  source="1| if (x > 5) return;", signals=["if"])
    ledger = {"candidates": {"C00001": {"status": "pending"}}, "raw_rules": [], "rules": []}
    rules_ledger.apply_answer([c], [{"candidate": "C00001", "rules": [
        {"statement": "Returns early when `x > 5`.", "lines": "1"}]}], ledger)
    reword = rules_ledger.needs_rewording([c], ledger)
    assert reword == {"C00001": ["not plain English: “Returns early when `x > 5`.”"]}
    request = rules_ledger.render_batch([c], reword)
    assert "Restate from this code, in plain English" in request
    assert "- not plain English: “Returns early when `x > 5`.”" in request
    rules_ledger.apply_answer([c], [{"candidate": "C00001", "rules": [
        {"statement": "A request with more than five items is not processed.", "capability": "Requests",
         "lines": "1"}]}], ledger, replace=True)
    assert [r["statement"] for r in ledger["raw_rules"]] == ["A request with more than five items is not processed."]
    assert rules_ledger.needs_rewording([c], ledger) == {}
    # A restatement that gives no rules leaves the earlier answer standing.
    rules_ledger.apply_answer([c], [{"candidate": "C00001", "rules": [], "technical": "x"}], ledger, replace=True)
    assert len(ledger["raw_rules"]) == 1 and ledger["candidates"]["C00001"]["status"] == "rule"


def test_the_rules_section_takes_its_place_in_the_brd():
    po = "## Executive Summary\nx\n## Business Scenarios\n1. y\n## Business Data\nz\n## Open Questions\n- q\n"
    section = "## Business Rules by Capability\n\n### Claims\n\n- **Rule ID:** BR-CLAIMS-001"
    placed = pl.place_section(po, section, "## Business Rules by Capability")
    assert placed.index("## Business Scenarios") < placed.index("## Business Rules by Capability") \
        < placed.index("## Business Data")
    # A section the writer produced anyway is replaced, not duplicated.
    written = po.replace("## Business Data", "## Business Rules by Capability\n- `x > 5`\n## Business Data")
    replaced = pl.place_section(written, section, "## Business Rules by Capability")
    assert replaced.count("## Business Rules by Capability") == 1 and "x > 5" not in replaced


def test_the_evidence_file_traces_each_statement_to_its_evidence():
    packs = [("java", "Java application", "### Business Behaviour\n- [EV-java-0012] `OrderService.java:40` — "
              "decision: `qty > 100`\n")]
    md = ep.evidence_markdown("Technology Stack Discovery", "## Detected Technology Stacks\n| java |",
                              [("Orders above 100 units need approval.", ["EV-java-0012", "EV-java-0999"])],
                              packs, "## Business Rules Catalog\n| BR-0001 | `src/Order.java:9-11` |",
                              "## Evidence Check\nok", "only 10 of 20 files")
    assert md.startswith("# Evidence — Technology Stack Discovery")
    assert "> ⚠️ **Incomplete repository.** only 10 of 20 files" in md
    assert "- **Orders above 100 units need approval.**" in md
    assert "  - `EV-java-0012` — `OrderService.java:40` — decision: `qty > 100`" in md
    assert "  - `EV-java-0999` — **no such evidence item** (unverified)" in md
    assert md.index("## BRD Traceability") < md.index("## Detected Technology Stacks") \
        < md.index("## Business Rules Catalog — Code Locations and Tests") < md.index("## Evidence Check")


def test_the_evidence_file_downloads_but_only_through_the_api(tmp_path):
    sid = _session(PRESCAN)
    with TestClient(main.app) as client:
        assert client.get(f"/api/sessions/{sid}/download/evidence").status_code == 404
    evidence = tmp_path / main.EVIDENCE_FILE
    evidence.write_text("# Evidence — x\n\n## BRD Traceability\n")
    asyncio.run(main._update_state(sid, {"evidence_path": str(evidence)}))
    with TestClient(main.app) as client:
        md = client.get(f"/api/sessions/{sid}/download/evidence")
        word = client.get(f"/api/sessions/{sid}/download/evidence?format=docx")
    assert md.status_code == 200 and md.text.startswith("# Evidence")
    assert word.status_code == 200 and word.headers["content-disposition"].endswith('.docx"')
