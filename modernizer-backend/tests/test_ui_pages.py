"""UI pages and every interactive component on them (agents/shared/ui_pages.py), on a
Thymeleaf + Spring Boot app (tests/fixtures/thymeleaf-ui-pages): a layout, a fragment,
a search form with a select, links, a modal toggle, an input a script reads, buttons
bound by jQuery or an inline handler, a role-guarded and conditionally disabled
button, a server-rendered grid, a form with bean validation, and a REST call."""
import re
from pathlib import Path

import pytest

from agents.shared import interfaces, ui_contracts, ui_pages
from agents.shared.rule_candidates import _PARSERS

pytestmark = pytest.mark.skipif("java" not in _PARSERS or "javascript" not in _PARSERS,
                                reason="tree-sitter grammars not installed")

REPO = str(Path(__file__).parent / "fixtures" / "thymeleaf-ui-pages")
T = "src/main/resources/templates/"


@pytest.fixture(scope="module")
def pages():
    inv = interfaces.scan(REPO)
    return {p.rel: p for p in ui_pages.scan(REPO, inv, ui_contracts.scan(REPO, inv))}


@pytest.fixture(scope="module")
def md(pages):
    return ui_pages.to_markdown(list(pages.values()))


def _rows(md: str, page: str) -> dict[str, list[str]]:
    section = md.split(f"### Page `{page}`")[1].split("\n### Page ")[0]
    rows = {}
    for line in section.splitlines():
        if re.match(r"\| C\d+ \|", line):
            cells = [c.strip() for c in line.strip("|").split(" | ")]
            rows[cells[1]] = cells
    return rows


def test_pages_are_the_templates_a_handler_renders_not_fragments_or_layouts(pages):
    assert sorted(pages) == [T + "orders/detail.html", T + "orders/form.html", T + "orders/list.html"]
    listing = pages[T + "orders/list.html"]
    assert listing.includes == [T + "fragments/header.html", T + "layouts/main.html"]
    assert listing.scripts == ["src/main/resources/static/js/orders.js"]


def test_every_interactive_element_is_listed_with_id_action_state_navigation_and_api(md):
    rows = _rows(md, "orders/list.html")
    section = md.split("### Page `orders/list.html`")[1].split("\n### Page ")[0]
    order = [(l.split(" | ")[1], l.split(" | ")[2]) for l in section.splitlines() if re.match(r"\| C\d+ \|", l)]
    assert order == [("`#navOrders`", 'link "Orders"'), ("`#navAdmin`", 'link "Admin"'),
                     ("— (no id)", 'link "Orders"'), ("— (no id)", 'link "New order"'),
                     ("`#searchForm`", "form"), ("— (name=`q`)", "input"), ("`#statusFilter`", "select"),
                     ("— (no id)", 'button "Search"'), ("`#filtersBtn`", 'button "Filters"'),
                     ("`#quickJump`", 'input "Order #"'), ("`#jumpBtn`", 'button "Go"'),
                     ("`#bulkDelete`", 'button "Delete selected"'), ("`#orderGrid`", "grid"),
                     ("— (no id)", 'link "${o.id}"'), ("— (class=`cancel-btn`)", 'button "Cancel"'),
                     ("— (no id)", 'link "Next page"')]
    #       Element, Action, Interaction / state, Target navigation, API called
    assert rows["`#navAdmin`"][2:] == [
        'link "Admin"', "navigates", "only for `hasRole('ADMIN')`; from `layouts/main.html`",
        "`/admin` — no handler in the code serves this path", "`GET /admin` — no handler found (UI-008)"]
    assert rows["`#statusFilter`"][2:4] == ["select", "sent as `status` with form `#searchForm`"]
    assert rows["`#filtersBtn`"][3:6] == ["opens a panel or dialog (modal)", "—",
                                          "stays on the page; opens `#filterModal` (modal)"]
    assert rows["`#quickJump`"][3] == "read by script `orders.js:16`"
    jump = rows["`#jumpBtn`"]
    assert jump[4] == "navigates to `'/orders/' + id` (`orders.js:17`)"
    assert jump[6] == "`GET /orders/{id}` → `OrderPageController.detail` (UI-003, on click)"
    bulk = rows["`#bulkDelete`"]
    assert bulk[4] == ("only for `hasRole('ORDER_ADMIN')`; disabled when `${#lists.isEmpty(orders)}`; asks for "
                       "confirmation: \"Delete the selected orders?\" (`orders.js:25`); can cancel the action "
                       "(returns false) (`orders.js:26`); navigates to `'/orders?deleted=true'` (`orders.js:28`)")
    cancel = rows["— (class=`cancel-btn`)"]
    assert cancel[2] == 'button "Cancel"'
    assert cancel[4] == ("one per item of `orders`; shown when `${o.status.name() == 'OPEN'}`; styled by "
                         "`${o.overdue} ? 'btn-danger'`; shows a message: `res.message` (`orders.js:5`); sets "
                         "`disabled` = `true` on the element itself (`orders.js:6`)")
    assert cancel[5:] == ["stays on the page",
                          "`POST /api/orders/{id}/cancel` → `OrderApiController.cancel` (UI-001, on click)"]
    assert rows["`#orderGrid`"][3:6] == ["shows `orders` (server-rendered rows)", "—", "—"]


