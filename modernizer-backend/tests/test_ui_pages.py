"""UI pages and every interactive element on them (agents/shared/ui_pages.py), on a
Thymeleaf + Spring Boot app (tests/fixtures/thymeleaf-ui-pages): a layout, a fragment,
a search form with a select, links, a modal toggle, an input a script reads, buttons
bound by jQuery (also through an object method or a noConflict alias) or an inline
handler, a role-guarded and conditionally disabled button, a server-rendered grid, a
Handsontable grid whose columns depend on a checkbox, a form with bean validation, REST
calls — and a third-party plugin script whose generic bindings must not be taken for the
page's behaviour.

One row per action a user can take on an element: what happens on the UI, and the API
that action — and only that action — calls. Request and response fields are printed
once, under Endpoint Contracts, and referred to everywhere else."""
import re
from pathlib import Path

import pytest

from agents.shared import interfaces, ui_contracts, ui_pages
from agents.shared.rule_candidates import _PARSERS

pytestmark = pytest.mark.skipif("java" not in _PARSERS or "javascript" not in _PARSERS,
                                reason="tree-sitter grammars not installed")

REPO = str(Path(__file__).parent / "fixtures" / "thymeleaf-ui-pages")
T = "src/main/resources/templates/"
HEADER = "| # | Element id | Element | User action | What happens on the UI | API called by this action |"
ATTR_API = "`GET /api/attributes/search` → `AttributeApiController.search` (`AttributeApiController.java:10`) — UI-001"
LIST_API = "`GET /orders` → `OrderPageController.list` (`OrderPageController.java:16`)"


@pytest.fixture(scope="module")
def scanned():
    inv = interfaces.scan(REPO)
    result = ui_contracts.scan(REPO, inv)
    return result, ui_pages.scan(REPO, inv, result)


@pytest.fixture(scope="module")
def pages(scanned):
    return {p.rel: p for p in scanned[1]}


@pytest.fixture(scope="module")
def md(scanned):
    return ui_pages.to_markdown(scanned[1])


def _section(md: str, page: str) -> str:
    return md.split(f"### Page `{page}`")[1].split("\n### Page ")[0]


def _rows(md: str, page: str) -> list[list[str]]:
    return [[c.strip() for c in line.strip("|").split(" | ")] for line in _section(md, page).splitlines()
            if re.match(r"\| C\d+[a-z]? \|", line)]


def _row(md: str, page: str, ref: str) -> list[str]:
    return next(r[1:] for r in _rows(md, page) if r[0] == ref)


def _detail(md: str, page: str, head: str) -> str:
    return _section(md, page).split(head)[1].split("\n**")[0]


def test_pages_are_the_templates_a_handler_renders_not_fragments_or_layouts(pages):
    assert sorted(pages) == [T + "dashboard/attribute_search.html", T + "orders/detail.html",
                             T + "orders/form.html", T + "orders/list.html", T + "selfservicetool/job_list.html"]
    listing = pages[T + "orders/list.html"]
    assert listing.includes == [T + "fragments/header.html", T + "layouts/main.html"]
    assert listing.scripts == ["src/main/resources/static/js/orders.js"]
    assert listing.files == [T + "fragments/header.html", T + "layouts/main.html", T + "orders/list.html"]


def test_one_row_per_action_with_the_api_of_that_action(md):
    for page in ("orders/list.html", "orders/form.html", "dashboard/attribute_search.html"):
        assert HEADER in _section(md, page)
    assert [(r[0], r[1], r[3]) for r in _rows(md, "orders/list.html")] == [
        ("C1", "`#navOrders`", "click"), ("C2", "`#navAdmin`", "click"), ("C3", "— (no id)", "click"),
        ("C4", "— (no id)", "click"), ("C5", "`#searchForm`", "submit"), ("C6a", "— (name=`q`)", "type text"),
        ("C6b", "— (name=`q`)", "press Enter"), ("C7", "`#statusFilter`", "choose an option"),
        ("C8", "— (no id)", "click"), ("C9", "`#filtersBtn`", "click"), ("C10", "`#quickJump`", "type text"),
        ("C11", "`#jumpBtn`", "click"), ("C12", "`#bulkDelete`", "click"), ("C13", "`#orderGrid`", "view rows"),
        ("C14", "— (no id)", "click"), ("C15", "— (class=`cancel-btn`)", "click"), ("C16", "— (no id)", "click")]
    # Typing calls nothing; pressing Enter submits the form and calls its endpoint.
    assert _row(md, "orders/list.html", "C6a")[3:] == [
        "Nothing happens yet: the value goes as `q` when form C5 is submitted", "none"]
    assert _row(md, "orders/list.html", "C6b")[3:] == [
        "Submits form C5: the same result as C5", f"via form C5: {LIST_API} — UI-013"]


