"""UI-to-backend contracts: every control that reaches the server, tied to its
handler, with the handler's request and response contract — all read from the
code (agents/shared/ui_contracts.py)."""
from pathlib import Path

import pytest

from agents.shared import interfaces, ui_contracts
from agents.shared.rule_candidates import _PARSERS

pytestmark = pytest.mark.skipif("java" not in _PARSERS or "javascript" not in _PARSERS,
                                reason="tree-sitter grammars not installed")

JAVA = "src/main/java/com/acme/jobs"
RES = "src/main/resources"

FILES = {
    f"{JAVA}/web/JobController.java": """
package com.acme.jobs.web;

import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.annotation.*;
import javax.validation.Valid;

@Controller
@RequestMapping("/jobs")
public class JobController {
    private final JobService service;
    public JobController(JobService service) { this.service = service; }

    @GetMapping
    public String list(Model model) {
        model.addAttribute("jobs", service.findAll());
        model.addAttribute("jobForm", new JobForm());
        return "jobs/list";
    }

    @GetMapping("/{id}")
    public String detail(@PathVariable Long id, Model model) {
        model.addAttribute("job", service.find(id));
        return "jobs/detail";
    }

    @PostMapping("/save")
    public String save(@Valid @ModelAttribute("jobForm") JobForm form, BindingResult result) {
        if (result.hasErrors()) { return "jobs/list"; }
        service.save(form);
        return "redirect:/jobs";
    }
}
""",
    f"{JAVA}/web/JobService.java": """
package com.acme.jobs.web;
import java.util.List;
public class JobService {
    public List<JobDto> findAll() { return null; }
    public JobDto find(Long id) { return null; }
    public void save(JobForm f) { }
}
""",
    f"{JAVA}/api/JobApi.java": """
package com.acme.jobs.api;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;
import javax.validation.Valid;
import java.util.List;

@RestController
@RequestMapping("/api/jobs")
public class JobApi {
    @GetMapping
    public List<JobDto> search(@RequestParam(value = "q", required = false) String q,
                               @RequestParam(defaultValue = "0") int page) {
        return null;
    }

    @PostMapping(consumes = "application/json")
    public ResponseEntity<JobDto> create(@Valid @RequestBody CreateJobRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(null);
    }

    @DeleteMapping("/{id}")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<Void> delete(@PathVariable("id") Long id) {
        if (id == null) { throw new JobNotFoundException("missing"); }
        return ResponseEntity.noContent().build();
    }
}
""",
    f"{JAVA}/api/GlobalErrors.java": """
package com.acme.jobs.api;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
@ControllerAdvice
public class GlobalErrors {
    @ExceptionHandler(JobNotFoundException.class)
    @ResponseStatus(HttpStatus.NOT_FOUND)
    public void notFound() { }
}
""",
    f"{JAVA}/api/JobNotFoundException.java": """
package com.acme.jobs.api;
public class JobNotFoundException extends RuntimeException {
    public JobNotFoundException(String m) { super(m); }
}
""",
    f"{JAVA}/api/JobDto.java": """
package com.acme.jobs.api;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.LocalDateTime;
import java.util.List;
public class JobDto {
    private Long id;
    @NotBlank @Size(max = 80) private String name;
    private JobStatus status;
    private List<TaskDto> tasks;
    @JsonProperty("created_at") private LocalDateTime createdAt;
    @JsonIgnore private String internalNote;
}
""",
    f"{JAVA}/api/TaskDto.java": """
package com.acme.jobs.api;
public record TaskDto(String title, boolean done) { }
""",
    f"{JAVA}/api/JobStatus.java": """
package com.acme.jobs.api;
public enum JobStatus { QUEUED, RUNNING, FAILED }
""",
    f"{JAVA}/api/CreateJobRequest.java": """
package com.acme.jobs.api;
public class CreateJobRequest {
    @NotBlank @Size(max = 80, message = "too long") private String name;
    @Min(1) @Max(10) private int priority;
}
""",
    f"{JAVA}/web/JobForm.java": """
package com.acme.jobs.web;
public class JobForm { private String name; private Integer priority; }
""",
    f"{RES}/templates/jobs/list.html": """<!DOCTYPE html>
<html xmlns:th="http://www.thymeleaf.org">
<body>
<form id="jobForm" th:action="@{/jobs/save}" method="post" th:object="${jobForm}">
  <input type="text" th:field="*{name}" required maxlength="80"/>
  <input type="number" th:field="*{priority}" min="1" max="10"/>
  <input type="hidden" name="_csrf" value="x"/>
  <button type="submit">Save</button>
</form>
<table id="jobsTable">
  <thead><tr><th>Name</th><th>Status</th></tr></thead>
  <tbody>
    <tr th:each="job : ${jobs}">
      <td th:text="${job.name}">n</td>
      <td th:text="${job.status}">s</td>
      <td><a th:href="@{/jobs/{id}(id=${job.id})}">View</a></td>
    </tr>
  </tbody>
</table>
<table id="jobsGrid"></table>
<input id="q"/>
<button id="refresh" type="button">Refresh</button>
<button type="button" onclick="deleteJob(1)">Delete</button>
<button id="create" type="button">Create</button>
<script th:src="@{/vendor/jquery/jquery-3.6.0.min.js}"></script>
<script th:src="@{/js/jobs.js}"></script>
</body>
</html>
""",
    f"{RES}/templates/jobs/detail.html": """<!DOCTYPE html>
<html xmlns:th="http://www.thymeleaf.org"><body><h1 th:text="${job.name}">x</h1>
<a href="/jobs">Back</a></body></html>
""",
    f"{RES}/static/js/jobs.js": """
const API = '/api/jobs';
$(function () {
  $('#jobsGrid').DataTable({ ajax: { url: API, type: 'GET' } });
});
$('#refresh').on('click', function () { search($('#q').val()); });
function search(q) { $.get(API, { q: q, page: 0 }); }
function deleteJob(id) { fetch(API + '/' + id, { method: 'DELETE' }); }
document.getElementById('create').addEventListener('click', () => {
  axios.post('/api/jobs', { name: 'x', priority: 1 });
});
fetch('https://other.example.com/api/x');
""",
    f"{RES}/static/vendor/jquery/jquery-3.6.0.min.js": "/* library: never read */ $.ajax({url:'/nope'});",
    "frontend/src/JobPanel.tsx": """
import React, { useEffect } from 'react';
import axios from 'axios';
export function JobPanel({ q }: { q: string }) {
  useEffect(() => { fetch(`/api/jobs?q=${q}`).then(r => r.json()); }, []);
  const remove = (id: number) => axios.delete(`/api/jobs/${id}`);
  return <button onClick={() => remove(1)}>Remove</button>;
}
""",
    "src/main/webapp/WEB-INF/views/orders.jsp": """<%@ taglib prefix="form" uri="http://www.springframework.org/tags/form" %>
<form:form action="${pageContext.request.contextPath}/orders/place" method="post" modelAttribute="orderForm">
  <form:input path="quantity"/>
  <input type="submit" value="Place order"/>
</form:form>
""",
}


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("jobs-app")
    for rel, text in FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def result(repo) -> dict:
    return ui_contracts.scan(str(repo), interfaces.scan(str(repo)))


