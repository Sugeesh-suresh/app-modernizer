"""Layered reverse engineering: strategy options, pass batches, and the
deterministic deliverables (OpenAPI 3.0, setup facts, tech debt / dead code)."""
from pathlib import Path

import pytest

from agents.shared import (code_health, interfaces, openapi_spec, re_strategy, setup_facts, stack_detector,
                           system_inventory, ui_contracts)

FIX = Path(__file__).parent / "fixtures"


def _computed(name: str):
    ws = str(FIX / name)
    inv = interfaces.scan(ws)
    ui = ui_contracts.scan(ws, inv)
    sysinv = system_inventory.scan(ws)
    return ws, inv, ui, sysinv


# ── strategies ──────────────────────────────────────────────────────────────

def test_full_stack_repository_recommends_the_layered_trace():
    stacks = [{"pattern": "thymeleaf", "kind": "web-tier"}, {"pattern": "java", "kind": "application"},
              {"pattern": "oracle", "kind": "database"}]
    opts = re_strategy.options(stacks, {"screens": 8, "endpoints": 10, "tables": 5})
    assert opts[0]["id"] == "layered-trace" and opts[0]["recommended"]
    assert opts[0]["passes"] == ["ui", "db", "api"]
    assert {o["id"] for o in opts} == set(re_strategy.STRATEGY_IDS)
    assert all(o["available"] for o in opts)


def test_backend_only_recommends_api_first_and_layered_is_unavailable():
    stacks = [{"pattern": "java", "kind": "application"}, {"pattern": "postgresql", "kind": "database"}]
    opts = {o["id"]: o for o in re_strategy.options(stacks, {"endpoints": 12, "tables": 4})}
    assert opts["api-first"]["recommended"]
    assert not opts["layered-trace"]["available"]
    with pytest.raises(ValueError):
        re_strategy.get("layered-trace", list(opts.values()))


def test_database_centric_repository_recommends_data_first():
    stacks = [{"pattern": "oracle", "kind": "database"}]
    opts = re_strategy.options(stacks, {"tables": 40, "routines": 25})
    assert opts[0]["id"] == "data-first"


def test_no_layers_falls_back_to_stack_by_stack():
    opts = re_strategy.options([{"pattern": "kafka", "kind": "messaging"}], {})
    assert opts[0]["id"] == re_strategy.STACK_BY_STACK and opts[0]["recommended"]
    assert "Reverse-Engineering Strategy Options" in re_strategy.to_markdown(opts)


def test_layers_detected_from_computed_signals_on_a_real_fixture():
    ws, inv, ui, sysinv = _computed("thymeleaf-ui-pages")
    stacks = stack_detector.detect_stacks(ws)
    sig = re_strategy.signals_for(ws, inv, ui, sysinv["database"])
    layers = re_strategy.detect_layers(stacks, sig)
    assert layers["ui"]["present"] and layers["api"]["present"]
    assert sig["screens"] > 0 and sig["endpoints"] > 0


def test_pass_batches_carry_the_computed_starting_points():
    ws, inv, ui, sysinv = _computed("thymeleaf-ui-pages")
    [ui_batch] = re_strategy.ui_batches(ui, [])
    assert "Screens and controls to trace" in ui_batch["request"] and "UI-001" in ui_batch["request"]
    [api_batch] = re_strategy.api_batches(inv, ui, max_classes=50)
    assert "no UI control in this repository calls it" in api_batch["request"]
    assert "called from UI UI-002" in api_batch["request"]
    ws2, _, _, sysinv2 = _computed("arch-inventory")
    [db_batch] = re_strategy.db_batches(sysinv2["database"], ws2)
    assert "TABLE `claim`" in db_batch["request"] and "ClaimRepository.java" in db_batch["request"]
    assert "dead-data candidate" not in db_batch["request"].split("TABLE `claim`")[1].split("###")[0]


# ── OpenAPI 3.0 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture", ["thymeleaf-ui-pages", "pds-react", "thymeleaf-rules"])
def test_openapi_document_is_valid_openapi_3(fixture):
    validator = pytest.importorskip("openapi_spec_validator")
    _, _, ui, _ = _computed(fixture)
    doc = openapi_spec.build(ui["contracts"], "Test API")
    validator.validate(doc)
    assert doc["openapi"] == "3.0.3"
    assert len([op for p in doc["paths"].values() for op in p.values()]) == len(ui["contracts"])


