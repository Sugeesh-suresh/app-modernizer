"""The Gemini CLI path (cli/): the pipeline state machine and the MCP tools,
driven end to end with the subagents' outputs written by the test."""
import json
import subprocess
import sys
from pathlib import Path

import anyio
import pytest

from cli import discovery, mcp_server, pipeline
from cli.runstate import Run, RunError

BACKEND = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"

SOLR_SCHEMA = """<?xml version="1.0"?>
<schema name="x" version="1.5">
  <fieldType name="int" class="solr.TrieIntField"/>
  <field name="id" type="string" indexed="true" stored="true"/>
</schema>
"""

PLAN = """# Migration Plan

## 1. What Changes
### File Change Manifest
| File | Change |
|---|---|
| `conf/schema.xml` | Trie -> Point |
"""


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MODERNIZER_WORKSPACE", raising=False)


def _solr_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "solr"
    (repo / "conf").mkdir(parents=True)
    (repo / "conf" / "schema.xml").write_text(SOLR_SCHEMA)
    # luceneMatchVersion already moved (8.x is accepted by Solr 9): this run's plan is only Trie -> Point.
    (repo / "conf" / "solrconfig.xml").write_text("<config><luceneMatchVersion>8.11.2</luceneMatchVersion></config>")
    return repo


def _save(repo: Path, step_id: str, text: str) -> None:
    assert _tool(mcp_server.save_output, step_id=step_id, content=text, workspace=str(repo)).startswith("Saved")


def _tool(fn, **kwargs) -> str:
    return anyio.run(lambda: fn(**kwargs))


def _next(repo: Path) -> dict:
    step, _ = pipeline.next_step(Run.load(repo))
    return step


def test_solr_run_end_to_end(tmp_path, monkeypatch):
    from agents.shared import callbacks
    monkeypatch.setattr(callbacks, "_LEARNING_ENABLED", True)      # learning on: still no curation step
    repo = _solr_repo(tmp_path)
    run = pipeline.start(repo, "solr-4-to-9")
    assert Path(run.state["baseline_dir"], "conf", "schema.xml").is_file()

    # The inventory runs without a model; the planner is the first agent.
    step = _next(repo)
    assert step["id"] == "plan-solr-4-to-9" and step["subagent"] == "modernizer-planner"
    assert "`solr-4-to-9` skill" in step["query"] and "references/steps/plan.md" in step["query"] and ".modernizer/docs/solr-4-to-9/technical_spec.md" in step["query"]
    assert "Solr" in Run.load(repo).read_doc("technical_spec")

    # Nothing may be written before the plan is approved.
    assert "No plan is approved" in _tool(mcp_server.ws_write_file, path="x.txt", content="x", workspace=str(repo))

    with pytest.raises(RunError):
        pipeline.complete_step(Run.load(repo), step["id"])          # nothing saved yet
    _save(repo, step["id"], PLAN)
    msg = pipeline.complete_step(Run.load(repo), step["id"])
    assert "Plan saved" in msg
    plan = Run.load(repo).read_doc("plan")
    assert "Plan Completeness Check" in plan                         # the contract check ran

    gate = _next(repo)
    assert gate["kind"] == "review_gate" and gate["id"] == "plan-review"
    with pytest.raises(RunError):
        pipeline.confirm(Run.load(repo), "analysis")                 # wrong gate
    pipeline.confirm(Run.load(repo), "plan")

    modify = _next(repo)
    assert modify["subagent"] == "modernizer-coder" and "references/steps/modify.md" in modify["query"]
    # The coder writes through the MCP tools; .modernizer is off limits.
    assert "save_output" in _tool(mcp_server.ws_write_file, path=".modernizer/run.json", content="{}",
                                  workspace=str(repo))
    out = _tool(mcp_server.ws_replace_in_file, path="conf/schema.xml", old_text="solr.TrieIntField",
                new_text="solr.IntPointField", workspace=str(repo))
    assert not out.startswith("ERROR"), out
    _save(repo, modify["id"], "Changed conf/schema.xml.")
    pipeline.complete_step(Run.load(repo), modify["id"])

    validate = _next(repo)
    assert validate["subagent"] == "modernizer-validator"
    report = _tool(mcp_server.ws_validate, workspace=str(repo))
    assert "OVERALL: no issues found." in report
    assert "recorded" in _tool(mcp_server.ws_signal_build_success, workspace=str(repo))
    _save(repo, validate["id"], '{"passed": true, "errors": [], "summary": "clean"}')
    assert "PASSED" in pipeline.complete_step(Run.load(repo), validate["id"])

    review = _next(repo)
    assert review["subagent"] == "modernizer-reviewer"
    audit = _tool(mcp_server.ws_audit_changes, workspace=str(repo))
    assert "schema.xml" in audit
    _save(repo, review["id"], "Looks right.")
    pipeline.complete_step(Run.load(repo), review["id"])

    report_step = _next(repo)
    assert report_step["subagent"] == "modernizer-writer" and "references/steps/report.md" in report_step["query"]
    _save(repo, report_step["id"], "# Report")
    pipeline.complete_step(Run.load(repo), report_step["id"])

    done = _next(repo)                       # the report is the last step: no skill-curation step follows
    assert done["kind"] == "done" and not str(done.get("id", "")).startswith("curate")
    assert Run.load(repo).state["pi"] == 1
    changes = (repo / ".modernizer" / "results" / "changes.md").read_text()
    assert "`conf/schema.xml`" in changes and ".modernizer" not in changes.split("|---|---|")[1]


