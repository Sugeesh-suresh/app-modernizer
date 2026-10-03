"""
Evidence packs: one fact base with stable ids, split into the Product Owner's
and the Enterprise Architect's views, and a check that every id the documents
cite exists.
"""
from agents.shared import evidence_pack as ep

PACK = """## Unit 1: src
### Components
- `A.java` — order service
  with a continuation line
- [EV-9] `B.java` — dao (the model's own id is replaced)
### Business Behaviour
- Orders over 50 items are rejected (`A.java:9`)
### Actors & Roles
None found.
### Tests
- `ATest.java` covers rejection
## Unit 2: web
### Components
- `index.jsp` — order page
### Unit Limitations
- could not read `C.java`
Prose outside any section stays as it is.
"""


def test_ids_are_assigned_by_the_pipeline_in_order_and_are_stable():
    numbered = ep.assign_ids(PACK, "tibco-ems")
    assert "- [EV-tibco-ems-0001] `A.java` — order service\n  with a continuation line" in numbered
    assert "- [EV-tibco-ems-0002] `B.java`" in numbered and "[EV-9]" not in numbered
    assert "- [EV-tibco-ems-0006] could not read" in numbered               # "Unit Limitations" -> Limitations
    assert "None found." in numbered and "[EV-tibco-ems-0007]" not in numbered
    assert ep.assign_ids(numbered, "tibco-ems") == numbered                  # idempotent
    assert ep.ids(numbered) == {f"EV-tibco-ems-{i:04d}" for i in range(1, 7)}


def test_each_writer_gets_its_own_sections_from_every_unit():
    numbered = ep.assign_ids(PACK, "java")
    [po] = ep.view([("java", "Java application", numbered)], ep.PO_SECTIONS)
    [ea] = ep.view([("java", "Java application", numbered)], ep.EA_SECTIONS)
    assert po.startswith("## Java application (`java`)")
    assert "Orders over 50 items" in po and "`A.java` — order service" not in po and "ATest" not in po
    assert "`A.java` — order service" in ea and "`index.jsp`" in ea and "ATest" in ea and "Orders over" not in ea
    assert "could not read" in po and "could not read" in ea                 # both see the limitations


def test_a_long_piece_is_cut_at_item_boundaries():
    piece = "## S (`s`)\n\n### Components\n" + "\n".join(f"- [EV-s-{i:04d}] " + "x" * 50 for i in range(1, 41))
    parts = ep.split_piece(piece, 600)
    assert len(parts) > 1 and all(len(p) <= 700 for p in parts)
    assert all(line.startswith(("- [EV-", "## ", "### ")) or not line.strip()
               for p in parts for line in p.splitlines())
    assert set(ep.EV_ID.findall("\n".join(parts))) == {f"EV-s-{i:04d}" for i in range(1, 41)}


def test_the_rules_brief_lists_rules_by_id_and_says_when_it_stops():
    ledger = {"rules": [{"id": f"BR-{i:04d}", "area": "orders" if i < 3 else "billing", "type": "validation",
                         "basis": "explicit", "statement": f"rule {i}"} for i in range(1, 6)]}
    brief = ep.rules_index(ledger, 10_000)
    assert "5 rules in 2 areas" in brief and "- BR-0001 (validation, explicit): rule 1" in brief
    short = ep.rules_index(ledger, 260)
    assert "more rules not listed here" in short
    assert ep.rules_index(None, 100) == "No business-rules catalog was produced for this run."


def test_the_check_reports_citations_that_match_nothing():
    ids = {"EV-java-0001", "EV-java-0002", "EV-java-0003"}
    brd = ep.check("Orders are checked (EV-java-0001, BR-0001). Refunds (EV-java-0042).", ids, {"BR-0001"})
    spec = ep.check("Service (EV-java-0002). Rule BR-0099.", ids, {"BR-0001"})
    md = ep.check_markdown(brd, spec, ids)
    assert brd["unknown_evidence"] == ["EV-java-0042"] and spec["unknown_rules"] == ["BR-0099"]
    assert "**Cited by neither:** 1" in md
    assert "- BRD: `EV-java-0042`" in md and "- Technical Specification: `BR-0099`" in md


def test_the_architects_answer_splits_into_specification_and_tests():
    assert ep.split_spec("<!-- SECTION: TECHNICAL_SPECIFICATION -->\nspec\n<!-- SECTION: TEST_INVENTORY -->\n"
                         "tests\n<!-- SECTION: END -->\ntrailing") == ("spec", "tests")
    assert ep.split_spec("only a spec") == ("only a spec", "")