def _elements(result: dict) -> list[dict]:
    return [e for s in result["screens"] for e in s["elements"]]


def _find(result: dict, **kw) -> dict:
    hits = [e for e in _elements(result) if all(kw[k] in str(e[k]) for k in kw)]
    assert hits, f"no element with {kw}: {[(e['kind'], e['label'], e['event'], e['path']) for e in _elements(result)]}"
    return hits[0]


def _contract(result: dict, endpoint: str) -> dict:
    return next(c for c in result["contracts"] if c["endpoint"] == endpoint)


# ── URL normalisation and matching ──────────────────────────────────────────

@pytest.mark.parametrize("raw, path, query", [
    ("@{/jobs/{id}(id=${job.id})}", "/jobs/{}", []),
    ("@{/search(q=${q},page=1)}", "/search", ["page", "q"]),
    ("${pageContext.request.contextPath}/orders/place", "/orders/place", []),
    ("<c:url value='/orders'/>", "/orders", []),
    ("/api/jobs?q={}&page=2", "/api/jobs", ["page", "q"]),
    ("/api/jobs/{}", "/api/jobs/{}", []),
    ("orders/place", "/orders/place", []),
    ("/api/item-{}", "/api/{}", []),
])
def test_normalize(raw, path, query):
    url = ui_contracts.normalize(raw)
    assert (url.path, url.query) == (path, query)