def test_failed_validation_goes_to_the_fixer_then_back(tmp_path):
    repo = _solr_repo(tmp_path)
    pipeline.start(repo, "solr-4-to-9")
    step = _next(repo)
    _save(repo, step["id"], PLAN)
    pipeline.complete_step(Run.load(repo), step["id"])
    _next(repo)
    pipeline.confirm(Run.load(repo), "plan")
    modify = _next(repo)
    _save(repo, modify["id"], "nothing")
    pipeline.complete_step(Run.load(repo), modify["id"])
    validate = _next(repo)
    # A JSON "passed" without the gate is not a pass.
    _save(repo, validate["id"], '{"passed": true, "errors": []}')
    assert "FAILED" in pipeline.complete_step(Run.load(repo), validate["id"])
    fix = _next(repo)
    assert fix["id"].startswith("fix-") and "references/steps/fix.md" in fix["query"]
    assert "build_result.json" in fix["query"]
    _save(repo, fix["id"], "fixed\n\n## Lessons\n")
    pipeline.complete_step(Run.load(repo), fix["id"])
    assert _next(repo)["id"].startswith("validate-solr-4-to-9-2")


def test_refine_plan_reruns_the_planner_with_feedback(tmp_path):
    repo = _solr_repo(tmp_path)
    pipeline.start(repo, "solr-4-to-9")
    step = _next(repo)
    _save(repo, step["id"], PLAN)
    pipeline.complete_step(Run.load(repo), step["id"])
    _next(repo)
    pipeline.refine(Run.load(repo), "plan", "Keep the managed schema.")
    again = _next(repo)
    assert again["id"] == "plan-solr-4-to-9" and "Keep the managed schema." in again["query"]
    assert "Previous plan" in again["query"]


def test_java11_writes_go_through_the_scope_fence(tmp_path):
    repo = tmp_path / "app"
    (repo / "src/main/webapp/WEB-INF").mkdir(parents=True)
    (repo / "src/main/java/a").mkdir(parents=True)
    (repo / "src/main/webapp/index.jsp").write_text("<html/>")
    (repo / "src/main/java/a/A.java").write_text("package a;\nclass A {}\n")
    (repo / "pom.xml").write_text("<project><packaging>war</packaging></project>")
    run = pipeline.start(repo, "java-8-to-11")
    run.state.update({"plan_approved": True, "current_pattern": "java-8-to-11"})
    run.save()
    refused = _tool(mcp_server.ws_write_file, path="src/main/webapp/index.jsp", content="x", workspace=str(repo))
    assert refused.startswith("ERROR: refused")
    ok = _tool(mcp_server.ws_replace_in_file, path="src/main/java/a/A.java", old_text="class A {}",
               new_text="class A { }", workspace=str(repo))
    assert not ok.startswith("ERROR"), ok
    jakarta = _tool(mcp_server.ws_replace_in_file, path="src/main/java/a/A.java", old_text="package a;\n",
                    new_text="package a;\nimport jakarta.servlet.Servlet;\n", workspace=str(repo))
    assert jakarta.startswith("ERROR: refused")


def test_incremental_java25_runs_one_unit_per_task_per_stage(tmp_path):
    repo = tmp_path / "j"
    (repo / "src").mkdir(parents=True)
    (repo / "pom.xml").write_text("<project/>")
    run = pipeline.start(repo, "java-8-to-25", migration_strategy="incremental")
    plan = ("## Stage 1: Modernize Build Systems (Maven/Gradle)\n\n### Task 1.1: Wrapper\n- Files: `pom.xml`\n\n"
            "### Task 1.2: Surefire\n- Files: `pom.xml`\n\n## Stage 3: Java 8 → Java 17 LTS\n\n### Task 3.1: Release\n"
            "- Files: `pom.xml`\n")
    run.write_doc("plan", plan)
    run.state.update({"phase": "code", "plan_approved": True, "pi": 0, "code": None})
    run.save()
    first = _next(repo)
    assert first["id"] == "modify-java-8-to-25-stage1-1.1"
    assert "Guardrail for this stage" in first["query"] and "references/steps/readiness.md" in first["query"]
    _save(repo, first["id"], "done")
    pipeline.complete_step(Run.load(repo), first["id"])
    assert _next(repo)["id"] == "modify-java-8-to-25-stage1-1.2"


