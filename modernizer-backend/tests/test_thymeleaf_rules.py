"""
A Spring MVC + Thymeleaf application holding its rules where such applications do
(tests/fixtures/thymeleaf-rules): template conditions, lists, styling and state,
formatting, forms and their errors, fragments, bean calls, an inline script, bean
validation with a custom constraint, a custom Spring validator, BindingResult,
@ControllerAdvice model data, an interceptor, an @ExceptionHandler, session and
flash state — and references to rules the repository does not contain.

Every decision found must be accounted for: named by a rule, dismissed with a
reason, or reported as unaccounted. All of it is deterministic (no model).
"""
import asyncio
import csv
import io
import json
import re
import shutil
from pathlib import Path

import pytest

from agents import config
import main
from agents.shared import external_rules, rules_ledger
from agents.shared import rule_candidates as rc

pytestmark = pytest.mark.skipif("java" not in rc._PARSERS or "javascript" not in rc._PARSERS,
                                reason="tree-sitter grammars not installed")

REPO = Path(__file__).parent / "fixtures" / "thymeleaf-rules"
T = "src/main/resources/templates/"
J = "src/main/java/com/acme/shop/"


@pytest.fixture(scope="module")
def scanned():
    return rc.scan(str(REPO))


def _points(scanned, path: str) -> list[tuple]:
    return [(d["line"], d["kind"], d["text"]) for c in scanned.candidates if c.path == path for d in c.decisions]


def _candidate(scanned, symbol: str):
    return next(c for c in scanned.candidates if c.symbol == symbol)


def test_every_template_decision_is_a_point_of_its_own_kind(scanned):
    listing = _points(scanned, T + "orders/list.html")
    kinds = [(line, kind) for line, kind, _ in listing if kind != "if"]
    assert kinds == [(4, "visibility"), (6, "list"), (6, "conditional styling"), (7, "formatting"),
                     (8, "formatting"), (9, "case"), (9, "case"), (9, "case"), (10, "conditional state"),
                     (11, "server call"), (12, "ternary")]
    texts = {text for _, _, text in listing}
    assert "#numbers.formatDecimal(o.total, 1, 2)" in texts and "#temporals.format(o.placedAt, 'dd/MM/yyyy')" in texts
    assert "${@pricing.discountFor(o)}" in texts and "th:classappend=\"${o.status == 'OVERDUE'} ? 'row-danger'\"" in texts
    form = _points(scanned, T + "orders/form.html")
    assert [(line, kind) for line, kind, _ in form] == [(3, "form field"), (4, "visibility"), (4, "form errors"),
                                                         (5, "form field")]


def test_a_fragment_says_which_pages_include_it_and_keeps_its_access_rule(scanned):
    header = next(c for c in scanned.candidates if c.path == T + "fragments/header.html")
    assert "included by: " + T + "orders/list.html" in header.signals
    assert [(line, kind) for line, kind, _ in _points(scanned, header.path)] == [(3, "access rule"), (4, "visibility")]


def test_an_inline_script_is_parsed_as_javascript_at_its_own_lines(scanned):
    script = _candidate(scanned, "<script> checkQuantity")
    assert (script.path, script.start, script.end) == (T + "orders/list.html", 18, 21)
    assert "inline script" in script.signals and [d["text"] for d in script.decisions] == ["if (q > limit)"]


def test_validation_custom_constraints_and_validators_are_candidates(scanned):
    form = _candidate(scanned, "com.acme.shop.web.OrderForm")
    assert form.kind == "validation" and form.signals == ["@NotNull", "@Max", "@Email", "@ValidSku"]
    assert len(form.decisions) == 4                       # one per constraint, the custom one included
    sku = _candidate(scanned, "com.acme.shop.validation.SkuValidator.isValid")
    assert sku.kind == "validator" and sku.status == "pending" and len(sku.decisions) == 1
    validator = _candidate(scanned, "com.acme.shop.validation.OrderFormValidator.validate")
    assert validator.kind == "validator" and "BindingResult" in validator.signals
    assert [d["kind"] for d in validator.decisions] == ["if", "validation outcome"]