def test_normalize_absolute_urls():
    assert ui_contracts.normalize("https://other.example.com/api/x").external == "other.example.com"
    assert not ui_contracts.normalize("http://localhost:8080/api/x").external


def test_match_prefers_literal_segments_and_checks_the_method():
    eps = [{"verb": "GET", "path": "/api/jobs/{id}", "handler": "A.one"},
           {"verb": "GET", "path": "/api/jobs/search", "handler": "A.search"},
           {"verb": "ANY", "path": "/legacy", "handler": "L.any"}]
    found, _ = ui_contracts.match(ui_contracts.normalize("/api/jobs/search"), "GET", eps)
    assert [e["handler"] for e in found] == ["A.search"]
    found, _ = ui_contracts.match(ui_contracts.normalize("/api/jobs/{}"), "GET", eps)
    assert [e["handler"] for e in found] == ["A.one"]
    found, reason = ui_contracts.match(ui_contracts.normalize("/api/jobs/7"), "DELETE", eps)
    assert not found and "GET only" in reason
    found, _ = ui_contracts.match(ui_contracts.normalize("/ctx/api/jobs/search"), "GET", eps)
    assert [e["handler"] for e in found] == ["A.search"]          # a leading context path
    assert ui_contracts.match(ui_contracts.normalize("/legacy"), "POST", eps)[0]
    found, reason = ui_contracts.match(ui_contracts.normalize("{}"), "GET", eps)
    assert not found and "run time" in reason


# ── UI side ─────────────────────────────────────────────────────────────────

def test_form_is_tied_to_its_handler_with_fields_and_client_checks(result):
    form = _find(result, kind="form", source="list.html")
    assert form["verb"] == "POST" and form["path"] == "/jobs/save"
    assert form["endpoints"] == ["POST /jobs/save JobController.save"]
    assert '"Save"' in form["label"]
    names = [f[0] for f in form["fields"]]
    assert names == ["name", "priority"]                          # the CSRF token is not a field
    assert form["fields"][0][2] == "required, maxlength=80"
    assert form["fields"][1][2] == "type=number, min=1, max=10"


def test_server_rendered_grid_columns_map_to_model_values(result):
    grid = _find(result, kind="grid", label="#jobsTable")
    assert grid["data"] == "jobs"
    assert [tuple(c) for c in grid["columns"]] == [("Name", "jobs[].name"), ("Status", "jobs[].status")]


def test_link_with_path_variable(result):
    link = _find(result, kind="link", label='"View"')
    assert link["endpoints"] == ["GET /jobs/{id} JobController.detail"]


def test_datatable_grid_loads_from_rest_endpoint(result):
    grid = _find(result, kind="grid", label="#jobsGrid")
    assert grid["event"] == "page load" and grid["endpoints"] == ["GET /api/jobs JobApi.search"]


def test_jquery_binding_reaches_the_call_through_a_named_function(result):
    refresh = _find(result, label="#refresh")
    assert refresh["event"] == "click" and refresh["kind"] == "button"
    assert refresh["sends"] == ["q", "page"]
    assert refresh["endpoints"] == ["GET /api/jobs JobApi.search"]


def test_inline_onclick_handler_in_the_template_names_the_function(result):
    delete = _find(result, via="deleteJob()")
    assert delete["verb"] == "DELETE" and delete["path"] == "/api/jobs/{}"
    assert delete["endpoints"] == ["DELETE /api/jobs/{id} JobApi.delete"]
    assert "list.html" in delete["via"] and delete["label"] == 'button "Delete"'


def test_add_event_listener_and_axios_body(result):
    create = _find(result, label="#create")
    assert create["verb"] == "POST" and create["sends"] == ["name", "priority"]
    assert create["endpoints"] == ["POST /api/jobs JobApi.create"]