def test_button_click_checkbox_and_its_grid(md):
    page = "dashboard/attribute_search.html"
    assert _row(md, page, "C4") == [
        "`#searchButton`", 'button "Search"', "click",
        "Calls the server; stays on this page: fills grid `#attributeGrid` with the response "
        "(`attribute_search.js:17`)", ATTR_API]
    assert _row(md, page, "C6") == [
        "`#showValues`", 'checkbox "Show Values"', "check / uncheck",
        "Calls the server; stays on this page: fills grid `#attributeGrid` with the response "
        "(`attribute_search.js:17`)", ATTR_API]
    assert _row(md, page, "C5")[2:] == [
        "click", "Changes this page only (no server call): sets the value of `#attrQuery` (`attribute_search.js:23`); "
                 "clears `#attributeGrid` (`attribute_search.js:24`)", "none — handled in the browser"]
    assert _row(md, page, "C3")[3] == ("No action of its own: the value is used by `search()` "
                                       "(`attribute_search.js:5`) when C4 click, C6 check / uncheck")
    assert _row(md, page, "C1")[2:] == ["click", "no behaviour found in the code", "none"]
    search = _detail(md, page, '#searchButton · button "Search"**')
    assert "| Value | `[].value` | only when `#showValues` is checked (`attribute_search.js:15`) |" in search
    assert "| ID | `[].id` | always (`attribute_search.js:13`) |" in search
    assert "Grid columns after check / uncheck: the same as C4 click." in \
        _detail(md, page, '#showValues · checkbox "Show Values"**')
    section = _section(md, page)
    assert "handsontable-chosen-editor.js` (third-party, not read)" in section and "keydown" not in section


def test_links_forms_and_buttons_say_which_page_loads(md):
    page = "orders/list.html"
    assert _row(md, page, "C2")[3:] == ["Requests a URL the code does not serve: requests `/admin` — no handler "
                                        "in the code serves this path",
                                        "`GET /admin` — no handler found in the code (UI-010)"]
    assert _row(md, page, "C5")[3:] == ["Loads a page: `orders/list.html` with the results", f"{LIST_API} — UI-013"]
    assert _row(md, page, "C8")[3:] == ["Submits form C5: loads page `orders/list.html` with the results",
                                        f"via form C5: {LIST_API} — UI-013"]
    assert _row(md, page, "C9")[3:] == ["Opens a dialog or panel (no server call): opens modal `#filterModal` on "
                                        "this page", "none — handled in the browser"]
    assert _row(md, page, "C10")[3:] == ["No action of its own: the value is used by the script (`orders.js:16`) "
                                         "when C11 click", "none"]
    assert _row(md, page, "C11")[3:] == [
        "Loads a page: `orders/detail.html`",
        "`GET /orders/{id}` → `OrderPageController.detail` (`OrderPageController.java:26`) — UI-004"]
    assert _row(md, page, "C12")[3] == ('Loads a page: `orders/list.html`; first asks for confirmation: '
                                        '"Delete the selected orders?" (`orders.js:25`)')
    assert _row(md, page, "C15")[3:] == [
        "Calls the server; stays on this page: shows a message: `res.message` (`orders.js:5`); sets `disabled` "
        "= `true` on the element itself (`orders.js:6`)",
        "`POST /api/orders/{id}/cancel` → `OrderApiController.cancel` (`OrderApiController.java:18`) — UI-002"]
    assert _row(md, page, "C7")[3:] == [
        "Nothing happens yet: its options come from `statuses`, rendered with the page; the value goes as "
        "`status` when form C5 is submitted", "none"]
    assert _row(md, page, "C13")[3:] == ["Display only: shows one row per item of `orders`, rendered with the page",
                                         "none"]


def test_a_form_submit_names_the_redirect_and_the_page_shown_again(md):
    assert _row(md, "orders/form.html", "C1")[2:] == [
        "submit", "Loads a page: redirects to `/orders` and loads page `orders/list.html`, or shows page "
                  "`orders/form.html` again (e.g. with validation errors)",
        "`POST /orders` → `OrderPageController.create` (`OrderPageController.java:39`) — UI-012"]
    form = _detail(md, "orders/form.html", "#orderForm · form**")
    assert "| `quantity` | number | type=number, required, min=1, max=50 |" in form
    assert "Server-side types and constraints of these fields: Endpoint Contracts → `POST /orders`." in form


def test_request_and_response_fields_are_never_repeated_here(md):
    # The fields are printed once, under Endpoint Contracts; this section refers to them.
    assert "| Request parameter |" not in md and "Response —" not in md and "| `[].name` | string" not in md
    cancel = _detail(md, "orders/list.html", 'button "Cancel"**')
    assert ("- Calls `POST /api/orders/{id}/cancel` → `OrderApiController.cancel` (UI-002) when the user: click. "
            "Request and response fields: Endpoint Contracts → `POST /api/orders/{id}/cancel`.") in cancel
    assert "page data `currentUser`, `orders`, `q` — fields: Endpoint Contracts → `GET /orders`" in \
        _section(md, "orders/list.html")


