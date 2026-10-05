"""Architecture diagrams: the agent's spec is checked element by element against
what it cites, then laid out and drawn by the pipeline (agents/shared/arch_diagrams.py)."""
import json

import pytest

from agents.shared import arch_diagrams as ad

EVIDENCE = {
    "EV-java-0001": "OrderController handles POST /orders/place and calls OrderService.place",
    "EV-java-0002": "OrderService.place saves the Order through OrderRepository (JPA) to the Oracle ORDERS table",
    "EV-java-0003": "OrderService publishes OrderPlaced to the orders.events JMS queue",
    "EV-ldap-0001": "SecurityConfig authenticates users against LDAP (ldap.url), session timeout 30 minutes",
}
FACTS = ad.Facts.build(["java", "oracle"], [{"verb": "POST", "path": "/orders/place", "handler": "OrderController.place"}],
                       ["orders-core"], ["ldap.url"], ["UI-001"], "POST /orders/place OrderController.place")


def node(i, label, sources, **kw):
    return {"id": i, "label": label, "sources": sources, **kw}


def edge(a, b, label, sources):
    return {"from": a, "to": b, "label": label, "sources": sources}


def check(diagram):
    return ad.validate([diagram], EVIDENCE, FACTS)


def test_parse_takes_the_json_from_a_fence_or_bare():
    spec = {"diagrams": [{"kind": "context"}]}
    assert ad.parse("text\n```json\n" + json.dumps(spec) + "\n```")[0] == spec["diagrams"]
    assert ad.parse("here: " + json.dumps(spec))[0] == spec["diagrams"]
    assert ad.parse("no json")[1]


def test_traceable_elements_are_kept_and_numbered():
    diagrams, rejected = check({"level": "high", "kind": "context", "title": "Context", "nodes": [
        node("c", "OrderController", ["EV-java-0001"]), node("s", "OrderService", ["EV-java-0002"]),
        node("d", "Oracle", ["stack:oracle"], type="database")],
        "edges": [edge("c", "s", "calls place", ["EV-java-0001"]), edge("s", "d", "saves orders", ["EV-java-0002"])]})
    assert not rejected and [d.id for d in diagrams] == ["HLD-1"]
    assert [n.type for n in diagrams[0].nodes] == ["component", "component", "database"]


@pytest.mark.parametrize("bad, reason", [
    (node("x", "Payment Gateway", ["EV-pay-0001"]), "cites no evidence item or computed fact"),
    (node("x", "Payment Gateway", []), "cites no evidence item or computed fact"),
    (node("x", "FraudChecker", ["EV-java-0001"]), "`FraudChecker` appears neither"),
    (node("x", "Billing ledger", ["EV-java-0003"]), "shares no key word"),
    (node("x", "Session store", ["EV-ldap-0001"], detail="timeout 45 minutes"), "45"),
    (node("x", "Fake endpoint", ["endpoint:GET /nope"]), "cites no evidence item or computed fact"),
])
def test_untraceable_nodes_are_left_out_with_the_reason(bad, reason):
    diagrams, rejected = check({"kind": "component", "title": "T", "nodes": [
        node("c", "OrderController", ["EV-java-0001"]), node("s", "OrderService", ["EV-java-0002"]), bad],
        "edges": [edge("c", "s", "calls place", ["EV-java-0001"]), edge("s", "x", "uses", ["EV-java-0002"])]})
    assert len(diagrams[0].nodes) == 2
    assert any(reason in why for _, why in rejected)
    assert any("an end of it is not a node" in why for _, why in rejected)     # its edge goes with it


def test_computed_facts_ground_elements():
    diagrams, rejected = check({"kind": "sequence", "level": "low", "title": "Place", "participants": [
        node("u", "Rep", ["UI-001"], type="actor"), node("c", "OrderController", ["handler:OrderController"])],
        "steps": [edge("u", "c", "POST /orders/place", ["endpoint:POST /orders/place"])]})
    assert not rejected and diagrams[0].id == "LLD-1" and diagrams[0].kind == "sequence"


def test_a_diagram_without_two_traceable_elements_is_dropped():
    diagrams, rejected = check({"kind": "component", "title": "Lonely", "nodes": [
        node("c", "OrderController", ["EV-java-0001"]), node("g", "Ghost", [])], "edges": []})
    assert not diagrams and any("fewer than two" in why for _, why in rejected)


