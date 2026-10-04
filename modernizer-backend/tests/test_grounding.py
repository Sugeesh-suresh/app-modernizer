"""Grounding: what the business documents state must be traceable to the
repository's code — evidence items, business rules, their scenarios and the
BRD's statements are all checked, deterministically."""
from pathlib import Path

from agents.shared import grounding as g
from agents.shared import rules_ledger

CODE = """  10| public boolean autoApprove(Claim claim) {
  11|     if (claim.getAmount() == null) throw new IllegalArgumentException("Amount is required");
  12|     if (claim.isFraudFlag()) return false;
  13|     if (claim.getAmount().compareTo(threshold) < 0 && claim.getAmount().intValue() < 500) return true;
  14|     return false;
  15| }"""


# ── values, terms, kinds ────────────────────────────────────────────────────

def test_numbers_must_come_from_the_code():
    code = g.strip_line_numbers(CODE)
    assert g.unsupported_values("A claim under 500 is approved at once.", code) == []
    assert g.unsupported_values("A claim of exactly 501 is not auto-approved.", code) == []   # boundary arithmetic
    assert g.unsupported_values("A claim of one item is fine.", code) == []                  # ordinary language
    assert g.unsupported_values("Claims under 750 are approved.", code) == \
        ["the value 750 does not appear in the code"]
    assert g.unsupported_values("Claims under fifty are approved.", code) == \
        ["the value 50 does not appear in the code"]                                       # numbers in words too
    assert g.unsupported_values("A 10% fee applies.", "rate = 0.10;") == []                  # percent ↔ fraction
    assert g.unsupported_values("Orders over 1,000 need approval.", "if (total > 1000)") == []


def test_quoted_messages_must_come_from_the_code_or_its_message_files():
    code = g.strip_line_numbers(CODE)
    assert g.unsupported_values("The user is told “Amount is required”.", code) == []
    assert g.unsupported_values("The user is told “Please enter an amount”.", code) == \
        ["the text “Please enter an amount” does not appear in the code"]
    assert g.unsupported_values("The user sees “Claim limit exceeded”.", code,
                                extra_text="claim.limit=Claim limit exceeded") == []


def test_a_statement_must_relate_to_the_code_it_came_from():
    code = g.strip_line_numbers(CODE)
    assert g.unrelated_terms("A claim flagged for fraud is never approved automatically.", code) == []
    assert g.unrelated_terms("Loyalty points expire after inactivity for premium members.", code) == \
        ["none of its key terms (expire, inactivity, loyalty, members, points, premium) relate to the code"]


def test_a_scenario_must_match_a_check_the_code_makes():
    code = g.strip_line_numbers(CODE)
    assert g.missing_behaviour("A claim with no amount is rejected.", code) == []            # == null
    assert g.missing_behaviour("A claim of exactly 500 is not auto-approved.", code) == []    # < 500
    assert g.missing_behaviour("A claim submitted by a user without the adjuster role is refused.", code) == \
        ["it describes an access or role check, which the code does not check"]
    assert g.missing_behaviour("A claim older than 30 days is rejected.", code) == \
        ["it describes a date, time or schedule, which the code does not check"]


# ── rules ───────────────────────────────────────────────────────────────────

def _raw(statement, **scenarios):
    rule = {"statement": statement, "capability": "Claims", "type": "eligibility", "condition": "", "outcome": "",
            "basis": "explicit", "confidence": "high", "area": "claims", "flags": [],
            "use_cases": scenarios.get("use_cases", []), "negative_scenarios": scenarios.get("negative_scenarios", []),
            "edge_cases": scenarios.get("edge_cases", []),
            "sources": [{"candidate": "C1", "path": "src/ClaimService.java", "start": 10, "end": 15,
                         "symbol": "ClaimService.autoApprove"}]}
    rule["grounding"] = g.check_rule(rule, CODE)
    return rule


def _finalize(*raws):
    ledger = {"candidates": {"C1": {}}, "raw_rules": list(raws), "rules": []}
    rules_ledger.finalize(ledger, "/nonexistent", [])
    return ledger


