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


LEDGER = {"rules": [
    {"id": "BR-0001", "type": "validation", "basis": "explicit", "area": "orders",
     "statement": "An order with more than 50 items is rejected.", "condition": "the order has more than 50 items",
     "outcome": "the order is rejected", "sources": [{"path": "src/Order.java", "start": 9, "end": 11}]},
    {"id": "BR-0002", "type": "authorization", "basis": "inferred", "area": "web",
     "statement": "Only managers see the refund screen in `RefundController.java`.", "condition": "", "outcome": "",
     "sources": [{"path": "src/RefundController.java", "start": 3, "end": 4}]},
    {"id": "BR-0003", "type": "validation", "basis": "explicit", "area": "web",
     "statement": "The implementation applies `<div th:if=\"${param.error}\">`.", "condition": "`x > 5`",
     "outcome": "", "sources": [{"path": "login.html", "start": 4, "end": 4}]},
]}


def test_the_brd_catalog_is_in_business_words_by_kind_of_rule():
    md = rules_ledger.business_catalog_markdown(LEDGER, 100)
    assert md.startswith("## Business Rules Catalog") and pl.is_plain(md.replace("BR-", "BR "))
    assert md.index("### Access and permissions") < md.index("### Validation")
    assert "| BR-0001 | An order with more than 50 items is rejected. | the order has more than 50 items | " \
           "the order is rejected | Stated in the system |" in md
    assert "| BR-0002 | Only managers see the refund screen. | — | — | Inferred — confirm with the business |" in md
    assert f"| BR-0003 | {rules_ledger.TECHNICAL_ONLY} | — | — |" in md
    assert "Source" not in md and "Tests" not in md and ".java" not in md


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