def test_openapi_carries_parameters_constraints_errors_and_access_rules():
    _, _, ui, _ = _computed("thymeleaf-ui-pages")
    doc = openapi_spec.build(ui["contracts"], "Orders")
    cancel = doc["paths"]["/api/orders/{id}/cancel"]["post"]
    assert cancel["parameters"][0] == {"name": "id", "in": "path", "required": True,
                                       "schema": {"type": "integer", "format": "int64"}}
    assert "409" in cancel["responses"] and "OrderNotOpenException" in cancel["responses"]["409"]["description"]
    assert cancel["x-access-rule"].startswith("@PreAuthorize") and "403" in cancel["responses"]
    form = doc["paths"]["/orders"]["post"]
    body = form["requestBody"]["content"]["application/x-www-form-urlencoded"]["schema"]
    schema = doc["components"]["schemas"][body["$ref"].rsplit("/", 1)[-1]]
    assert schema["properties"]["quantity"]["minimum"] == 1 and schema["properties"]["quantity"]["maximum"] == 50
    assert schema["properties"]["customer"]["maxLength"] == 80
    assert set(schema["required"]) >= {"customer", "quantity"}
    assert schema["properties"]["email"]["format"] == "email"
    assert "text/html" in form["responses"]["200"]["content"]


def test_openapi_yaml_round_trips():
    import yaml
    _, _, ui, _ = _computed("pds-react")
    doc = openapi_spec.build(ui["contracts"], "PDS")
    assert yaml.safe_load(openapi_spec.to_yaml(doc)) == doc
    paged = doc["paths"]["/api/attributes"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    page = doc["components"]["schemas"][paged["$ref"].rsplit("/", 1)[-1]]
    assert page["properties"]["content"]["type"] == "array"


def test_flattened_fields_nest_into_objects_and_arrays():
    s = openapi_spec.object_schema([("items[].sku", "string", "@NotBlank"), ("items[].qty", "integer", ""),
                                    ("customer.name", "string", ""), ("tags", "list of string", "")])
    assert s["properties"]["items"]["type"] == "array"
    assert s["properties"]["items"]["items"]["properties"]["sku"]["minLength"] == 1
    assert s["properties"]["items"]["items"]["required"] == ["sku"]
    assert s["properties"]["customer"]["properties"]["name"]["type"] == "string"
    assert s["properties"]["tags"] == {"type": "array", "items": {"type": "string"}}


# ── setup facts ─────────────────────────────────────────────────────────────

def test_setup_facts(tmp_path):
    (tmp_path / "pom.xml").write_text("<project><packaging>war</packaging><properties><java.version>17</java.version>"
                                      "</properties><build><plugins><plugin><artifactId>spring-boot-maven-plugin"
                                      "</artifactId></plugin></plugins></build></project>")
    (tmp_path / "mvnw").write_text("#!/bin/sh")
    res = tmp_path / "src/main/resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text("server:\n  port: 8081\nspring:\n  datasource:\n    url: ${DB_URL}\n"
                                         "    password: ${DB_PASSWORD:changeme}\n")
    (res / "application-prod.yml").write_text("feature: on\n")
    (tmp_path / "Dockerfile").write_text("FROM eclipse-temurin:17-jre\nEXPOSE 8081\nENTRYPOINT [\"java\",\"-jar\",\"/app.jar\"]\n")
    (tmp_path / "docker-compose.yml").write_text("services:\n  db:\n    image: postgres:15\n    ports: ['5432:5432']\n"
                                                 "  app:\n    build: .\n    depends_on: [db]\n    environment:\n"
                                                 "      DB_URL: jdbc:postgresql://db/app\n")
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/ci.yml").write_text("jobs:\n  build:\n    steps:\n      - name: Build with Maven\n")
    src = tmp_path / "src/main/java/a"
    src.mkdir(parents=True)
    (src / "A.java").write_text('class A { String k = System.getenv("API_KEY"); }')
    facts = setup_facts.scan(str(tmp_path))
    assert {"purpose": "build", "command": "./mvnw clean package", "dir": ".", "source": "pom.xml"} in facts["commands"]
    assert any(c["command"] == "./mvnw spring-boot:run" for c in facts["commands"])
    assert {"runtime": "Java", "version": "17", "where": "pom.xml:1"} in facts["runtimes"]
    assert any(p["port"].startswith("8081 (server.port)") for p in facts["ports"])
    env = {e["name"]: e["kind"] for e in facts["env"]}
    assert "no default" in env["DB_URL"] and "default `[REDACTED]`" in env["DB_PASSWORD"]
    assert env["API_KEY"] == "environment variable"
    assert {s["service"] for s in facts["compose"]} == {"db", "app"}
    assert facts["profiles"][0]["profile"] == "prod"
    md = setup_facts.to_markdown(facts)
    assert "changeme" not in md and "### CI/CD pipelines" in md and ".github/workflows/ci.yml" in md


