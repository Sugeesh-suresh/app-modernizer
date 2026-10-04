"""UI screens: pages rendered from the repository's own Thymeleaf templates with
sample data read from the code — no model, the same result every run."""
import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from agents import config
from agents.shared import interfaces, ui_mock_data as mock, ui_screens

J = "src/main/java/com/acme"
R = "src/main/resources"

FILES = {
    f"{J}/web/JobController.java": """package com.acme.web;
import com.acme.model.Job;
import com.acme.model.JobType;
import com.acme.service.JobService;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;

@Controller
@RequestMapping("/jobs")
public class JobController {
    private final JobService jobService;

    @GetMapping
    public String list(Model model) {
        model.addAttribute("jobs", jobService.findAll());
        return "jobs/list";
    }

    @GetMapping("/{id}")
    public String detail(@PathVariable Long id, Model model) {
        Job job = jobService.find(id);
        if (job == null) {
            return "redirect:/jobs";
        }
        model.addAttribute("job", job);
        return "jobs/detail";
    }

    @GetMapping("/new")
    public String form(Model model) {
        model.addAttribute("job", new Job());
        model.addAttribute("types", JobType.values());
        return "jobs/form";
    }

    @GetMapping("/legacy")
    public String legacy() { return "legacy/page"; }

    @PostMapping
    public String save(@ModelAttribute Job job) { return "redirect:/jobs?saved"; }
}
""",
    f"{J}/service/JobService.java": """package com.acme.service;
import com.acme.model.Job;
import java.util.List;
public interface JobService { List<Job> findAll(); Job find(Long id); }
""",
    f"{J}/model/BaseEntity.java": """package com.acme.model;
import java.time.LocalDateTime;
public abstract class BaseEntity { private Long id; private LocalDateTime createdAt; }
""",
    f"{J}/model/Job.java": """package com.acme.model;
import java.math.BigDecimal;
import java.util.List;
public class Job extends BaseEntity {
    private String name; private JobType type; private boolean active; private BigDecimal cost;
    private String ownerEmail; private List<Step> steps;
}
""",
    f"{J}/model/Step.java": "package com.acme.model;\npublic record Step(String name, int order) {}\n",
    f"{J}/model/JobType.java": "package com.acme.model;\npublic enum JobType { NIGHTLY, ADHOC, WEEKLY }\n",
    f"{R}/messages.properties": "app.title=Job Scheduler\njobs.title=Scheduled Jobs\njobs.empty=No jobs yet.\n",
    f"{R}/static/css/app.css": "body { font-family: sans-serif; } header { background: #1f3a68; color: #fff; }\n",
    f"{R}/templates/layout.html": """<!DOCTYPE html>
<html xmlns:th="http://www.thymeleaf.org" xmlns:layout="http://www.ultraq.net.nz/thymeleaf/layout">
<head><title th:text="#{app.title}">Jobs</title><link rel="stylesheet" th:href="@{/css/app.css}"/></head>
<body><div th:replace="~{fragments/header :: header}"></div><main layout:fragment="content">x</main></body></html>
""",
    f"{R}/templates/fragments/header.html": """<html xmlns:th="http://www.thymeleaf.org" xmlns:sec="http://www.thymeleaf.org/extras/spring-security">
<header th:fragment="header"><b sec:authentication="name">u</b>
<a sec:authorize="hasRole('ADMIN')" th:href="@{/admin}">Administration</a>
<a sec:authorize="isAuthenticated()" th:href="@{/logout}">Sign out</a></header></html>
""",
    f"{R}/templates/jobs/list.html": """<!DOCTYPE html>
<html xmlns:th="http://www.thymeleaf.org" xmlns:sec="http://www.thymeleaf.org/extras/spring-security"
      xmlns:layout="http://www.ultraq.net.nz/thymeleaf/layout" layout:decorate="~{layout}">
<main layout:fragment="content"><h1 th:text="#{jobs.title}">Jobs</h1>
<div class="alert" th:if="${param.saved}">The job was saved.</div>
<p th:if="${#lists.isEmpty(jobs)}" th:text="#{jobs.empty}">None</p>
<table th:unless="${#lists.isEmpty(jobs)}"><tr th:each="job : ${jobs}">
<td th:text="${job.name}">n</td><td th:text="${job.type}">t</td>
<td th:text="${#temporals.format(job.createdAt, 'yyyy-MM-dd HH:mm')}">d</td>
<td th:text="${#numbers.formatDecimal(job.cost, 1, 2)}">c</td></tr></table></main></html>
""",
    f"{R}/templates/jobs/detail.html": """<!DOCTYPE html>
<html xmlns:th="http://www.thymeleaf.org" xmlns:layout="http://www.ultraq.net.nz/thymeleaf/layout" layout:decorate="~{layout}">
<main layout:fragment="content"><h1 th:text="${job.name}">Job</h1><p th:text="${job.ownerEmail}">o</p>
<ol><li th:each="step : ${job.steps}" th:text="${step.order} + '. ' + ${step.name}">s</li></ol></main></html>
""",
    f"{R}/templates/jobs/form.html": """<!DOCTYPE html>
<html xmlns:th="http://www.thymeleaf.org" xmlns:layout="http://www.ultraq.net.nz/thymeleaf/layout" layout:decorate="~{layout}">
<main layout:fragment="content"><form th:action="@{/jobs}" th:object="${job}" method="post">
<div th:if="${#fields.hasErrors('*')}">Please correct the errors.</div>
<input type="text" th:field="*{name}"/><span th:errors="*{name}">e</span>
<select th:field="*{type}"><option th:each="t : ${types}" th:value="${t}" th:text="${t}">t</option></select>
<input type="checkbox" th:field="*{active}"/></form></main></html>
""",
    f"{R}/templates/login.html": """<!DOCTYPE html>
<html xmlns:th="http://www.thymeleaf.org"><body><h1>Sign in</h1>
<div th:if="${param.error}">Invalid user name or password.</div><input name="username"/></body></html>
""",
    f"{R}/templates/mail/welcome.html": "<!DOCTYPE html><html><body><p th:text=\"${name}\">x</p></body></html>\n",
}