def test_companion_selection_is_a_gate(tmp_path):
    repo = tmp_path / "j"
    (repo / "src/main/resources").mkdir(parents=True)
    (repo / "pom.xml").write_text("<project><dependencies><dependency><groupId>com.oracle</groupId>"
                                  "<artifactId>ojdbc6</artifactId></dependency></dependencies></project>")
    (repo / "src/main/resources/app.properties").write_text("url=jdbc:oracle:thin:@db:1521:ORCL\n")
    run = pipeline.start(repo, "java-8-to-25")
    if not run.state["recommendations"]:
        pytest.skip("no companion detected for this fixture")
    step = _next(repo)
    assert step["kind"] == "ask_user"
    with pytest.raises(RunError):
        pipeline.confirm(Run.load(repo), "companions", ["solr-4-to-9"] if "solr-4-to-9" not in
                         {r["pattern"] for r in run.state["recommendations"]} else ["nope"])
    pipeline.confirm(Run.load(repo), "companions", [])
    assert Run.load(repo).state["bundle"] == ["java-8-to-25"]


def test_stack_discovery_end_to_end(tmp_path, monkeypatch):
    import shutil
    repo = tmp_path / "shop"
    shutil.copytree(FIXTURES / "thymeleaf-rules", repo)
    pipeline.start(repo, "stack-discovery")
    mapper = _next(repo)
    assert mapper["id"] == "mapper" and "dependency-mapper" in mapper["query"]
    _save(repo, "mapper", "# Technology Stack Inventory\n\nNothing to add.\n\n```json\n{\"stacks\": [], \"rejected\": []}\n```")
    pipeline.complete_step(Run.load(repo), "mapper")
    gate = _next(repo)
    assert gate["kind"] == "ask_user"
    stacks = [s["pattern"] for s in Run.load(repo).state["recommendations"]]
    assert "java" in stacks
    pipeline.confirm(Run.load(repo), "stacks", ["java"], ["brd", "technical_spec", "test_inventory"])
    strategy = _next(repo)
    assert strategy["id"] == "select-strategy" and strategy["kind"] == "ask_user"
    with pytest.raises(RunError):
        pipeline.confirm(Run.load(repo), "strategy", ["no-such-strategy"])
    pipeline.confirm(Run.load(repo), "strategy", ["stack-by-stack"])

    ev = _next(repo)
    assert ev["id"] == "evidence-java" and "stack-discovery-re" in ev["query"]
    _save(repo, "evidence-java", "## Components\n- `OrderController` handles orders "
                                 "(src/main/java/com/acme/shop/web/OrderController.java:1)\n\n"
                                 "## Business Behaviour\n- Orders are listed and submitted through a form "
                                 "(src/main/java/com/acme/shop/web/OrderController.java:1)\n\n"
                                 "## Limitations\n- none\n")
    pipeline.complete_step(Run.load(repo), "evidence-java")
    pack = (repo / ".modernizer/discovery/evidence/java.md").read_text()
    assert "EV-" in pack                                           # numbered by the pipeline

    po = _next(repo)
    assert po["id"] == "po_brd" and "as-is-brd" in po["query"]
    request = (repo / ".modernizer/discovery/requests/po_brd.md").read_text()
    assert "## Evidence" in request and "EV-" in request
    _save(repo, "po_brd", "# BRD\n\n## Executive Summary\nThe shop takes orders.\n")
    pipeline.complete_step(Run.load(repo), "po_brd")
    ea = _next(repo)
    assert ea["id"] == "ea_spec"
    _save(repo, "ea_spec", "# Technical Specification\n\n## Architecture Overview\nOne Spring MVC app. We recommend "
                           "migrating to Java 25.\n")
    pipeline.complete_step(Run.load(repo), "ea_spec")
    step = _next(repo)
    while step["kind"] in ("subagent", "parallel") and _members(step)[0]["id"].startswith("ea-ui"):
        _answer(repo, step, lambda sid: "No controls.")
        step = _next(repo)
    assert step["id"] in ("ea_diagrams",)
    _save(repo, "ea_diagrams", '{"diagrams": []}')
    pipeline.complete_step(Run.load(repo), "ea_diagrams")
    if (step := _next(repo))["id"] == "ea_diagrams-retry":
        _save(repo, step["id"], '{"diagrams": []}')
        pipeline.complete_step(Run.load(repo), step["id"])
        step = _next(repo)
    assert step["id"] == "documents-review"
    run = Run.load(repo)
    spec = run.read_doc("technical_spec", "stack-discovery")
    assert "Interface & Job Inventory" in spec or "Endpoint" in spec      # computed sections placed
    assert "migrating to Java 25" not in spec                             # migration advice scrubbed
    assert run.read_doc("evidence", "stack-discovery")
    assert "confirmed" in discovery.confirm(run, "documents", None, None)
    assert _next(repo)["kind"] == "done"


def _members(step: dict) -> list[dict]:
    """The subagent steps a step stands for: itself, or the members of a parallel group."""
    return step["members"] if step["kind"] == "parallel" else [step]


def _answer(repo: Path, step: dict, text_for) -> None:
    """Save and complete every subagent step `step` stands for, as Gemini CLI does for a group: all saved,
    then each completed."""
    members = _members(step)
    for m in members:
        _save(repo, m["id"], text_for(m["id"]))
    for m in members:
        pipeline.complete_step(Run.load(repo), m["id"])