# ── tech debt and dead code ─────────────────────────────────────────────────

def test_code_health_finds_dead_code_and_debt(tmp_path):
    src = tmp_path / "src/main/java/com/a"
    src.mkdir(parents=True)
    (src / "Used.java").write_text(
        "package com.a;\n@Service\npublic class Used {\n"
        "  private void helper() {}\n"
        "  private void called() {}\n"
        "  public void run() { called(); try { x(); } catch (Exception e) { }\n"
        "    String q = \"SELECT * FROM t WHERE id=\" + id;\n"
        "    System.out.println(q); // TODO remove this\n"
        "  }\n}\n")
    (src / "Orphan.java").write_text("package com.a;\npublic class Orphan {\n}\n")
    (src / "Repo.java").write_text("package com.a;\npublic interface Repo extends JpaRepository<Used, Long> {\n"
                                   "  java.util.List<Used> findByName(String n);\n}\n")
    res = tmp_path / "src/main/resources"
    res.mkdir(parents=True)
    (res / "application.properties").write_text("db.password=hunter2\nspring.jpa.hibernate.ddl-auto=update\n")
    found = code_health.scan(str(tmp_path))
    dead = {(r["category"], r["item"]) for r in found["dead"]}
    assert ("Class referenced by nothing", "Orphan") in dead
    assert ("Class referenced by nothing", "Used") not in dead            # @Service
    assert ("Private method never called", "helper") in dead
    assert ("Private method never called", "called") not in dead
    assert ("Repository method never called", "findByName") in dead
    debt = {r["category"] for r in found["debt"]}
    assert {"Marked in code: TODO", "Exception caught and ignored (empty catch)", "Broad catch (Exception / Throwable)",
            "SQL built by string concatenation (injection risk)", "Console output instead of logging",
            "Credential written in configuration", "Schema changed automatically at start-up"} <= debt
    md = code_health.to_markdown(found, [("EV-ui-0003", "OrderService.legacyTotal is reached by no flow")])
    assert "hunter2" not in md and "| Decision |" in md and "EV-ui-0003" in md


def test_rest_endpoints_no_ui_calls_are_candidates_only_when_the_repository_has_a_ui():
    ws, inv, ui, sysinv = _computed("thymeleaf-ui-pages")
    found = code_health.scan(ws, ui, sysinv["database"])
    uncalled = [r for r in found["dead"] if r["category"] == "REST endpoint no UI control calls"]
    called = {c["endpoint"] for c in ui["contracts"] if c.get("called_by")}
    assert all(r["item"] not in called for r in uncalled)
    assert not [r for r in code_health.scan(ws, {"screens": []})["dead"]
                if r["category"] == "REST endpoint no UI control calls"]


# ── UI pages: elements, interactions and backend traces ────────────────────

from agents.shared import ui_page_traces, ui_pages  # noqa: E402