def test_controller_advice_interceptor_error_mapping_and_session_state_are_candidates(scanned):
    kinds = {c.symbol: c.kind for c in scanned.candidates}
    assert kinds["com.acme.shop.web.GlobalModel.cartCount"] == "global-model"
    assert kinds["com.acme.shop.web.GlobalModel.trim"] == "global-model"
    assert kinds["com.acme.shop.web.MaintenanceInterceptor.preHandle"] == "interceptor"
    assert kinds["com.acme.shop.web.OrderController.outOfStock"] == "error-mapping"
    assert kinds["com.acme.shop.web.OrderController"] == "session-state"          # @SessionAttributes
    place = _candidate(scanned, "com.acme.shop.web.OrderController.place")
    assert place.kind == "session-state" and "BindingResult" in place.signals
    assert [d["kind"] for d in place.decisions] == ["if", "validation outcome", "session", "session"]
    advice = _candidate(scanned, "com.acme.shop.web.OrderController.outOfStock")
    assert [d["kind"] for d in advice.decisions] == ["model / response"]


def test_every_candidate_has_decision_points_with_unique_ids(scanned):
    ids = [d["id"] for c in scanned.candidates for d in c.decisions]
    assert all(c.decisions for c in scanned.candidates)
    assert len(ids) == len(set(ids)) and all(re.fullmatch(r"DP-\d{5}", i) for i in ids)


def test_references_outside_the_repository_are_listed_with_where_they_are_used():
    rows = {(r["category"], r["reference"]): r["where"] for r in external_rules.scan(str(REPO))}
    assert rows == {
        ("Message texts not in the repository", "order.email.invalid"): [J + "web/OrderForm.java:7"],
        ("Message texts not in the repository", "order.email.required.bulk"): [J + "validation/OrderFormValidator.java:7"],
        ("Message texts not in the repository", "order.legacy.notice"): [T + "orders/list.html:15"],
        ("Message texts not in the repository", "sku.invalid"): [J + "validation/ValidSku.java:6"],
        ("External services", 'name = "shipping", url = "${shipping.url}"'): [J + "web/ShippingClient.java:2"],
        ("Database tables with no definition here", "order_audit"): [J + "web/OrderController.java:20"],
        ("Stored procedures and functions not in the repository", "archive_order"): [J + "web/OrderController.java:23"],
        ("Logic evaluated at run time", "SpEL expression evaluated at run time"): [J + "web/PromoConfig.java:8"],
        ("Logic evaluated at run time", "SpEL value computed at run time"): [J + "web/PromoConfig.java:5"],
        ("Feature switches", 'name = "promo.enabled", havingValue = "true"'): [J + "web/PromoConfig.java:3"],
    }
    md = external_rules.to_markdown(external_rules.scan(str(REPO)))
    assert md.startswith(external_rules.HEADING) and "### Message texts not in the repository (4)" in md
    assert "| `archive_order` | stored routine | `" + J + "web/OrderController.java:23` |" in md


def test_defined_tables_keys_and_routines_are_not_listed(tmp_path):
    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "s.sql").write_text("CREATE TABLE audit (id INT);\nCREATE OR REPLACE PROCEDURE purge AS BEGIN NULL; END;\n")
    (tmp_path / "A.java").write_text('@Entity class OrderLine {}\nclass A { String q = "SELECT * FROM audit a JOIN '
                                     'order_line l ON 1=1"; void p() { jdbc.call("{call purge()}"); }\n'
                                     '  @Value("#{systemProperties.x}") String v; }\n')
    rows = external_rules.scan(str(tmp_path))
    assert [(r["category"], r["reference"]) for r in rows] == [("Logic evaluated at run time",
                                                                "SpEL value computed at run time")]
    assert external_rules.to_markdown([]).endswith("Nothing found.")


# ---------------------------------------------------------------------------
# Accounting for every decision point
# ---------------------------------------------------------------------------

def _ledger(scanned, symbols):
    batch = [c for c in scanned.candidates if c.symbol in symbols]
    return batch, rules_ledger.new_ledger(batch)