def _app(root: Path, extra: dict | None = None) -> str:
    for rel, text in {**FILES, **(extra or {})}.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return str(root)


def _browser_and_renderer() -> bool:
    status = ui_screens.tools()
    return status["browser"] and status["renderer"]


# ── sample data ─────────────────────────────────────────────────────────────

def test_controller_model_types_come_from_the_code(tmp_path):
    ws = _app(tmp_path)
    classes = mock.index_classes(ws)
    inv = interfaces.scan(ws)
    by_path = {e["path"]: e for e in inv["endpoints"] if e["verb"] == "GET"}
    assert mock.controller_model(ws, by_path["/jobs"]["source"], classes) == {"jobs": "List<Job>"}
    # A local variable, and the early redirect is not the page's view.
    assert by_path["/jobs/{id}"]["view"] == "jobs/detail"
    assert mock.controller_model(ws, by_path["/jobs/{id}"]["source"], classes) == {"job": "Job"}
    # new Job() is an empty form object; JobType.values() is every constant.
    assert mock.controller_model(ws, by_path["/jobs/new"]["source"], classes) == {
        "job": mock.NEW + "Job", "types": "JobType[]"}


def test_values_follow_types_inheritance_and_names(tmp_path):
    ws = _app(tmp_path)
    classes = mock.index_classes(ws)
    jobs = mock.value_for("List<Job>", None, "jobs", classes)
    assert len(jobs) == 3 and [j["type"] for j in jobs] == ["NIGHTLY", "ADHOC", "WEEKLY"]
    first = jobs[0]
    assert first["id"] == 1001 and first["createdAt"] == {"$date": mock.SAMPLE_DATETIME}   # from BaseEntity
    assert first["ownerEmail"] == "user1@example.com" and first["cost"] == 50.99 and first["active"] is True
    assert first["steps"][0] == {"name": "Sample Name 1", "order": 1}                      # a record
    assert mock.value_for(mock.NEW + "Job", None, "job", classes)["name"] is None          # blank form


