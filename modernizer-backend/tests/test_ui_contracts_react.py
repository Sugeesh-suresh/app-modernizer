"""A React front end the way real ones are written — a shared axios client with a
baseURL, URL constants and API functions in their own modules, calls made from
hooks, state and timers — against a Spring REST back end (tests/fixtures/pds-react:
the PDS Job List, Job Status and Attribute Search screens). Every control must reach
the GET endpoint that serves it, with that endpoint's contract."""
from pathlib import Path

import pytest

from agents.shared import interfaces, ui_contracts
from agents.shared.rule_candidates import _PARSERS

pytestmark = pytest.mark.skipif("java" not in _PARSERS or "tsx" not in _PARSERS,
                                reason="tree-sitter grammars not installed")

REPO = Path(__file__).parent / "fixtures" / "pds-react"
PAGES = "pds-ui/src/pages/"


@pytest.fixture(scope="module")
def result() -> dict:
    return ui_contracts.scan(str(REPO), interfaces.scan(str(REPO)))


def _rows(result, screen: str) -> list[tuple]:
    s = next(s for s in result["screens"] if s["file"] == PAGES + screen)
    return [(e["kind"], e["label"], e["event"], e["verb"], e["path"],
             [k.rsplit(" ", 1)[-1] for k in e["endpoints"]]) for e in s["elements"]]


def test_every_call_is_a_get_tied_to_its_handler_and_every_endpoint_is_called(result):
    elements = [e for s in result["screens"] for e in s["elements"]]
    assert elements and all(e["verb"] == "GET" and e["endpoints"] for e in elements)
    assert result["unmatched"] == [] and result["uncalled"] == []
    # The service modules hold the calls; the controls are on the pages that use them.
    assert {s["file"] for s in result["screens"]} == {PAGES + f for f in
                                                      ("JobList.jsx", "JobStatus.jsx", "AttributeSearch.jsx")}


def test_job_list(result):
    rows = _rows(result, "JobList.jsx")
    assert ("page load", "JobList.jsx", "page load", "GET", "/api/jobs", ["JobController.listJobs"]) in rows
    assert ("input", "select #viewSelect", "change", "GET", "/api/jobs", ["JobController.listJobs"]) in rows
    assert ("input", "input #jobSearch", "keydown", "GET", "/api/jobs/search", ["JobController.searchJobs"]) in rows
    search = next(e for s in result["screens"] for e in s["elements"] if e["path"] == "/api/jobs/search"
                  and e["kind"] == "input")
    assert search["sends"] == ["q", "scope", "exact", "tenant"]
    load = next(e for s in result["screens"] for e in s["elements"] if e["kind"] == "page load"
                and e["path"] == "/api/jobs")
    assert load["sends"] == ["tenant", "env", "view"]          # passed by the page to fetchJobs(params)
    grid = next(e for s in result["screens"] for e in s["elements"] if e["label"] == "table #jobGrid"
                and e["path"] == "/api/jobs")
    assert [tuple(c) for c in grid["columns"][:3]] == [("Job ID", "jobs[].jobId"),
                                                        ("Job Name", "jobs[].jobName, jobs[].warnings"),
                                                        ("Status", "jobs[].status")]


def test_job_status(result):
    rows = _rows(result, "JobStatus.jsx")
    running = ["JobController.runningJobs"]
    assert ("timer", "timer in JobStatus.jsx", "every 10000 ms", "GET", "/api/jobs/running", running) in rows
    assert ("input", 'input[checkbox] "Auto-Refresh"', "change", "GET", "/api/jobs/running", running) in rows
    for label in ('button "Previous day"', 'button "Today"', 'button "Next day"'):
        assert ("button", label, "click", "GET", "/api/jobs/completed", ["JobController.completedJobs"]) in rows
    assert ("button", 'button "Cancel"', "click", "GET", "/api/jobs/executions/{}/cancel",
            ["JobController.cancelExecution"]) in rows


def test_attribute_search(result):
    rows = _rows(result, "AttributeSearch.jsx")
    listing = ["AttributeController.listAttributes"]
    for label in ('button "First"', 'button "Previous"', 'button "Next"', 'button "Last"'):
        assert ("button", label, "click", "GET", "/api/attributes", listing) in rows
    assert ("input", 'input[checkbox] "Show Values"', "change", "GET", "/api/attributes", listing) in rows
    assert ("button", 'button #attrSearch "Search"', "click", "GET", "/api/attributes/search",
            ["AttributeController.searchAttributes"]) in rows
    assert ("link", 'a "{a.id}"', "click", "GET", "/api/attributes/{}", ["AttributeController.getAttribute"]) in rows
    grid = next(e for s in result["screens"] for e in s["elements"] if e["label"] == "table #attributeGrid")
    assert [tuple(c) for c in grid["columns"]][0] == ("ID", "content[].id")


def test_contracts_carry_the_request_and_response_schema(result):
    md = ui_contracts.contracts_markdown(result)
    attributes = md.split("### `GET /api/attributes` —")[1].split("\n### ")[0]
    assert "| `size` | query | integer | no | 20 | @Min(1), @Max(100) |" in attributes
    assert "| `content[].avail` | enum: MCOM \\| BCOM | — |" in attributes
    assert "| `totalPages` | integer | Spring Data page |" in attributes
    completed = md.split("### `GET /api/jobs/completed` —")[1].split("\n### ")[0]
    assert "| `date` | query | date | yes | — | format yyyy-MM-dd |" in completed
    assert "| `[].started` | date-time | format MM/dd/yy hh:mm a |" in completed
    cancel = md.split("### `GET /api/jobs/executions/{execId}/cancel` —")[1].split("\n### ")[0]
    assert "`204 NO_CONTENT`" in cancel and "409 CONFLICT (GlobalExceptionHandler.notRunning)" in cancel
    assert "Called from the UI by: UI-" in cancel