def test_ui_pages_document_lists_every_page_in_route_order_with_its_elements_and_traces():
    ws, inv, ui, _ = _computed("thymeleaf-ui-pages")
    pages = ui_page_traces.build(ws, ui)
    order = [p["file"].rsplit("/templates/", 1)[1] for p in pages]
    assert order == ["dashboard/attribute_search.html", "orders/list.html", "orders/form.html", "orders/detail.html",
                     "selfservicetool/job_list.html", "fragments/header.html", "layouts/main.html"]
    listing = next(p for p in pages if p["file"].endswith("orders/list.html"))
    assert listing["id"] == "PG-02" and {f.rsplit("/", 1)[1] for f in listing["includes"]} == {"header.html", "main.html"}
    tags = [(r["tag"], r["attrs"].get("id")) for r in listing["elements"]]
    assert ("button", "filtersBtn") in tags and ("input", "quickJump") in tags     # no request: still listed
    md = ui_page_traces.to_markdown(pages, ui, {"UI-002": "- **UI-002** — Cancels the order (EV-ui-0001)."},
                                    {"EV-ui-0009": "OrderApiController.cancel sets status CANCELLED in table orders"},
                                    {listing["file"]: ["SCR-0003"]}, "Orders",
                                    ui_pages.to_markdown(ui_pages.scan(ws, inv, ui)))
    section = md.split("### PG-02")[1].split("### PG-03")[0]
    assert "opens modal `#filterModal` (in the browser, no request)" in section
    assert "| UI-002 | button .cancel-btn | click | Ajax — jQuery `$.post` | `POST /api/orders/{}/cancel` |" in section
    cancel = section.split("##### UI-002")[1].split("#####")[0]
    assert "**Purpose:** Cancels the order (EV-ui-0001)." in cancel
    assert "`OrderApiController.cancel` serving `POST /api/orders/{id}/cancel`" in cancel
    assert "Errors:" in cancel and "OrderNotOpenException" in cancel and "Access rule:" in cancel
    assert "sets status CANCELLED in table orders (EV-ui-0009)" in cancel          # traced downstream
    assert "SCR-0003" in section and "#### Interactive components and what each action does" in section
    assert "Endpoint Contracts →" not in md                                           # self-contained
    form = md.split("### PG-03")[1].split("### PG-04")[0]
    assert "HTML form submission (full page request)" in form and "_(computed)_" in form


def test_ui_pages_covers_single_page_applications_by_route():
    ws, _, ui, _ = _computed("pds-react")
    pages = ui_page_traces.build(ws, ui)
    by_file = {p["file"]: p for p in pages}
    search = by_file["pds-ui/src/pages/AttributeSearch.jsx"]
    assert search["routes"] == ["route /attribute_search"] and search["id"] == "PG-01"
    assert any(r["tag"] == "table" and r["attrs"].get("id") == "attributeGrid" for r in search["elements"])
    md = ui_page_traces.to_markdown(pages, ui)
    assert "Ajax — HTTP client `api.get`" in md and "`AttributeController.searchAttributes`" in md


def test_soap_operations_default_address_sun_jaxws_and_excluded_methods(tmp_path):
    src = tmp_path / "src/main/java/a"
    src.mkdir(parents=True)
    (src / "QuoteEndpoint.java").write_text(
        "package a;\n@Endpoint\npublic class QuoteEndpoint {\n"
        "  @SoapAction(\"http://a/Quote\")\n  @ResponsePayload\n"
        "  public QuoteResponse quote(@RequestPayload QuoteRequest r) { return null; }\n}\n")
    (src / "Legacy.java").write_text(
        "package a;\n@WebService\npublic class Legacy {\n  public String ping() { return \"x\"; }\n"
        "  @WebMethod(exclude = true)\n  public void internal() {}\n  private void hidden() {}\n}\n")
    web = tmp_path / "src/main/webapp/WEB-INF"
    web.mkdir(parents=True)
    (web / "sun-jaxws.xml").write_text('<endpoints><endpoint name="l" implementation="a.Legacy" '
                                       'url-pattern="/legacy"/></endpoints>')
    from agents.shared import interfaces
    ops = {o["operation"]: o for o in interfaces.scan(str(tmp_path))["soap"]}
    assert set(ops) == {"http://a/Quote", "ping"}
    assert ops["http://a/Quote"]["address"] == "/services/* (Spring Boot default)"
    assert ops["ping"]["service"] == "LegacyService" and ops["ping"]["address"] == "/legacy"
    md = interfaces.to_markdown(interfaces.scan(str(tmp_path)))
    assert "### SOAP operations (2)" in md