def test_react_component_calls(result):
    load = _find(result, source="JobPanel.tsx", event="page load")
    assert load["kind"] == "page load" and load["label"] == "JobPanel.tsx"
    assert load["endpoints"] == ["GET /api/jobs JobApi.search"] and load["query"] == ["q"]
    remove = _find(result, source="JobPanel.tsx", verb="DELETE")
    assert remove["event"] == "click" and 'button "Remove"' in remove["label"]


def test_unmatched_calls_are_listed_with_the_reason(result):
    reasons = {u["call"]: u["reason"] for u in result["unmatched"]}
    assert any("other.example.com" in r for r in reasons.values())
    assert any("orders/place" in c and "no handler" in r for c, r in reasons.items())


def test_vendored_libraries_are_not_read(result):
    assert not any("/nope" in e["url"] for e in _elements(result))


def test_ids_are_stable_and_sequential(repo, result):
    again = ui_contracts.scan(str(repo), interfaces.scan(str(repo)))
    assert ui_contracts.ids(again) == ui_contracts.ids(result)
    assert ui_contracts.ids(result)[0] == "UI-001"
    assert len(set(ui_contracts.ids(result))) == len(ui_contracts.ids(result))


# ── backend side ────────────────────────────────────────────────────────────

def test_rest_contract_request_params(result):
    c = _contract(result, "GET /api/jobs")
    params = {p["name"]: p for p in c["params"]}
    assert params["q"]["required"] == "no" and params["q"]["in"] == "query" and params["q"]["type"] == "string"
    assert params["page"]["required"] == "no" and params["page"]["default"] == "0"


def test_rest_contract_response_schema_is_flattened(result):
    rows = {p: (t, k) for p, t, k in _contract(result, "GET /api/jobs")["response"]}
    assert rows["[].id"][0] == "integer (64-bit)"
    assert rows["[].name"] == ("string", "@NotBlank, @Size(max = 80)")
    assert rows["[].status"][0] == "enum: QUEUED | RUNNING | FAILED"
    assert rows["[].tasks[].title"][0] == "string" and rows["[].tasks[].done"][0] == "boolean"
    assert rows["[].created_at"][0] == "date-time"                    # @JsonProperty name
    assert "[].internalNote" not in rows                               # @JsonIgnore


def test_rest_contract_body_validation_status_and_errors(result):
    c = _contract(result, "POST /api/jobs")
    assert c["consumes"] == "application/json" and c["body_in"] == "JSON body"
    rows = {p: k for p, _, k in c["body"]}
    assert rows == {"name": "@NotBlank, @Size(max = 80)", "priority": "@Min(1), @Max(10)"}
    assert "201 CREATED" in c["statuses"] and c["validation"]
    d = _contract(result, "DELETE /api/jobs/{id}")
    assert d["params"][0]["name"] == "id" and d["params"][0]["in"] == "path"
    assert "204 NO_CONTENT" in d["statuses"]
    assert d["errors"] == [("JobNotFoundException", "404 NOT_FOUND (GlobalErrors.notFound)")]
    assert d["access"] == "@PreAuthorize(\"hasRole('ADMIN')\")"


def test_page_contract_form_object_view_and_model(result):
    save = _contract(result, "POST /jobs/save")
    assert save["body_in"] == "form fields" and [r[0] for r in save["body"]] == ["name", "priority"]
    assert save["redirects"] == ["redirect:/jobs"] and save["view"] == "jobs/list"
    assert any("BindingResult" in v for v in save["validation"])
    page = _contract(result, "GET /jobs")
    model = {k: t for k, t, _ in page["model"]}
    assert model["jobs"] == "list of object (JobDto)" and model["jobForm"] == "object (JobForm)"
    fields = {p: t for p, t, _ in page["model_fields"]}
    assert fields["jobs[].name"] == "string" and fields["jobForm.priority"] == "integer"


def test_screen_lists_the_page_endpoint_that_renders_it(result):
    screen = next(s for s in result["screens"] if s["file"].endswith("jobs/list.html"))
    assert any("GET /jobs (JobController.list)" in x for x in screen["served_by"])
    js = next(s for s in result["screens"] if s["file"].endswith("js/jobs.js"))
    assert js["used_by"] == [f"{RES}/templates/jobs/list.html"]