def test_an_untraceable_rule_never_reaches_the_brd():
    made_up = _raw("Loyalty points expire after inactivity for premium members.")
    real = _raw("A claim is auto-approved only when its amount is below 500 and it has no fraud flag.",
                use_cases=["A claim below 500 with no fraud flag is approved at once.",
                           "A claim of 200 with no fraud flag is approved at once."],      # 200: an invented example
                negative_scenarios=["A claim with a fraud flag is not auto-approved.",
                                    "A claim submitted by a user without the adjuster role is refused."],
                edge_cases=["A claim of exactly 500 is not auto-approved.", "A claim with no amount is rejected.",
                            "A claim older than 30 days is rejected."])
    ledger = _finalize(made_up, real)
    by_statement = {r["statement"]: r for r in ledger["rules"]}
    assert by_statement[made_up["statement"]]["verified"] is False
    assert by_statement[made_up["statement"]]["id"].startswith("UV-")
    kept = by_statement[real["statement"]]
    assert kept["verified"] and kept["id"] == "BR-CLAIMS-001"
    assert kept["negative_scenarios"] == ["A claim with a fraud flag is not auto-approved."]
    assert kept["edge_cases"] == ["A claim of exactly 500 is not auto-approved.", "A claim with no amount is rejected."]
    assert kept["use_cases"] == ["A claim below 500 with no fraud flag is approved at once."]
    assert [d["text"] for d in kept["dropped"]] == ["A claim of 200 with no fraud flag is approved at once.",
                                                    "A claim submitted by a user without the adjuster role is refused.",
                                                    "A claim older than 30 days is rejected."]
    brd = rules_ledger.business_rules_markdown(ledger, 100)
    assert "Loyalty" not in brd and "adjuster role" not in brd and "30 days" not in brd
    assert "BR-CLAIMS-001" in brd
    report = g.report_markdown([], ledger, [])
    assert "Loyalty points expire" in report and "adjuster role is refused" in report and "30 days" in report


def test_the_same_rule_found_elsewhere_in_the_code_makes_it_traceable():
    unsupported = _raw("A claim is auto-approved only when its amount is below 750.")
    supported = dict(unsupported, grounding={"statement": [], "use_cases": [], "negative_scenarios": [],
                                             "edge_cases": [], "condition": [], "outcome": []},
                     sources=[{"candidate": "C2", "path": "src/Other.java", "start": 1, "end": 3, "symbol": "O.f"}])
    ledger = {"candidates": {"C1": {}, "C2": {}}, "raw_rules": [unsupported, supported], "rules": []}
    rules_ledger.finalize(ledger, "/nonexistent", [])
    [rule] = ledger["rules"]
    assert rule["verified"] and rule["id"] == "BR-CLAIMS-001" and len(rule["sources"]) == 2


def test_the_restate_request_says_what_could_not_be_traced():
    from agents.shared.rule_candidates import Candidate
    c = Candidate(id="C00001", path="src/ClaimService.java", start=10, end=15, kind="method",
                  symbol="ClaimService.autoApprove", language="Java", parser="tree-sitter", source=CODE)
    ledger = {"candidates": {"C00001": {"status": "pending"}}, "raw_rules": [], "rules": []}
    rules_ledger.apply_answer([c], [{"candidate": "C00001", "rules": [{
        "statement": "Claims under 750 are approved automatically when no fraud flag is set.", "lines": "13",
        "edge_cases": ["A claim older than 30 days is rejected."]}]}], ledger)
    reasons = rules_ledger.needs_rewording([c], ledger)["C00001"]
    assert any("the value 750 does not appear in the code" in r for r in reasons)
    assert any("date, time or schedule" in r for r in reasons)
    assert "Leave out any case the code does not contain" in rules_ledger.render_batch([c], {"C00001": reasons})


# ── evidence items ──────────────────────────────────────────────────────────

def _repo(tmp_path: Path) -> str:
    (tmp_path / "src/main/java/com/acme").mkdir(parents=True)
    # The code at the lines CODE numbers it (10-15), as the evidence cites it.
    (tmp_path / "src/main/java/com/acme/ClaimService.java").write_text("\n" * 9 + g.strip_line_numbers(CODE) + "\n")
    (tmp_path / "pom.xml").write_text("<project><password>s3cret</password></project>\n")
    return str(tmp_path)


