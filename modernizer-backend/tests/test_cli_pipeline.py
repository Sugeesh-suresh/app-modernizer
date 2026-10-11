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
    (repo / "conf" / "solrconfig.xml").write_text("<config><luceneMatchVersion>4.10.4</luceneMatchVersion></config>")
    return repo


def _save(repo: Path, step_id: str, text: str) -> None:
    assert _tool(mcp_server.save_output, step_id=step_id, content=text, workspace=str(repo)).startswith("Saved")


def _tool(fn, **kwargs) -> str:
    return anyio.run(lambda: fn(**kwargs))


def _next(repo: Path) -> dict:
    step, _ = pipeline.next_step(Run.load(repo))
    return step


def test_solr_run_end_to_end(tmp_path):
    repo = _solr_repo(tmp_path)
    run = pipeline.start(repo, "solr-4-to-9")
    assert Path(run.state["baseline_dir"], "conf", "schema.xml").is_file()

    # The inventory runs without a model; the planner is the first agent.
    step = _next(repo)
    assert step["id"] == "plan-solr-4-to-9" and step["subagent"] == "modernizer-planner"
    assert "`solr-4-to-9-plan`" in step["query"] and ".modernizer/docs/solr-4-to-9/technical_spec.md" in step["query"]
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
    assert modify["subagent"] == "modernizer-coder" and "`solr-4-to-9-modify`" in modify["query"]
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
    assert report_step["subagent"] == "modernizer-writer" and "solr-4-to-9-report" in report_step["query"]
    _save(repo, report_step["id"], "# Report")
    pipeline.complete_step(Run.load(repo), report_step["id"])

    done = _next(repo)                       # skill learning is off in tests: no curator step
    assert done["kind"] == "done"
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
    assert fix["id"].startswith("fix-") and "solr-4-to-9-fix" in fix["query"]
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
    assert "Guardrail for this stage" in first["query"] and "java-migration-readiness" in first["query"]
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
    while step["kind"] == "subagent" and step["id"].startswith("ea-ui"):
        _save(repo, step["id"], "No controls.")
        pipeline.complete_step(Run.load(repo), step["id"])
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


def _drive_writers(repo: Path, outputs: dict[str, str]) -> dict:
    """Answer every subagent step until a non-subagent step, with `outputs` by step-id prefix."""
    step = _next(repo)
    while step["kind"] == "subagent":
        text = next((v for k, v in outputs.items() if step["id"].startswith(k)), "None found.")
        _save(repo, step["id"], text)
        pipeline.complete_step(Run.load(repo), step["id"])
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
    assert offered["layered-trace"]["recommended"] and offered["layered-trace"]["passes"] == ["ui", "db", "api"]
    assert "Reverse-Engineering Strategy Options" in (repo / ".modernizer/discovery/strategy.md").read_text()
    pipeline.confirm(Run.load(repo), "strategy", ["layered-trace"])

    ui_step = _next(repo)
    assert ui_step["id"] == "layer-ui-1" and "`layer-ui-trace`" in ui_step["query"]
    ui_request = (repo / ".modernizer/discovery/layers/ui/request-0001.md").read_text()
    assert "UI-001" in ui_request
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
            "import agents.shared.change_audit, agents.shared.plan_coverage, agents.shared.skill_curator_tools\n")
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