# ── markdown ────────────────────────────────────────────────────────────────

def test_markdown(result):
    md = ui_contracts.to_markdown(result)
    assert md.startswith(ui_contracts.HEADING)
    assert "| UI-001 |" in md and "#### `POST /api/jobs` — `JobApi.create`" in md
    assert "### Calls not tied to a handler" in md
    assert "**Request JSON body** — `CreateJobRequest`" in md
    assert "| `JobNotFoundException` | 404 NOT_FOUND (GlobalErrors.notFound) |" in md
    assert ui_contracts.to_markdown({"screens": []}) == ""


def test_uncovered(result):
    ids = ui_contracts.ids(result)
    assert ui_contracts.uncovered(result, " ".join(ids[1:])) == [ids[0]]


# ── guardrail on the Architect's UI Interaction Contracts ────────────────────

SPEC = """## Interface Catalog

Untouched `AnythingGoes` here (EV-java-0001).

## UI Interaction Contracts

### Screen jobs/list.html — job list

| Id | Control | Request | Response |
|---|---|---|---|
| UI-001 | Remove button | `DELETE /api/jobs/{id}` with path `id` | 204, empty |
| UI-002 | Search | GET /api/jobs with `q` and `page` | list of `JobDto` |
| UI-003 | Export | GET /api/jobs/export | CSV |
| UI-099 | Ghost | GET /api/jobs | — |

- UI-004: the create button sends `name` (max 80) and `priority` to POST /api/jobs.
- UI-005: the create button sends `name` (max 120) to POST /api/jobs.
- UI-006: shows "Job saved" after the call (EV-js-0001).
- UI-007: shows "Totally invented" after the call.
- UI-008: the list highlights `overdueFlag` rows (EV-js-0001).

### Screen orders.jsp

- UI-012: unresolved — no handler in the code serves `/orders/place`.

## Data Architecture

Kept `Whatever`.
"""


def test_check_ui_section_removes_untraceable_statements(result):
    contracts_md = ui_contracts.to_markdown(result)
    evidence = {"EV-js-0001": "jobs.js shows \"Job saved\" and toggles overdueFlag on late rows"}
    from agents.shared import grounding
    checked, removed = grounding.check_ui_section(SPEC, contracts_md, set(ui_contracts.ids(result)),
                                                  ui_contracts.calls(result), evidence)
    reasons = {s.split()[1] if s.startswith("|") else s.split(":")[0].lstrip("- "): r for s, r in removed}
    assert set(reasons) == {"UI-003", "UI-099", "UI-005", "UI-007"}
    assert "GET /api/jobs/export" in reasons["UI-003"]
    assert "did not find" in reasons["UI-099"]
    assert "120" in reasons["UI-005"]
    assert "Totally invented" in reasons["UI-007"]
    for kept in ("UI-001", "UI-002", "UI-004", "UI-006", "UI-008", "UI-012", "`AnythingGoes`", "`Whatever`",
                 "| Id | Control |"):
        assert kept in checked


def test_check_ui_section_names_in_backticks_must_be_known(result):
    from agents.shared import grounding
    spec = "## UI Interaction Contracts\n\n- UI-001 sends `secretToken` in the body.\n"
    checked, removed = grounding.check_ui_section(spec, ui_contracts.to_markdown(result),
                                                  set(ui_contracts.ids(result)), ui_contracts.calls(result), {})
    assert removed and "`secretToken`" in removed[0][1]
    assert grounding.UI_EMPTIED in checked


def test_check_ui_section_without_the_section_changes_nothing():
    from agents.shared import grounding
    assert grounding.check_ui_section("## Other\n\nx `y`", "", set(), set(), {}) == ("## Other\n\nx `y`", [])


def test_evidence_check_lists_undescribed_ui_elements():
    from agents.shared import evidence_pack
    empty = {"evidence": set(), "rules": set(), "unknown_evidence": [], "unknown_rules": []}
    md = evidence_pack.check_markdown(empty, empty, set(), None, ["UI-002", "UI-005"])
    assert "do not describe (2)" in md and "UI-002, UI-005" in md
    assert "Every UI element found in the code is described" in evidence_pack.check_markdown(empty, empty, set(),
                                                                                             None, [])