def test_a_point_no_rule_names_and_no_dismissal_covers_is_asked_for_again(scanned):
    batch, ledger = _ledger(scanned, {"com.acme.shop.web.OrderController.place"})
    c = batch[0]
    ids = [d["id"] for d in c.decisions]
    rules_ledger.apply_answer(batch, [{"candidate": c.id, "rules": [
        {"statement": "An order with invalid input goes back to the form.", "lines": "7-9",
         "decision_points": [ids[0], ids[1], "DP-99999"]}]}], ledger)
    assert ledger["raw_rules"][0]["decision_points"] == ids[:2]               # another candidate's id is dropped
    left = rules_ledger.unaccounted(batch, ledger)
    assert left == {c.id: ids[2:]}
    prompt = rules_ledger.render_batch(batch, account=left)
    assert "Account for these decision points" in prompt and ids[0] not in prompt
    assert all(f"- {i} line" in prompt for i in ids[2:])
    rules_ledger.apply_answer(batch, [{"candidate": c.id, "rules": [
        {"statement": "The last order placed is remembered for the visit.", "lines": "10",
         "decision_points": [ids[2]]}],
        "technical_decisions": [{"id": ids[3], "reason": "confirmation message only"}]}], ledger)
    assert rules_ledger.unaccounted(batch, ledger) == {}
    assert ledger["candidates"][c.id]["dismissed"] == {ids[3]: "confirmation message only"}


def test_a_technical_candidate_dismisses_all_its_points_and_the_parser_dismissals_are_marked_auto(scanned):
    batch, ledger = _ledger(scanned, {"com.acme.shop.web.GlobalModel.trim"})
    rules_ledger.apply_answer(batch, [{"candidate": batch[0].id, "technical": "input clean-up"}], ledger)
    assert rules_ledger.unaccounted(batch, ledger) == {}
    assert set(ledger["candidates"][batch[0].id]["dismissed"].values()) == {"input clean-up"}
    auto = rc.Candidate(id="C09999", path="X.java", start=1, end=2, kind="method", symbol="X.getA", language="Java",
                        parser="tree-sitter", status="auto-technical", reason="accessor",
                        decisions=[{"id": "DP-09999", "line": 1, "kind": "method", "text": "X.getA"}])
    assert rules_ledger.new_ledger([auto])["candidates"]["C09999"]["dismissed"] == {"DP-09999": "auto: accessor"}


def test_a_restatement_keeps_the_points_its_rules_named(scanned):
    batch, ledger = _ledger(scanned, {"com.acme.shop.validation.OrderFormValidator.validate"})
    c, ids = batch[0], [d["id"] for d in batch[0].decisions]
    rules_ledger.apply_answer(batch, [{"candidate": c.id, "rules": [
        {"statement": "`quantity > 10` needs `email`", "lines": "6-7", "decision_points": ids}]}], ledger)
    rules_ledger.apply_answer(batch, [{"candidate": c.id, "rules": [
        {"statement": "An order of more than 10 items needs an email address.", "lines": "6-7"}]}], ledger,
        replace=True)
    assert len(ledger["raw_rules"]) == 1 and ledger["raw_rules"][0]["decision_points"] == ids
    assert rules_ledger.unaccounted(batch, ledger) == {}