def _drive_writers(repo: Path, outputs: dict[str, str]) -> dict:
    """Answer every subagent step until a non-subagent step, with `outputs` by step-id prefix."""
    step = _next(repo)
    while step["kind"] in ("subagent", "parallel"):
        _answer(repo, step, lambda sid: next((v for k, v in outputs.items() if sid.startswith(k)), "None found."))
        step = _next(repo)
    return step


def test_layered_trace_strategy_produces_every_deliverable(tmp_path):
    import json as _json
    import shutil
    repo = tmp_path / "orders"
    shutil.copytree(FIXTURES / "thymeleaf-ui-pages", repo)
    pipeline.start(repo, "stack-discovery")
    assert _next(repo)["id"] == "mapper"
    _save(repo, "mapper", "Nothing to add.\n\n```json\n{\"stacks\": [], \"rejected\": []}\n```")
    pipeline.complete_step(Run.load(repo), "mapper")
    _next(repo)
    stacks = [s["pattern"] for s in Run.load(repo).state["recommendations"]]
    pipeline.confirm(Run.load(repo), "stacks", stacks, None)            # default documents: all six
    gate = _next(repo)
    assert gate["id"] == "select-strategy"
    run = Run.load(repo)
    offered = {o["id"]: o for o in run.state["strategy_options"]}
    assert offered["layered-trace"]["recommended"] and offered["layered-trace"]["passes"] == ["api", "ui", "db"]
    assert "Reverse-Engineering Strategy Options" in (repo / ".modernizer/discovery/strategy.md").read_text()
    pipeline.confirm(Run.load(repo), "strategy", ["layered-trace"])

    # The API pass runs first and traces each handler once, down to the data store.
    api_step = _next(repo)
    assert api_step["id"] == "layer-api-1" and "`layer-api-logic`" in api_step["query"]
    api_pack = ("### Flow Traces\n- `GET /api/orders/{id}/status` → `OrderApiController.status` "
                "(src/main/java/com/acme/orders/api/OrderApiController.java:18) → reads ORDERS.status\n\n"
                "### Business Behaviour\n- OrderApiController.status answers 404 for an unknown order "
                "(src/main/java/com/acme/orders/api/OrderApiController.java:18)\n\n### Limitations\nNone found.\n")
    while _members(api_step)[0]["id"].startswith("layer-api-"):
        _answer(repo, api_step, lambda sid: api_pack)
        api_step = _next(repo)
    # The UI pass gets the index of its endpoints' traces and reads only the UI side. Its batches are
    # independent, so they are handed out together (DISCOVERY_CONCURRENCY at a time).
    ui_members = _members(api_step)
    assert [m["id"] for m in ui_members][:1] == ["layer-ui-1"]
    ui_step = ui_members[0]
    assert "`layer-ui-trace`" in ui_step["query"]
    assert ".modernizer/discovery/evidence/api.md" in ui_step["query"]
    ui_request = (repo / ".modernizer/discovery/layers/ui/request-0001.md").read_text()
    assert "UI-001" in ui_request
    assert "## Endpoint traces from the API pass" in ui_request
    assert "`GET /api/orders/{id}/status` → `OrderApiController.status`: trace EV-api-0001; also EV-api-0002" \
        in ui_request
    assert "**no trace** from the API pass" in ui_request          # endpoints the stand-in API pack left out
    pack = ("### Flow Traces\n- UI-002 cancel → POST /api/orders/{id}/cancel → OrderApiController.cancel "
            "(src/main/java/com/acme/orders/api/OrderApiController.java:18)\n\n"
            "### Business Behaviour\n- An open order can be cancelled "
            "(src/main/java/com/acme/orders/api/OrderApiController.java:18)\n\n"
            "### Tech Debt & Dead Code\n- DashboardController.attributeSearch page is reached by no flow "
            "(src/main/java/com/acme/orders/web/DashboardController.java:9)\n\n### Limitations\nNone found.\n")
    step = _drive_writers(repo, {"layer-": pack, "po_brd": "## Executive Summary\nOrders are managed.\n",
                                 "ea_spec": "## Architecture Overview\nOne Spring MVC application.\n",
                                 "ea_diagrams": '{"diagrams": []}',
                                 "setup": "## Prerequisites\nA JDK (pom.xml).\n"})
    assert step["id"] == "documents-review"
    run = Run.load(repo)
    # the db pass had nothing computed to start from and no data stack: it is recorded, not asked
    assert (repo / ".modernizer/discovery/evidence/db.md").read_text().startswith("### Limitations")
    assert "EV-ui-0001" in (repo / ".modernizer/discovery/evidence/ui.md").read_text()
    out = repo / ".modernizer/deliverables"
    names = {p.name for p in out.iterdir()}
    assert {"README.md", "SETUP.md", "BRD.md", "TECHNICAL_SPECIFICATION.md", "TECH_DEBT_AND_DEAD_CODE.md",
            "openapi.yaml", "openapi.json", "STRATEGY.md", "EVIDENCE.md"} <= names
    spec = _json.loads((out / "openapi.json").read_text())
    assert spec["openapi"] == "3.0.3" and "/api/orders/{id}/cancel" in spec["paths"]
    debt = (out / "TECH_DEBT_AND_DEAD_CODE.md").read_text()
    assert "Layered trace" in debt and "EV-ui-" in debt and "reached by no flow" in debt
    assert "## Setup & Deployment Facts (computed)" in (out / "SETUP.md").read_text()
    assert "# Existing Test Inventory" in (out / "TECHNICAL_SPECIFICATION.md").read_text()
    index = (out / "README.md").read_text()
    assert "[openapi.yaml](openapi.yaml)" in index and "Layered trace" in index
    pages = (out / "UI_PAGES.md").read_text()
    assert "[UI_PAGES.md](UI_PAGES.md)" in index
    assert pages.index("### PG-01") < pages.index("### PG-02") and "#### HTML elements" in pages
    assert "Ajax — jQuery `$.post`" in pages and "`POST /api/orders/{}/cancel`" in pages
    assert "#### Interactive components and what each action does" in pages
    pipeline.confirm(run, "documents")
    assert _next(repo)["kind"] == "done"


