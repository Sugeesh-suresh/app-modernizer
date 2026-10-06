"""UI pages and every interactive element on them (agents/shared/ui_pages.py), on a
Thymeleaf + Spring Boot app (tests/fixtures/thymeleaf-ui-pages): a layout, a fragment,
a search form with a select, links, a modal toggle, an input a script reads, buttons
bound by jQuery (also through an object method or a noConflict alias) or an inline
handler, a role-guarded and conditionally disabled button, a server-rendered grid, a
form with bean validation, REST calls — and a third-party plugin script whose generic
bindings must not be taken for the page's behaviour.

Columns: Element id | Element | User action | What happens on the UI | API called."""
import re
from pathlib import Path

import pytest

from agents.shared import interfaces, ui_contracts, ui_pages
from agents.shared.rule_candidates import _PARSERS

pytestmark = pytest.mark.skipif("java" not in _PARSERS or "javascript" not in _PARSERS,
                                reason="tree-sitter grammars not installed")

REPO = str(Path(__file__).parent / "fixtures" / "thymeleaf-ui-pages")
T = "src/main/resources/templates/"
HEADER = "| # | Element id | Element | User action | What happens on the UI | API called |"


@pytest.fixture(scope="module")
def pages():
    inv = interfaces.scan(REPO)
    return {p.rel: p for p in ui_pages.scan(REPO, inv, ui_contracts.scan(REPO, inv))}


@pytest.fixture(scope="module")
def md(pages):
    return ui_pages.to_markdown(list(pages.values()))


def _section(md: str, page: str) -> str:
    return md.split(f"### Page `{page}`")[1].split("\n### Page ")[0]


def _rows(md: str, page: str) -> list[list[str]]:
    return [[c.strip() for c in line.strip("|").split(" | ")] for line in _section(md, page).splitlines()
            if re.match(r"\| C\d+ \|", line)]


def _row(md: str, page: str, locator: str, element: str = "") -> list[str]:
    return next(r for r in _rows(md, page) if r[1] == locator and (not element or r[2] == element))


def test_pages_are_the_templates_a_handler_renders_not_fragments_or_layouts(pages):
    assert sorted(pages) == [T + "dashboard/attribute_search.html", T + "orders/detail.html",
                             T + "orders/form.html", T + "orders/list.html"]
    listing = pages[T + "orders/list.html"]
    assert listing.includes == [T + "fragments/header.html", T + "layouts/main.html"]
    assert listing.scripts == ["src/main/resources/static/js/orders.js"]


def test_the_table_has_the_user_action_ui_outcome_and_api_columns(md):
    for page in ("orders/list.html", "orders/form.html", "dashboard/attribute_search.html"):
        assert HEADER in _section(md, page)
    assert "Interaction / state" not in md and "Target navigation" not in md


def test_every_element_of_the_page_in_order(md):
    assert [(r[1], r[2]) for r in _rows(md, "orders/list.html")] == [
        ("`#navOrders`", 'link "Orders"'), ("`#navAdmin`", 'link "Admin"'), ("— (no id)", 'link "Orders"'),
        ("— (no id)", 'link "New order"'), ("`#searchForm`", "form"), ("— (name=`q`)", "input"),
        ("`#statusFilter`", "select"), ("— (no id)", 'button "Search"'), ("`#filtersBtn`", 'button "Filters"'),
        ("`#quickJump`", 'input "Order #"'), ("`#jumpBtn`", 'button "Go"'),
        ("`#bulkDelete`", 'button "Delete selected"'), ("`#orderGrid`", "grid"), ("— (no id)", 'link "${o.id}"'),
        ("— (class=`cancel-btn`)", 'button "Cancel"'), ("— (no id)", 'link "Next page"')]


def test_a_search_button_click_shows_its_ui_result_and_the_endpoint_it_calls(md):
    # The attribute-search case: bound through an object method; a plugin script binds generic inputs.
    page = "dashboard/attribute_search.html"
    assert _row(md, page, "`#searchButton`")[2:] == [
        'button "Search"', "click",
        "calls the server and stays on this page; updates the content of `#attributeGrid` (`attribute_search.js:7`)",
        "`GET /api/attributes/search` → `AttributeApiController.search` (`AttributeApiController.java:10`) — UI-001"]
    assert _row(md, page, "`#clearSearchButton`")[3:] == [
        "click", "sets the value of `#attrQuery` (`attribute_search.js:14`); clears `#attributeGrid` "
                 "(`attribute_search.js:15`)", "none"]
    assert _row(md, page, "`#showValues`")[2:4] == ['checkbox "Show Values"', "check / uncheck, change the value"]
    assert _row(md, page, "`#attrQuery`")[4] == "its value is read by the script at `attribute_search.js:5`"
    assert _row(md, page, "— (class=`dropbtn`)")[3:] == ["click", "no behaviour found in the code", "none"]
    section = _section(md, page)
    assert "handsontable-chosen-editor.js` (third-party, not read)" in section
    assert "stops the browser" not in section and "keydown" not in section
    detail = section.split('#searchButton · button "Search"**')[1].split("\n**")[0]
    assert "| `q` | query | string | yes | — |" in detail and "| `showValues` | query | boolean | no | — |" in detail
    assert "Response — `List<AttributeRow>`" in detail and "| `[].name` | string | — |" in detail