def _all_kinds():
    diagrams, _ = ad.validate([
        {"level": "high", "kind": "context", "title": "Context", "nodes": [
            node("u", "Users", ["EV-ldap-0001"], type="actor"), node("s", "OrderController", ["EV-java-0001"], type="system"),
            node("d", "Oracle", ["stack:oracle"], type="database"), node("q", "orders.events", ["EV-java-0003"], type="queue"),
            node("l", "LDAP", ["EV-ldap-0001"], type="external")],
         "edges": [edge("u", "s", "users authenticate", ["EV-ldap-0001"]), edge("s", "d", "saves orders", ["EV-java-0002"]),
                   edge("s", "q", "publishes OrderPlaced", ["EV-java-0003"]), edge("s", "l", "authenticates", ["EV-ldap-0001"]),
                   edge("d", "u", "orders table", ["EV-java-0002"])]},                    # a cycle
        {"level": "low", "kind": "sequence", "title": "Place", "participants": [
            node("c", "OrderController", ["EV-java-0001"]), node("s", "OrderService", ["EV-java-0002"])],
         "steps": [edge("c", "s", "place", ["EV-java-0001"]), edge("s", "s", "saves the order", ["EV-java-0002"]),
                   edge("s", "c", "return order", ["EV-java-0002"])]},
        {"level": "low", "kind": "data", "title": "Data", "nodes": [
            node("o", "Order", ["EV-java-0002"], type="entity", fields=["ORDERS table"]),
            node("q", "OrderPlaced", ["EV-java-0003"], type="entity")],
         "edges": [edge("o", "q", "published as OrderPlaced", ["EV-java-0003"])]}], EVIDENCE, FACTS)
    return diagrams


def test_every_kind_is_drawn_and_the_same_spec_draws_the_same_picture(tmp_path):
    pytest.importorskip("PIL")
    diagrams = _all_kinds()
    assert [d.id for d in diagrams] == ["HLD-1", "LLD-1", "LLD-2"]
    assert ad.render(diagrams, str(tmp_path / "a")) == ["HLD-1.png", "LLD-1.png", "LLD-2.png"]
    ad.render(_all_kinds(), str(tmp_path / "b"))
    for name in ("HLD-1.png", "LLD-1.png", "LLD-2.png"):
        first = (tmp_path / "a" / name).read_bytes()
        assert first.startswith(b"\x89PNG") and first == (tmp_path / "b" / name).read_bytes()


def test_markdown_shows_the_image_and_the_elements_with_their_sources(tmp_path):
    pytest.importorskip("PIL")
    diagrams = _all_kinds()
    ad.render(diagrams, str(tmp_path))
    md = ad.to_markdown(diagrams)
    assert md.startswith(ad.HEADING) and md.index("### High-level design") < md.index("### Low-level design")
    assert "![HLD-1 — Context](diagrams/HLD-1.png)" in md
    assert "| OrderController → Oracle | connection | saves orders | EV-java-0002 |" in md
    assert "| Oracle | database | — | `stack:oracle` |" in md
    assert "| 3 | OrderService | OrderController | return order | EV-java-0002 |" in md


def test_without_an_image_the_diagram_is_text():
    diagrams = _all_kinds()                     # not rendered: no image
    md = ad.to_markdown(diagrams)
    assert "```text" in md and "OrderController ── saves orders ──▶ Oracle" in md
    assert " 1. OrderController → OrderService : place" in md
    assert ad.to_markdown([]) == ""


def test_word_shows_a_diagram_at_its_real_size_not_stretched(tmp_path):
    pytest.importorskip("PIL")
    import io
    import zipfile
    from docx import Document
    from agents.shared import docx_export
    diagrams = _all_kinds()[2:]                                  # the small data diagram
    ad.render(diagrams, str(tmp_path))
    png = tmp_path / "LLD-2.png"
    assert docx_export._png_dpi(png) == pytest.approx(192, abs=1)
    pixels = docx_export._png_size(png)[0]
    data = docx_export.to_docx("T", [(None, "![d](diagrams/LLD-2.png)")], {"diagrams/LLD-2.png": png})
    shape = Document(io.BytesIO(data)).inline_shapes[0]
    assert shape.width.inches == pytest.approx(pixels / 192, abs=0.02)
    assert shape.width.inches < docx_export.PAGE_WIDTH_IN
    assert any(n.startswith("word/media/") for n in zipfile.ZipFile(io.BytesIO(data)).namelist())