def test_command_line_entry_point(tmp_path):
    repo = _solr_repo(tmp_path)
    env = {"MODERNIZER_HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin"}
    start = subprocess.run([sys.executable, "-m", "cli", "-w", str(repo), "start", "solr-4-to-9"], cwd=BACKEND,
                           capture_output=True, text=True, env=env)
    assert start.returncode == 0, start.stderr
    nxt = subprocess.run([sys.executable, "-m", "cli", "-w", str(repo), "next"], cwd=BACKEND,
                         capture_output=True, text=True, env=env)
    assert "plan-solr-4-to-9" in nxt.stdout
    status = json.loads((repo / ".modernizer/run.json").read_text())
    assert status["pattern"] == "solr-4-to-9"


def test_cli_path_never_imports_adk_or_the_web_server():
    """The Gemini CLI install has no google-adk / google-genai / FastAPI (requirements-cli.txt):
    the MCP server and every tool module it reaches must import without them."""
    code = ("import sys, importlib.abc\n"
            "class Block(importlib.abc.MetaPathFinder):\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.split('.')[0] == 'fastapi' or name.startswith(('google.adk', 'google.genai')):\n"
            "            raise ImportError(f'blocked: {name}')\n"
            "sys.meta_path.insert(0, Block())\n"
            "import cli.mcp_server, cli.discovery, cli.docs\n"
            "import agents.java_8_to_11.tools, agents.java_8_to_25.tools, agents.jsp_to_react_bff.tools\n"
            "import agents.solr_4_to_9.tools, agents.oracle_19c_to_23ai.tools, agents.tibco_ems_to_pubsub.tools\n"
            "import agents.shared.change_audit, agents.shared.plan_coverage\n")
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_backend_only_soap_and_oracle_repository(tmp_path):
    """5 REST endpoints, 3 SOAP operations (Spring-WS and JAX-WS), Oracle with a PL/SQL
    package and a trigger, no UI: API-first, no UI documents, SOAP documented everywhere."""
    import json as _json
    import shutil
    repo = tmp_path / "bank"
    shutil.copytree(FIXTURES / "banking-soap-oracle", repo)
    pipeline.start(repo, "stack-discovery")
    assert _next(repo)["id"] == "mapper"
    _save(repo, "mapper", "Nothing to add.\n\n```json\n{\"stacks\": [], \"rejected\": []}\n```")
    pipeline.complete_step(Run.load(repo), "mapper")
    gate = _next(repo)
    assert "ui_pages" in gate["text"]
    run = Run.load(repo)
    assert {s["pattern"] for s in run.state["recommendations"]} == {"java", "oracle"}
    assert run.state.get("screens_offer") is None                         # no UI: no screenshots offered
    pipeline.confirm(run, "stacks", ["java", "oracle"], None)
    assert _next(repo)["id"] == "select-strategy"
    run = Run.load(repo)
    offered = {o["id"]: o for o in run.state["strategy_options"]}
    assert offered["api-first"]["recommended"] and offered["api-first"]["passes"] == ["api", "db"]
    assert not offered["layered-trace"]["available"]
    assert run.state["strategy_signals"]["soap"] == 3 and run.state["strategy_signals"]["endpoints"] == 5
    pipeline.confirm(run, "strategy", ["api-first"])

    api_step = _next(repo)
    assert api_step["id"] == "layer-api-1"
    api_request = (repo / ".modernizer/discovery/layers/api/request-0001.md").read_text()
    for op in ("`GetAccount`", "`TransferFunds`", "`getStatement`"):
        assert op in api_request
    assert "no UI control" not in api_request                            # there is no UI to be called from
    pack = ("### Flow Traces\n- SOAP TransferFunds → AccountEndpoint.transferFunds → AccountService.transfer → "
            "PKG_TRANSFER.TRANSFER_FUNDS updates ACCOUNTS, inserts TRANSACTIONS "
            "(src/main/java/com/acme/bank/service/AccountService.java:29)\n\n"
            "### Tech Debt & Dead Code\n- A failed transfer is reported as REJECTED with the cause only printed "
            "(src/main/java/com/acme/bank/soap/AccountEndpoint.java:41)\n\n### Limitations\nNone found.\n")
    step = _drive_writers(repo, {"layer-": pack, "po_brd": "## Executive Summary\nCustomers and accounts.\n",
                                 "ea_spec": "## Architecture Overview\nOne Spring Boot service.\n",
                                 "ea_diagrams": '{"diagrams": []}', "setup": "## Prerequisites\nJDK 11 (pom.xml).\n"})
    assert step["id"] == "documents-review"
    out = repo / ".modernizer/deliverables"
    names = {p.name for p in out.iterdir()}
    assert {"SETUP.md", "BRD.md", "TECHNICAL_SPECIFICATION.md", "openapi.yaml", "TECH_DEBT_AND_DEAD_CODE.md"} <= names
    assert not names & {"UI_PAGES.md", "UI_SCREENS.md"}                  # no UI layer
    spec = _json.loads((out / "openapi.json").read_text())
    assert sum(len(v) for v in spec["paths"].values()) == 5
    assert [o["operation"] for o in spec["x-soap-operations"]] == ["GetAccount", "TransferFunds", "getStatement"]
    assert "3 SOAP operation(s)" in spec["info"]["description"] and "/ws/accounts.wsdl" in spec["info"]["description"]
    tech = (out / "TECHNICAL_SPECIFICATION.md").read_text()
    assert "### SOAP operations (3)" in tech and "http://0.0.0.0:8081/soap/statements" in tech
    assert "| request `TransferFundsRequest` | `amount` | decimal | required |" in tech
    assert "`pkg_transfer`" in tech and "`trg_accounts_audit`" in tech
    debt = (out / "TECH_DEBT_AND_DEAD_CODE.md").read_text()
    assert "InterestCalculator" in debt and "findByEmailContaining" in debt
    assert "| Table or view no application code uses | `audit_log`" not in debt     # written by the trigger
    assert "SQL built by string concatenation" in debt and "Welcome1" not in debt
    assert "REST endpoint no UI control calls" not in debt
    setup = (out / "SETUP.md").read_text()
    assert "DB_PASSWORD" in setup and "oracle" in setup and "Welcome1" not in setup