def test_template_shapes_scope_each_object_and_fragments(tmp_path):
    ws = _app(tmp_path)
    root = Path(ws) / R / "templates"
    facts = mock.read_template(root, "jobs/list")
    assert facts.files == ["jobs/list.html", "layout.html", "fragments/header.html"]
    assert facts.roles == ["ADMIN"] and facts.auth_tests is True
    assert sorted(facts.shapes["jobs"].item.props) == ["cost", "createdAt", "name", "type"]
    assert facts.shapes["jobs"].tested_empty
    form = mock.read_template(root, "jobs/form")
    model = mock.base_model({}, form, {})
    assert set(model) == {"job", "types"}                  # `t` is th:each's own variable on the same element
    assert sorted(model["job"]) == ["active", "name", "type"]


def test_states_cover_the_conditions_in_a_fixed_order(tmp_path):
    ws = _app(tmp_path)
    classes = mock.index_classes(ws)
    facts = mock.read_template(Path(ws) / R / "templates", "jobs/list")
    states = mock.states({"jobs": "List<Job>"}, facts, classes, max_states=10)
    assert [s.name for s in states] == ["default", "no jobs", "`saved` parameter present",
                                        "signed in without roles", "signed out"]
    assert states[0].roles == ["ADMIN"] and states[1].model["jobs"] == []
    assert states[2].model["param"] == {"saved": ["true"]}
    assert states[4].authenticated is False
    assert [s.name for s in mock.states({"jobs": "List<Job>"}, facts, classes, max_states=2)] == ["default", "no jobs"]
    again = mock.states({"jobs": "List<Job>"}, facts, classes, max_states=10)
    assert [s.model for s in again] == [s.model for s in states]


# ── planning ────────────────────────────────────────────────────────────────

def test_plan_lists_controller_pages_then_unnamed_page_templates(tmp_path):
    ws = _app(tmp_path)
    pages, skipped = ui_screens.plan(ws, interfaces.scan(ws))
    assert [(p.template, p.endpoint and p.endpoint["path"]) for p in pages] == [
        ("jobs/list", "/jobs"), ("jobs/detail", "/jobs/{id}"), ("jobs/form", "/jobs/new"), ("login", None)]
    # layout.html, fragments/ and mail/ are not pages; the JSP-style view is reported, not dropped.
    assert skipped == [{"what": "GET /jobs/legacy (JobController.legacy)", "template": "legacy/page",
                        "reason": "no Thymeleaf template with this name (JSP or another view technology)"}]


def test_symbolic_links_are_never_followed(tmp_path):
    secret = tmp_path / "outside.html"
    secret.write_text("<html><body>host file</body></html>")
    ws = _app(tmp_path / "repo")
    os.symlink(secret, Path(ws) / R / "templates" / "leak.html")
    pages, _ = ui_screens.plan(ws, interfaces.scan(ws))
    assert "leak" not in [p.template for p in pages]


def test_custom_template_prefix_is_honoured(tmp_path):
    ws = _app(tmp_path, {f"{R}/application.properties": "spring.thymeleaf.prefix=classpath:/views/\n",
                         f"{R}/views/home.html": "<!DOCTYPE html><html><body>home</body></html>"})
    assert f"{R}/views" in ui_screens.templates_roots(ws)


# ── the offer ───────────────────────────────────────────────────────────────

THYMELEAF = {"pattern": "thymeleaf", "label": "Thymeleaf server-rendered UI", "kind": "web-tier"}
JAVA = {"pattern": "java", "label": "Java application", "kind": "application"}
JSP = {"pattern": "jsp", "label": "JSP / Servlet web tier", "kind": "web-tier"}


def _tools(monkeypatch, browser=True, renderer=True):
    monkeypatch.setattr(ui_screens, "tools", lambda refresh=False: {
        "browser": browser, "renderer": renderer, "java": "java", "chromium": "",
        "notes": [] if browser and renderer else ["Java 17 or later not found"]})


def test_offer_is_silent_without_a_ui_or_when_switched_off(monkeypatch):
    _tools(monkeypatch)
    assert ui_screens.offer([JAVA]) is None
    monkeypatch.setattr(config, "UI_SCREENSHOTS", "off")
    assert ui_screens.offer([THYMELEAF, JAVA]) is None