def test_evidence_items_must_cite_real_files_lines_and_code(tmp_path):
    ws = _repo(tmp_path)
    pack = "\n".join([
        "### Business Behaviour",
        "- [EV-java-0001] `src/main/java/com/acme/ClaimService.java:12` — decision: `if (claim.isFraudFlag()) return false;`",
        "- [EV-java-0002] `ClaimService.java:13` — `claim.getAmount().intValue() < 500`",          # path ending
        "- [EV-java-0003] `src/main/java/com/acme/RefundService.java:5` — refunds need approval",   # no such file
        "- [EV-java-0004] `src/main/java/com/acme/ClaimService.java:99` — something",              # no such line
        "- [EV-java-0005] `ClaimService.java:11` — `if (claim.getAmount() > 750)`",                 # not in the file
        "  continued detail of the withheld item",
        "- [EV-java-0006] Claims are approved by managers.",                                         # cites nothing
        "### Integrations & Configuration",
        "- [EV-java-0007] `pom.xml:1` — `<password>[REDACTED]</password>`",                         # redacted: fine
        "### Limitations",
        "- [EV-java-0008] Did not read the generated sources.",                                      # exempt
    ])
    kept, rejected = g.verify_pack(pack, ws)
    assert [i for i, _ in rejected] == ["EV-java-0003", "EV-java-0004", "EV-java-0005", "EV-java-0006"]
    reasons = dict(rejected)
    assert "not in the repository" in reasons["EV-java-0003"] and "has no line 99" in reasons["EV-java-0004"]
    assert "is not in the file it cites" in reasons["EV-java-0005"] and "cites no file" in reasons["EV-java-0006"]
    assert "continued detail" not in kept
    for kept_id in ("EV-java-0001", "EV-java-0002", "EV-java-0007", "EV-java-0008"):
        assert kept_id in kept


# ── BRD statements ──────────────────────────────────────────────────────────

EVIDENCE = {"EV-java-0001": "`ClaimService.java:12` — a claim with a fraud flag is never auto-approved",
            "EV-java-0002": "`ClaimService.java:13` — claims below 500 are approved"}
RULES = {"BR-CLAIMS-001": "A claim is auto-approved only when its amount is below 500 and it has no fraud flag."}


def test_brd_statements_must_cite_what_they_rest_on_and_match_it():
    brd = """## Executive Summary
The system approves small claims automatically for 3 confirmed parts of the system.
## Business Capabilities
- Claims below 500 are approved at once (EV-java-0002, BR-CLAIMS-001).
- Claims below 900 are approved at once (EV-java-0002).
- Refunds are paid within 5 days.
- Fraud checks use a cited item that does not exist (EV-java-0099).
## Business Scenarios
1. A customer submits a claim of 200.
2. The claim has no fraud flag, so it is approved (EV-java-0001).
## Business Data
- Loyalty accounts track points.
## Open Questions
- Are refunds above 1,000 reviewed by finance?
"""
    kept, removed = g.check_brd(brd, EVIDENCE, RULES, allowed_numbers={3.0})
    assert "Claims below 500 are approved at once" in kept
    assert "1. A customer submits a claim of 200." not in kept or "approved (EV-java-0001)" in kept
    assert "Are refunds above 1,000 reviewed by finance?" in kept                 # a question, not a claim
    assert "for 3 confirmed parts" in kept                                        # the stack count is allowed
    gone = {s: r for s, r in removed}
    assert gone["- Claims below 900 are approved at once (EV-java-0002)."] == \
        "the value 900 does not appear in the code"
    assert "cites no evidence" in gone["- Refunds are paid within 5 days."]
    assert "cites no evidence" in gone["- Fraud checks use a cited item that does not exist (EV-java-0099)."]
    assert "## Business Data\n\n_Not yet described in business terms" in kept      # emptied section says so


def test_a_scenario_list_is_one_statement():
    brd = "## Business Scenarios\n1. A customer submits a claim of 200.\n2. It is approved (EV-java-0002).\n"
    kept, removed = g.check_brd(brd, EVIDENCE, RULES)
    # 200 is not in the cited evidence, so the whole scenario goes — no half scenario is left.
    assert removed and "1. A customer submits" not in kept and "2. It is approved" not in kept
    brd = "## Business Scenarios\n1. A customer submits a claim below 500.\n2. It is approved (EV-java-0002).\n"
    kept, removed = g.check_brd(brd, EVIDENCE, RULES)
    assert not removed and "1. A customer submits a claim below 500." in kept