def _discover(repo: Path, strategy: str, pack: str) -> dict:
    """Run stack discovery on `repo` with every default document, the given strategy and one
    answer for every agent; returns the run's state."""
    pipeline.start(repo, "stack-discovery")
    assert _next(repo)["id"] == "mapper"
    _save(repo, "mapper", "Nothing to add.\n\n```json\n{\"stacks\": [], \"rejected\": []}\n```")
    pipeline.complete_step(Run.load(repo), "mapper")
    _next(repo)
    run = Run.load(repo)
    pipeline.confirm(run, "stacks", [s["pattern"] for s in run.state["recommendations"]],
                     list(discovery.DEFAULT_DOCUMENTS) + ["ui_screens"]
                     if (run.state.get("screens_offer") or {}).get("available") else None)
    assert _next(repo)["id"] == "select-strategy"
    pipeline.confirm(Run.load(repo), "strategy", [strategy])
    step = _drive_writers(repo, {"layer-": pack, "evidence-": pack, "po_brd": "## Executive Summary\nAs observed.\n",
                                 "ea_spec": "## Architecture Overview\nAs observed.\n",
                                 "ea_diagrams": '{"diagrams": []}', "setup": "## Prerequisites\nA JDK (pom.xml).\n",
                                 "ea_ui": "None found."})
    if step["id"] == "ui-screens":                 # rendered beside the documents, no agent
        step = _drive_writers(repo, {})
    assert step["id"] == "documents-review", step
    return Run.load(repo).state


def test_jsp_multi_module_monorepo_with_ajax_and_oracle(tmp_path):
    """Parent POM + claims-web (JSP, jQuery $.ajax/$.get/$.getJSON, fetch, forms) + claims-services
    (REST under context path /claims-api, Oracle via Liquibase)."""
    import json as _json
    import shutil
    repo = tmp_path / "claims"
    shutil.copytree(FIXTURES / "claims-jsp-monorepo", repo)
    _discover(repo, "layered-trace", "### Limitations\nNone found.\n")
    run = Run.load(repo)
    assert {s["pattern"] for s in run.state["recommendations"]} >= {"jsp", "java", "oracle"}
    assert run.state["strategy_options"][0]["id"] == "layered-trace"
    ui_request = (repo / ".modernizer/discovery/layers/ui/request-0001.md").read_text()
    assert "claims/detail.jsp" in ui_request and "ClaimApiController.decide" in ui_request
    out = repo / ".modernizer/deliverables"
    pages = (out / "UI_PAGES.md").read_text()
    # Page by page, in route order; the shared header listed once and named on every page.
    assert pages.index("PG-01 Claims") < pages.index("PG-02 File a claim") < pages.index("PG-03 Claim detail")
    assert pages.count("**Includes:** FR-01") == 3
    detail = pages.split("### PG-03")[1].split("### FR-01")[0]
    assert "Ajax — jQuery `$.ajax`" in detail and "`PUT /claims-api/api/claims/${claimId}/decision`" in detail
    assert "`ClaimApiController.decide` serving `PUT /api/claims/{id}/decision`" in detail
    assert "Ajax — `fetch`" in detail and "ClaimDecisionException" in detail
    listing = pages.split("### PG-01")[1].split("### PG-02")[0]
    assert "claims-list.js" in listing and "Ajax — jQuery `$.get`" in listing
    assert "HTML form submission (full page request)" in pages.split("### PG-02")[1].split("### PG-03")[0]
    assert "`DELETE /api/claims/{id} (ClaimApiController.purge)`" in pages      # no UI calls it
    debt = (out / "TECH_DEBT_AND_DEAD_CODE.md").read_text()
    assert "Page template nothing renders" not in debt
    assert "REST endpoint no UI control calls" in debt and "FIXME" in debt
    setup = (out / "SETUP.md").read_text()
    assert "claims-services" in setup and "claims-web" in setup and "CLAIMS_DB_PASSWORD" in setup
    spec = _json.loads((out / "openapi.json").read_text())
    assert "/api/claims/{id}/decision" in spec["paths"] and "/claims" in spec["paths"]
    tech = (out / "TECHNICAL_SPECIFICATION.md").read_text()
    assert "`v_open_claims`" in tech and "Liquibase" in tech