def test_links_forms_and_buttons_say_which_page_loads(md):
    page = "orders/list.html"
    assert _row(md, page, "`#navAdmin`")[4:] == ["requests `/admin` — no handler in the code serves this path",
                                                 "`GET /admin` — no handler found in the code (UI-009)"]
    assert _row(md, page, "`#searchForm`")[4] == "loads page `orders/list.html` with the results"
    assert _row(md, page, "— (no id)", 'button "Search"')[4:] == [
        "loads page `orders/list.html` with the results",
        "via form C5: `GET /orders` → `OrderPageController.list` (`OrderPageController.java:16`) — UI-012"]
    assert _row(md, page, "`#filtersBtn`")[3:] == ["click", "opens modal `#filterModal` on this page", "none"]
    assert _row(md, page, "`#jumpBtn`")[4:] == [
        "loads page `orders/detail.html`",
        "`GET /orders/{id}` → `OrderPageController.detail` (`OrderPageController.java:26`) — UI-004"]
    assert _row(md, page, "`#bulkDelete`")[4] == ('asks for confirmation: "Delete the selected orders?" '
                                                 '(`orders.js:25`); loads page `orders/list.html`')
    assert _row(md, page, "— (class=`cancel-btn`)")[4:] == [
        "calls the server and stays on this page; shows a message: `res.message` (`orders.js:5`); sets `disabled` "
        "= `true` on the element itself (`orders.js:6`)",
        "`POST /api/orders/{id}/cancel` → `OrderApiController.cancel` (`OrderApiController.java:18`) — UI-002"]
    assert _row(md, page, "`#statusFilter`")[3:] == [
        "choose an option", "its options come from `statuses`, rendered with the page; its value is sent as "
        "`status` when form C5 is submitted",
        "via form C5: `GET /orders` → `OrderPageController.list` (`OrderPageController.java:16`) — UI-012"]
    assert _row(md, page, "`#orderGrid`")[3:] == ["view rows", "shows one row per item of `orders`, rendered with "
                                                  "the page", "none"]


def test_a_form_submit_names_the_redirect_and_the_page_shown_again(md):
    form = _row(md, "orders/form.html", "`#orderForm`")
    assert form[3:] == ["submit", "redirects to `/orders` and loads page `orders/list.html`, or shows page "
                        "`orders/form.html` again (e.g. with validation errors)",
                        "`POST /orders` → `OrderPageController.create` (`OrderPageController.java:39`) — UI-011"]
    quantity = _row(md, "orders/form.html", "— (name=`quantity`, th:field=`*{quantity}`)")
    assert quantity[3:5] == ["type a number, press Enter (submits the form)",
                             "its value is sent as `quantity` when form C1 is submitted"]
    section = _section(md, "orders/form.html")
    assert "| `quantity` | number | type=number, required, min=1, max=50 | integer | @NotNull, @Min(1), @Max(50) |" \
        in section


def test_visibility_and_state_move_to_the_element_details(md):
    section = _section(md, "orders/list.html")
    bulk = section.split('#bulkDelete · button "Delete selected"**')[1].split("\n**")[0]
    assert "- Shown / enabled: only for `hasRole('ORDER_ADMIN')`; disabled when `${#lists.isEmpty(orders)}`" in bulk
    cancel = section.split('button "Cancel"**')[1].split("\n**")[0]
    assert "one per item of `orders`; shown when `${o.status.name() == 'OPEN'}`" in cancel
    assert "· access @PreAuthorize(\"hasRole('ORDER_ADMIN')\")" in cancel
    assert "`OrderNotOpenException` → 409 CONFLICT (GlobalAdvice.notOpen)" in cancel
    nav = section.split('#navOrders · link "Orders"**')[1].split("\n**")[0]
    assert "- From: `layouts/main.html` (included in this page)" in nav


def test_a_fragment_element_is_on_every_page_that_includes_it(md):
    for page in ("orders/list.html", "orders/detail.html"):
        assert _row(md, page, "— (no id)", 'link "New order"')[4] == "loads page `orders/form.html`"


def test_a_binding_whose_element_is_built_at_run_time_is_listed_not_dropped(md):
    orphans = _section(md, "orders/list.html").split("#### Script handlers whose element is not in this page's "
                                                     "markup")[1]
    assert "| `.row-pin` | click | jQuery .on('click') in `orders.js` | toggles class `pinned` on the element itself" \
        in orphans
    assert "`#refreshStatus`" not in orphans and "`.cancel-btn`" not in orphans


def test_selectors_match_by_id_class_or_attribute_never_by_bare_tag():
    c = ui_pages.Component("a.html", 1, "button", {"id": "go", "class": "btn primary", "name": "x"})
    assert all(ui_pages._matches(s, c) for s in ("#go", ".btn", "button.primary", "form #go", "[name=x]",
                                                  "#nope, .btn"))
    assert not any(ui_pages._matches(s, c) for s in ("#other", ".secondary", "a#go", "[name=y]", "button",
                                                      "input:checkbox"))


def test_third_party_scripts_are_recognised():
    assert all(ui_pages.is_library(s) for s in ("static/selfservicetool/handsontable-chosen-editor.js",
                                                "static/js/jquery-3.6.0.js", "static/lib/app.js", "js/select2.full.js"))
    assert not any(ui_pages.is_library(s) for s in ("static/dashboard/attribute_search.js", "static/js/orders.js",
                                                    "static/js/create_menubar.js"))


def test_a_javascript_url_expression_keeps_its_literal_parts():
    assert ui_pages._js_url("'/orders/' + id") == "/orders/{}"
    assert ui_pages._js_url("base + '/x?q=' + q") == "{}/x?q={}"


def test_no_pages_gives_no_section(tmp_path):
    assert ui_pages.scan(str(tmp_path), {"endpoints": []}, {"screens": [], "contracts": []}) == []
    assert ui_pages.to_markdown([]) == ""