def test_the_ui_to_backend_section_does_not_repeat_form_fields_and_grid_columns(scanned):
    result, pages = scanned
    full = ui_contracts.to_markdown(result)
    deduped = ui_contracts.to_markdown(result, ui_pages.covered(pages))
    assert "form fields** (as the UI sends them)" in full and "form fields** (as the UI sends them)" not in deduped
    assert "grid columns** (from" not in deduped
    assert "Form fields and grid columns of this screen: UI Pages and Interactive Components → page " \
           "`orders/form.html`." in deduped


def test_visibility_and_state_are_in_the_element_details(md):
    bulk = _detail(md, "orders/list.html", '#bulkDelete · button "Delete selected"**')
    assert "- Shown / enabled: only for `hasRole('ORDER_ADMIN')`; disabled when `${#lists.isEmpty(orders)}`" in bulk
    cancel = _detail(md, "orders/list.html", 'button "Cancel"**')
    assert "one per item of `orders`; shown when `${o.status.name() == 'OPEN'}`" in cancel
    nav = _detail(md, "orders/list.html", '#navOrders · link "Orders"**')
    assert "- From: `layouts/main.html` (included in this page)" in nav


def test_a_fragment_element_is_on_every_page_that_includes_it(md):
    for page in ("orders/list.html", "orders/detail.html"):
        assert any(r[1] == 'link "New order"' and r[3] == "Loads a page: `orders/form.html`" for r in
                   [x[1:] for x in _rows(md, page)])


def test_a_binding_whose_element_is_built_at_run_time_is_listed_not_dropped(md):
    orphans = _section(md, "orders/list.html").split("#### Script handlers whose element is not in this page's "
                                                     "markup")[1]
    assert "| `.row-pin` | click | jQuery .on('click') in `orders.js` | toggles class `pinned` on the element itself" \
        in orphans
    assert "`#refreshStatus`" not in orphans and "`.cancel-btn`" not in orphans


def test_the_architects_field_tables_are_replaced_by_a_reference():
    section = ("- **UI-001** — Search calls `GET /api/x`.\n\n| Field | Type | Constraints |\n|---|---|---|\n"
               "| `q` | string | — |\n\nThe grid then shows the rows.\n\n| Column | Shows |\n|---|---|\n| Name | `name` |")
    out, removed = ui_contracts.strip_schema_tables(section)
    assert removed == 1 and "| `q` | string" not in out and "Fields: see Endpoint Contracts." in out
    assert "| Column | Shows |" in out and "The grid then shows the rows." in out


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
                                                    "static/js/create_menubar.js", "static/js/org-chart.js"))


def test_a_javascript_url_expression_keeps_its_literal_parts():
    assert ui_pages._js_url("'/orders/' + id") == "/orders/{}"
    assert ui_pages._js_url("base + '/x?q=' + q") == "{}/x?q={}"


def test_no_pages_gives_no_section(tmp_path):
    assert ui_pages.scan(str(tmp_path), {"endpoints": []}, {"screens": [], "contracts": []}) == []
    assert ui_pages.to_markdown([]) == ""


def test_client_side_actions_say_so_and_call_no_api(md):
    """The Job List: the search box and Exact Search filter the rows already loaded, the view selector
    switches the grid's columns — none of them calls the server."""
    page = "selfservicetool/job_list.html"
    section = _section(md, page)
    assert "- Page load: `GET /api/jobs` → `JobApiController.all`" in section
    assert _row(md, page, "C1")[2:] == [
        "type text", "Changes this page only (no server call): filters the rows already loaded and re-shows grid "
                     "`#jobGrid` (`job_list.js:45`)", "none — handled in the browser"]
    assert _row(md, page, "C2")[2:] == [
        "choose an option", "No action of its own: the value is used by `filterJobs()` (`job_list.js:39`) when C1 "
                            "type text, C3 check / uncheck", "none"]
    assert _row(md, page, "C3")[3:] == [
        "Changes this page only (no server call): filters the rows already loaded and re-shows grid `#jobGrid` "
        "(`job_list.js:45`)", "none — handled in the browser"]
    assert _row(md, page, "C4b") == [
        "`#viewSelect`", "select", 'choose "Description"',
        'Changes this page only (no server call): switches `#jobGrid` to the "Description" columns: Job ID, '
        "Job Name, Status, Attribute, Description, Edit, Run (`job_list.js:26`)", "none — handled in the browser"]
    assert [r[3] for r in _rows(md, page) if r[0].startswith("C4")] == [
        'choose "Standard"', 'choose "Description"', 'choose "Dev"']
    assert _row(md, page, "C4a")[3].endswith("Job ID, Job Name, Status, Attribute, Attribute Type, Edit "
                                             "(`job_list.js:32`)")
    view = _detail(md, page, "#viewSelect · select**")
    assert 'Grid columns after choose "Dev":' in view
    assert "| File Name | `[].fileName` | always (`job_list.js:29`) |" in view   # from the page-load response