def test_thymeleaf_spring_boot_oracle_and_solr4_search(tmp_path):
    """Thymeleaf templates with a layout and a fragment, Spring Boot, Oracle, and search APIs on Solr 4."""
    import json as _json
    import shutil
    repo = tmp_path / "catalog"
    shutil.copytree(FIXTURES / "catalog-thymeleaf-solr", repo)
    _discover(repo, "layered-trace", "### Limitations\nNone found.\n")
    run = Run.load(repo)
    assert {s["pattern"] for s in run.state["recommendations"]} >= {"thymeleaf", "solr", "oracle", "java"}
    db_request = (repo / ".modernizer/discovery/layers/db/request-0001.md").read_text()
    assert "SOLR CORE `products`" in db_request and "name_suggest (text_suggest)" in db_request
    out = repo / ".modernizer/deliverables"
    tech = (out / "TECHNICAL_SPECIFICATION.md").read_text()
    assert "### Search Engine — Apache Solr (computed)" in tech
    assert "| `solr-solrj` | 4.10.4 |" in tech and "`luceneMatchVersion`: 4.10.4" in tech
    assert "| `/suggest` | `SearchHandler` |" in tech and "Copy fields: `name` → `name_suggest`" in tech
    backed = tech.split("#### HTTP endpoints backed by Solr")[1].split("###")[0]
    assert "`GET /api/search/products`" in backed and "`POST /admin/reindex`" in backed
    assert "ReindexJob → ProductSearchService" in backed and "`GET /products/{sku}`" not in backed
    pages = (out / "UI_PAGES.md").read_text()
    order = [l.split(" ", 2)[1] for l in pages.splitlines() if l.startswith("### PG-")]
    assert len(order) == 4                                                     # home, admin, product, search
    assert "| FR-01 |" in pages and "| FR-02 |" in pages                      # nav fragment and layout
    assert "Ajax — `fetch`" in pages and "`GET /api/search/products?q={}&page={}&inStock={}`" in pages
    assert "Ajax — jQuery `$.getJSON`" in pages and "`SearchApiController.suggest`" in pages
    assert "Calls No Handler Serves" not in pages                              # @{/} resolves to home
    debt = (out / "TECH_DEBT_AND_DEAD_CODE.md").read_text()
    assert "Search query built by string concatenation" in debt and 'addFilterQuery("category:" + category)' in debt
    spec = _json.loads((out / "openapi.json").read_text())
    assert spec["paths"]["/api/search/suggest"]["get"]["parameters"][0]["schema"].get("minLength") == 2
    if "UI_SCREENS.md" in {p.name for p in out.iterdir()}:
        screens = (out / "UI_SCREENS.md").read_text()
        assert screens.index("PG-01") < screens.index("PG-02")


def test_no_curator_tool_is_registered_on_the_mcp_server():
    names = {t.name for t in anyio.run(mcp_server.server.list_tools)}
    assert "next_step" in names and "ws_write_file" in names
    assert not [n for n in names if "curator" in n or n.endswith("_skill_file")]


FAILED_BUILD = json.dumps({"passed": False, "errors": ["COMPILE: Svc.java:3 cannot find symbol"], "summary": "1 error"})
STAGED_PLAN = ("## Stage 1: Modernize Build Systems (Maven/Gradle)\n\n### Task 1.1: Wrapper\n- Files: `pom.xml`\n\n"
               "## Stage 3: Java 8 → Java 17 LTS\n\n### Task 3.1: Release\n- Files: `pom.xml`\n")