def test_the_report_gives_every_point_a_status(scanned, tmp_path):
    symbols = {"com.acme.shop.web.OrderController.place", "com.acme.shop.web.GlobalModel.trim",
               "com.acme.shop.web.MaintenanceInterceptor.preHandle"}
    batch, ledger = _ledger(scanned, symbols)
    by = {c.symbol: c for c in batch}
    place, trim, gate = (by["com.acme.shop.web.OrderController.place"], by["com.acme.shop.web.GlobalModel.trim"],
                         by["com.acme.shop.web.MaintenanceInterceptor.preHandle"])
    rules_ledger.apply_answer(batch, [
        {"candidate": place.id, "rules": [{"statement": "An order with invalid input is shown the form again.",
                                           "lines": "7-9", "decision_points": [place.decisions[0]["id"]]}]},
        {"candidate": trim.id, "technical": "input clean-up"},
        {"candidate": gate.id, "rules": [{"statement": "Only administrators can use the site during maintenance.",
                                          "lines": "5-8"}]},
    ], ledger)
    rules_ledger.finalize(ledger, str(tmp_path), [])
    status = {r["id"]: r["status"] for r in rules_ledger.decision_report(ledger)}
    assert status[place.decisions[0]["id"]] in ("rule", "unverified rule")
    assert status[trim.decisions[0]["id"]] == "technical"
    assert status[gate.decisions[0]["id"]] == "unaccounted" and status[place.decisions[2]["id"]] == "unaccounted"
    md = rules_ledger.decisions_markdown(ledger)
    assert "### Decision Points Not Accounted For (" in md and f"| {gate.decisions[0]['id']} |" in md
    assert "### Decision Points Dismissed as Technical by the Agent (1)" in md and "input clean-up" in md
    rows = list(csv.DictReader(io.StringIO(rules_ledger.decisions_csv(ledger))))
    assert len(rows) == sum(len(c.decisions) for c in batch)
    assert {r["status"] for r in rows} >= {"technical", "unaccounted"}


# ---------------------------------------------------------------------------
# The pipeline: asked again for what was left, reported, downloadable
# ---------------------------------------------------------------------------

def test_the_pipeline_asks_once_more_reports_what_is_left_and_lists_outside_references(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from tests.test_business_rules import _session
    monkeypatch.setattr(config, "RULES_EXTRACTION", "on")
    shutil.copytree(REPO, tmp_path / "repo")
    prompts = []

    async def answer(step, pattern, state, message, output_key):
        """Names only each candidate's first point; asked again, dismisses the rest except the last."""
        text = state["rule_batch"]
        prompts.append(text)
        blocks = re.findall(r"### (C\d{5}) — .*?\nFile: `[^`]+` lines (\d+)-.*?Decision points:\n(.*?)\n```",
                            text, re.S)
        results = []
        for cid, start, listing in blocks:
            ids = re.findall(r"^- (DP-\d{5}) ", listing, re.M)
            if "Account for these decision points" in text:
                results.append({"candidate": cid, "technical_decisions": [{"id": i, "reason": "display only"}
                                                                          for i in ids[:-1]]})
            else:
                results.append({"candidate": cid, "rules": [{"statement": f"A rule of candidate {cid} applies.",
                                                             "lines": start, "decision_points": ids[:1]}]})
        return "```json\n" + json.dumps({"results": results}) + "\n```"

    monkeypatch.setattr(main, "_run_isolated", answer)
    sid = _session(tmp_path / "repo", [{"pattern": "java", "kind": "language"},
                                       {"pattern": "thymeleaf", "kind": "frontend"}])
    asyncio.run(main._run_rules_extraction(sid))
    state = asyncio.run(main._get_state(sid))
    assert any("Account for these decision points" in p for p in prompts)
    ledger = json.loads(Path(state["rules_ledger_path"]).read_text())
    rows = rules_ledger.decision_report(ledger)
    multi = [c for c in ledger["candidates"].values() if len(c["decisions"]) > 2]
    assert multi
    for c in multi:                                   # first named, middle dismissed, last left unaccounted
        status = [next(r["status"] for r in rows if r["id"] == d["id"]) for d in c["decisions"]]
        assert status[0] in ("rule", "unverified rule") and set(status[1:-1]) == {"technical"}
        assert status[-1] == "unaccounted"
    md = state["rules_markdown"]
    assert "## Decision Points" in md and "### Decision Points Not Accounted For (" in md
    assert external_rules.HEADING in md and "`order_audit`" in md
    with TestClient(main.app) as client:
        res = client.get(f"/api/sessions/{sid}/download/decision-points")
        missing = client.get(f"/api/sessions/{_session(tmp_path, [])}/download/decision-points")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    assert res.text.splitlines()[0] == "decision_point,file,line,kind,code,status,rules,reason,candidate,area"
    assert len(res.text.strip().splitlines()) == len(rows) + 1
    assert missing.status_code == 404