def test_offer_for_a_renderable_ui(monkeypatch):
    _tools(monkeypatch)
    monkeypatch.setattr(config, "UI_SCREENSHOTS", "offer")
    monkeypatch.setattr(config, "UI_SCREENSHOTS_DEFAULT", False)
    assert ui_screens.offer([THYMELEAF, JAVA]) == {"available": True, "default": False, "stacks": ["thymeleaf"],
                                                   "reason": ""}


def test_offer_explains_what_is_missing(monkeypatch):
    monkeypatch.setattr(config, "UI_SCREENSHOTS", "offer")
    _tools(monkeypatch)
    jsp = ui_screens.offer([JSP, JAVA])
    assert jsp["available"] is False and "Thymeleaf" in jsp["reason"] and "JSP" in jsp["reason"]
    _tools(monkeypatch, browser=False)
    assert ui_screens.offer([THYMELEAF])["available"] is False
    _tools(monkeypatch, renderer=False)
    partial = ui_screens.offer([THYMELEAF])
    assert partial["available"] is True and "static template previews" in partial["reason"]


# ── rendering ───────────────────────────────────────────────────────────────

@pytest.mark.skipif(not Path(config.UI_THYMELEAF_RENDERER).is_file(), reason="Thymeleaf renderer not built")
def test_expressions_cannot_reach_java_classes(tmp_path):
    if not ui_screens.tools()["renderer"]:
        pytest.skip("Java 17+ not available")
    templates = tmp_path / "templates"
    templates.mkdir()
    attacks = {
        "type": "${T(java.lang.Runtime).getRuntime().exec('id')}",
        "getclass": "${''.getClass().forName('java.lang.Runtime')}",
        "constructor": "${new java.lang.ProcessBuilder('id').start()}",
    }
    for name, expr in attacks.items():
        (templates / f"{name}.html").write_text(f'<p th:text="{expr}"></p>')
    (templates / "ok.html").write_text('<p th:text="${greeting}">x</p>')
    spec = {"templates": str(templates), "messages": [], "jobs": [
        {"id": n, "template": n, "model": {"greeting": "hello"}, "out": str(tmp_path / f"{n}.html")}
        for n in [*attacks, "ok"]]}
    results = asyncio.run(ui_screens._run_renderer(tmp_path, 0, spec, 120))
    assert results["ok"]["ok"] and (tmp_path / "ok.html").read_text() == "<p>hello</p>"
    for name in attacks:
        assert results[name]["ok"] is False, name
        assert not (tmp_path / f"{name}.html").exists()


@pytest.mark.skipif(not _browser_and_renderer(), reason="Chromium, Java 17+ or the renderer not available")
def test_capture_renders_every_state_and_is_deterministic(tmp_path):
    ws = _app(tmp_path / "repo")
    inv = interfaces.scan(ws)
    first = asyncio.run(ui_screens.capture(ws, inv, str(tmp_path / "a")))
    second = asyncio.run(ui_screens.capture(ws, inv, str(tmp_path / "b")))
    assert [(s["template"].rsplit("/templates/", 1)[1], s["state"], s["mode"]) for s in first["screens"]] == [
        ("jobs/list.html", "default", "rendered"), ("jobs/list.html", "no jobs", "rendered"),
        ("jobs/list.html", "`saved` parameter present", "rendered"),
        ("jobs/list.html", "signed in without roles", "rendered"),
        ("jobs/detail.html", "default", "rendered"), ("jobs/detail.html", "signed in without roles", "rendered"),
        ("jobs/detail.html", "signed out", "rendered"),
        ("jobs/form.html", "default", "rendered"), ("jobs/form.html", "signed in without roles", "rendered"),
        ("jobs/form.html", "signed out", "rendered"),
        ("login.html", "default", "rendered"), ("login.html", "`error` parameter present", "rendered")]
    assert first["not_rendered"][0]["template"] == "legacy/page"

    def digest(folder):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(folder).glob("*.png"))}
    assert digest(tmp_path / "a") == digest(tmp_path / "b") and len(digest(tmp_path / "a")) == 12
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