def _stage1_out_of_iterations(tmp_path, monkeypatch):
    from agents import config
    monkeypatch.setattr(config, "BUILD_LOOP_MAX_ITERATIONS", 2)
    repo = tmp_path / "j"
    (repo / "src").mkdir(parents=True)
    (repo / "pom.xml").write_text("<project/>")
    run = pipeline.start(repo, "java-8-to-25", migration_strategy="incremental")
    run.write_doc("plan", STAGED_PLAN)
    run.state.update({"phase": "code", "plan_approved": True, "pi": 0, "code": None})
    run.save()

    def answer(text):
        step = _next(repo)
        _save(repo, step["id"], text)
        pipeline.complete_step(Run.load(repo), step["id"])
        return step["id"]
    assert answer("done") == "modify-java-8-to-25-stage1-1.1"
    assert answer(FAILED_BUILD) == "validate-java-8-to-25-stage1-1"
    assert answer("fixed") == "fix-java-8-to-25-stage1-1"
    assert answer(FAILED_BUILD) == "validate-java-8-to-25-stage1-2"
    return repo, answer


def _passes(repo: Path) -> str:
    """Complete the validation the way a passing validator does: its JSON, and the build-success signal."""
    step = _next(repo)
    assert step["id"].startswith("validate-")
    _save(repo, step["id"], json.dumps({"passed": True, "errors": [], "summary": "ok"}))
    run = Run.load(repo)
    run.state["build_signalled"] = True
    run.save()
    pipeline.complete_step(Run.load(repo), step["id"])
    return step["id"]


def test_an_incremental_stage_whose_build_loop_runs_out_pauses_the_run_for_the_user(tmp_path, monkeypatch):
    repo, answer = _stage1_out_of_iterations(tmp_path, monkeypatch)
    held = _next(repo)
    assert held["id"] == "stage-build-failed" and held["kind"] == "ask_user"
    assert "Modernize Build Systems" in held["title"] and "cannot find symbol" in held["text"]
    assert "gate=`stage`" in held["text"] and str(repo) in held["text"]
    assert _next(repo)["id"] == "stage-build-failed"                      # asked again; the next stage never starts
    with pytest.raises(RunError):
        pipeline.confirm(Run.load(repo), "stage", ["whatever"])
    # the user fixed it by hand: validate again, with a fresh budget — and then the next stage follows
    assert "validating again" in pipeline.confirm(Run.load(repo), "stage", ["retry"])
    assert _passes(repo) == "validate-java-8-to-25-stage1-3"
    assert _next(repo)["id"] == "modify-java-8-to-25-stage3-3.1"           # only now does the next stage start


def test_retry_gets_a_fresh_budget_and_the_fixer_choice_runs_the_fixer(tmp_path, monkeypatch):
    repo, answer = _stage1_out_of_iterations(tmp_path, monkeypatch)
    assert _next(repo)["id"] == "stage-build-failed"
    pipeline.confirm(Run.load(repo), "stage", ["fix"])
    assert answer("fixed again") == "fix-java-8-to-25-stage1-2"
    assert answer(FAILED_BUILD) == "validate-java-8-to-25-stage1-3"
    assert _next(repo)["id"] == "fix-java-8-to-25-stage1-3"               # one validation of the new budget is not yet spent
    assert answer("fixed") == "fix-java-8-to-25-stage1-3"
    assert answer(FAILED_BUILD) == "validate-java-8-to-25-stage1-4"
    assert _next(repo)["id"] == "stage-build-failed"                      # the new budget (2) ran out: asks again


def test_skipping_continues_with_the_next_stage_and_the_report_says_so(tmp_path, monkeypatch):
    repo, answer = _stage1_out_of_iterations(tmp_path, monkeypatch)
    assert _next(repo)["id"] == "stage-build-failed"
    assert "report will say so" in pipeline.confirm(Run.load(repo), "stage", ["skip"])
    assert _next(repo)["id"] == "modify-java-8-to-25-stage3-3.1"
    assert "Modernize Build Systems" in Run.load(repo).state["unresolved_stages"][0]
    assert answer("done") == "modify-java-8-to-25-stage3-3.1"
    assert _passes(repo) == "validate-java-8-to-25-stage3-1"
    assert answer("fine") == "review-java-8-to-25"
    report = _next(repo)
    assert report["id"] == "report-java-8-to-25" and "Stages that did not build" in report["query"]


def test_a_big_bang_run_still_moves_on_when_its_build_loop_runs_out(tmp_path, monkeypatch):
    from agents import config
    monkeypatch.setattr(config, "BUILD_LOOP_MAX_ITERATIONS", 1)
    repo = tmp_path / "j"
    (repo / "src").mkdir(parents=True)
    (repo / "pom.xml").write_text("<project/>")
    run = pipeline.start(repo, "java-8-to-25")
    run.write_doc("plan", "## 1. What Changes\n\n### Task 1.1: Release\n- Files: `pom.xml`\n")
    run.state.update({"phase": "code", "plan_approved": True, "pi": 0, "code": None})
    run.save()
    for prefix in ("modify-", "validate-"):
        step = _next(repo)
        assert step["id"].startswith(prefix)
        _save(repo, step["id"], "done" if prefix == "modify-" else FAILED_BUILD)
        pipeline.complete_step(Run.load(repo), step["id"])
    assert _next(repo)["id"] != "stage-build-failed"