def test_a_row_link_is_labelled_by_its_expression_and_leads_to_the_page_its_handler_renders(md):
    section = md.split("### Page `orders/list.html`")[1]
    row = next(l for l in section.splitlines() if 'link "${o.id}"' in l)
    assert "one per item of `orders`" in row and "renders `orders/detail.html`" in row
    assert "`GET /orders/{id}` → `OrderPageController.detail`" in row


def test_form_submit_follows_the_redirect_and_merges_client_and_server_checks(md):
    rows = _rows(md, "orders/form.html")
    form = rows["`#orderForm`"]
    assert form[3:] == ["submits (POST)", "—", "renders `orders/form.html`; redirects to `/orders` → "
                        "`orders/list.html`", "`POST /orders` → `OrderPageController.create` (UI-010, on submit)"]
    assert rows["— (name=`quantity`, th:field=`*{quantity}`)"][3:] == [
        "sent as `quantity` with form `#orderForm`", "client checks: type=number, required, min=1, max=50", "—",
        "with form C1"]
    section = md.split("### Page `orders/form.html`")[1].split("\n### Page ")[0]
    assert "| `quantity` | number | type=number, required, min=1, max=50 | integer | @NotNull, @Min(1), @Max(50) |" \
        in section


def test_a_fragment_element_is_on_every_page_that_includes_it(md):
    for page in ("orders/list.html", "orders/detail.html"):
        section = md.split(f"### Page `{page}`")[1].split("\n### Page ")[0]
        assert '| link "New order" | navigates | from `fragments/header.html` | renders `orders/form.html` |' in section


def test_data_fields_carry_the_request_and_response_schema_of_each_call(md):
    section = md.split("### Page `orders/list.html`")[1].split("\n### Page ")[0]
    cancel = section.split("button \"Cancel\"**")[1].split("\n**")[0]
    assert "· access @PreAuthorize(\"hasRole('ORDER_ADMIN')\")" in cancel
    assert "| `id` | path | integer (64-bit) | yes | — |" in cancel
    assert "Response — `ResponseEntity<StatusResponse>`" in cancel
    assert "| `status` | enum: OPEN \\| SHIPPED \\| CANCELLED | — |" in cancel
    assert "`OrderNotOpenException` → 409 CONFLICT (GlobalAdvice.notOpen)" in cancel
    search = section.split("· #searchForm · form**")[1].split("\n**")[0]
    assert "| `status` | select | — | enum: OPEN \\| SHIPPED \\| CANCELLED | — |" in search


def test_a_binding_whose_element_is_built_at_run_time_is_listed_not_dropped(md):
    section = md.split("### Page `orders/list.html`")[1].split("\n### Page ")[0]
    orphans = section.split("#### Script handlers whose element is not in this page's markup")[1]
    assert "| `.row-pin` | click | jQuery .on('click') in `orders.js` | toggles class `pinned` on the element itself" \
        in orphans
    # A shared script's binding whose element is on another page that loads it is not reported missing.
    assert "`#refreshStatus`" not in orphans and "`.cancel-btn`" not in orphans


def test_selectors_match_by_id_class_tag_and_attribute():
    c = ui_pages.Component("a.html", 1, "button", {"id": "go", "class": "btn primary", "name": "x"})
    assert all(ui_pages._matches(s, c) for s in ("#go", ".btn", "button.primary", "form #go", "[name=x]",
                                                  "#nope, .btn"))
    assert not any(ui_pages._matches(s, c) for s in ("#other", ".secondary", "a#go", "[name=y]"))


def test_no_pages_gives_no_section(tmp_path):
    assert ui_pages.scan(str(tmp_path), {"endpoints": []}, {"screens": [], "contracts": []}) == []
    assert ui_pages.to_markdown([]) == ""