@pytest.mark.skipif(not ui_screens.tools()["browser"], reason="Chromium not available")
def test_a_page_the_engine_cannot_render_falls_back_to_a_labelled_preview(tmp_path, monkeypatch):
    ws = _app(tmp_path / "repo", {f"{R}/templates/broken.html":
                                  '<!DOCTYPE html><html><body><p th:text="${a.b(}">Broken</p></body></html>'})
    manifest = asyncio.run(ui_screens.capture(ws, interfaces.scan(ws), str(tmp_path / "out"), max_screens=50))
    broken = next(s for s in manifest["screens"] if s["template"].endswith("broken.html"))
    assert broken["mode"] == "static preview" and broken["note"].startswith("Template engine:")
    assert str(tmp_path) not in broken["note"]                     # no machine paths in the document
    assert broken["model"] == {}


@pytest.mark.skipif(not _browser_and_renderer(), reason="Chromium, Java 17+ or the renderer not available")
def test_screen_limit_lists_what_was_left_out(tmp_path):
    ws = _app(tmp_path / "repo")
    manifest = asyncio.run(ui_screens.capture(ws, interfaces.scan(ws), str(tmp_path / "out"), max_screens=3))
    assert len(manifest["screens"]) == 3
    assert any("screen limit reached" in n["reason"] for n in manifest["not_rendered"])


# ── the document ────────────────────────────────────────────────────────────

MANIFEST = {
    "pages": 1, "notes": [],
    "screens": [
        {"id": "SCR-0001", "image": "SCR-0001.png", "mode": "rendered", "note": "", "state": "default",
         "description": "signed in as sample.user with role ADMIN", "template": f"{R}/templates/jobs/list.html",
         "files": [f"{R}/templates/jobs/list.html"],
         "endpoint": {"verb": "GET", "path": "/jobs", "handler": "JobController.list",
                      "source": f"{J}/web/JobController.java:14"},
         "model": {"jobs": [{"name": "Sample Name 1", "createdAt": {"$date": "2026-01-15T10:30:00"}},
                            {"name": "Sample Name 2", "createdAt": {"$date": "2026-01-15T10:30:00"}}]}},
        {"id": "SCR-0002", "image": "SCR-0002.png", "mode": "rendered", "note": "", "state": "no jobs",
         "description": "`jobs` is empty", "template": f"{R}/templates/jobs/list.html",
         "files": [f"{R}/templates/jobs/list.html"],
         "endpoint": {"verb": "GET", "path": "/jobs", "handler": "JobController.list",
                      "source": f"{J}/web/JobController.java:14"},
         "model": {"jobs": []}},
    ],
    "not_rendered": [{"what": "GET /jobs/legacy (JobController.legacy)", "template": "legacy/page",
                      "reason": "no Thymeleaf template with this name (JSP or another view technology)"}],
}


def test_document_lists_screens_rules_and_what_was_not_rendered():
    ledger = {"rules": [
        {"id": "BR-0001", "sources": [{"path": f"{R}/templates/jobs/list.html", "start": 4, "end": 4}]},
        {"id": "BR-0002", "sources": [{"path": f"{J}/web/JobController.java", "start": 13, "end": 17}]},
        {"id": "BR-0003", "sources": [{"path": f"{J}/web/Other.java", "start": 1, "end": 9}]}]}
    md = ui_screens.to_markdown(MANIFEST, ledger)
    assert md.startswith("## UI Screens") and "not screenshots of a running system" in md
    assert "### `GET /jobs`" in md and "- Handler: `JobController.list`" in md
    assert "![SCR-0001 — default](screens/SCR-0001.png)" in md
    assert "- Rules on this page: BR-0001, BR-0002" in md and "BR-0003" not in md
    assert '"createdAt": "2026-01-15 10:30:00"' in md and "… and 1 more like it" in md
    assert "Sample data: as SCR-0001, with `jobs` = `[]`." in md
    assert "| GET /jobs/legacy (JobController.legacy) | `legacy/page` |" in md
    assert "<" not in md.replace("<!--", "")                       # Markdown only, no HTML
