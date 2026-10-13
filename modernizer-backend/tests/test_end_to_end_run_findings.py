"""Regressions for what driving the Gemini CLI pipeline end to end on two applications found
(tests/fixtures/orders-jsp-oracle-monorepo: Java 8 -> 25 incremental + Oracle; tests/fixtures/
storefront-thymeleaf-solr4-oracle: big bang + Spring Boot + Oracle + Solr)."""
import json
import re
import shutil
from pathlib import Path

from agents import config
from agents.oracle_19c_to_23ai import tools as oracle_tools
from agents.shared import callbacks, change_audit, migration_inventory, plan_coverage, workspace_tools
from agents.shared.dependency_graph import EXCLUDED_DIRS
from agents.solr_4_to_9 import tools as solr_tools
from cli import pipeline
from cli.runstate import Run

FIXTURES = Path(__file__).parent / "fixtures"
ORDERS = FIXTURES / "orders-jsp-oracle-monorepo"
STORE = FIXTURES / "storefront-thymeleaf-solr4-oracle"
SKILLS = Path(__file__).resolve().parent.parent / "agents" / "skills"


class _Ctx:
    def __init__(self, ws):
        self.state = {"workspace_dir": str(ws)}


def test_jdbc_connections_never_carry_the_next_lines_credentials():
    tech = migration_inventory.to_document("oracle-19c-to-23ai", str(ORDERS), 400)
    assert "ORDERS_APP" not in tech and "ChangeMe" not in tech
    assert "| `order-services/src/main/resources/orders.properties` | " \
           "`jdbc:oracle:thin:@//orders-db.acme.internal:1521/ORDERSPDB` |" in tech
    from agents.shared.evidence import redact
    assert redact("spring.datasource.password=St0re!Prod") == "spring.datasource.password=<redacted>"


def test_jdbc_placeholders_are_not_hql_but_hibernate_queries_still_are():
    java = migration_inventory.to_document("java-8-to-25", str(ORDERS), 400)
    assert "HQL positional parameter" not in java                    # JdbcTemplate SQL in OrderDao
    hql = next(m for m in change_audit.LEGACY_MARKERS["java-8-to-25"] if m.name == "HQL positional parameter")
    line = 'return session.createQuery("from Policy where id = ?").list();'
    assert change_audit._scan([line], [hql], context="import org.hibernate.Session;\n" + line)
    assert not change_audit._scan(['jdbc.query("SELECT * FROM T WHERE ID = ?", m, id);'], [hql],
                                  context="JdbcTemplate jdbc;")


def test_spring6_and_jakarta_web_work_is_in_the_inventory():
    java = migration_inventory.to_document("java-8-to-25", str(ORDERS), 400)
    for token in ("Spring MVC adapter class", "order-web/src/main/java/com/acme/orders/web/WebConfig.java",
                  "Java EE descriptor namespace", "order-web/src/main/webapp/WEB-INF/web.xml", "JSTL 1.2 (javax)"):
        assert token in java, token


def test_sql_comments_are_not_code_but_strings_are():
    sql = ("-- NOTES LONG -> CLOB\n/* old type: LONG\n RAW */\nALTER TABLE ORDERS MODIFY (NOTES CLOB);\n"
           "EXECUTE IMMEDIATE 'ALTER SESSION SET optimizer_features_enable = ''11.2''';\n")
    code = change_audit.sql_code(sql)
    assert len(code) == len(sql) and code.count("\n") == sql.count("\n")
    assert "LONG" not in code and "optimizer_features_enable" in code


def test_the_oracle_validator_and_the_audit_agree_on_a_conversion_script(tmp_path):
    base, ws = tmp_path / "base", tmp_path / "ws"
    for d in (base, ws):
        (d / "db").mkdir(parents=True)
        (d / "db/V1.sql").write_text("CREATE TABLE ORDERS (ID NUMBER, NOTES LONG);\n")
    (ws / "db/V1.sql").write_text("CREATE TABLE ORDERS (ID NUMBER, NOTES CLOB);\n")
    (ws / "db/V3.sql").write_text("-- converts NOTES LONG to CLOB, as long as it is still LONG\n"
                                  "ALTER TABLE ORDERS MODIFY (NOTES CLOB);\n")
    report = oracle_tools.validate_sql_syntax(_Ctx(ws))
    assert "OVERALL: no issues found." in report, report
    assert "NOTES LONG," not in report
    audit = change_audit.audit_changes(str(base), str(ws), "oracle-19c-to-23ai")
    assert not audit.regressions, audit.regressions          # the comment in V3 is not a re-added LONG column
    (ws / "db/V1.sql").write_text("CREATE TABLE ORDERS (ID NUMBER, NOTES LONG, X NUMBER);\n")
    assert "LONG/LONG RAW" in oracle_tools.validate_sql_syntax(_Ctx(ws))   # a real LONG column still fails


def test_a_companion_builds_with_the_java_build_on_the_stage_jdk(tmp_path, monkeypatch):
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    repo = tmp_path / "orders"
    shutil.copytree(ORDERS, repo)
    pipeline.start(repo, "java-8-to-25", migration_strategy="incremental")
    run = Run.load(repo)
    run.state["bundle"] = ["oracle-19c-to-23ai", "java-8-to-25"]
    assert pipeline.build_pattern(run, "oracle-19c-to-23ai") == "java-8-to-25"
    assert pipeline.build_pattern(run, "java-8-to-25") is None
    run.state["bundle"] = ["oracle-19c-to-23ai"]
    assert pipeline.build_pattern(run, "oracle-19c-to-23ai") is None   # no Java build in the run: static only


def test_validation_compiles_the_tests_from_a_clean_tree():
    validate = (SKILLS / "java-8-to-25/references/steps/validate.md").read_text()
    assert "`mvn -q -DskipTests clean test-compile`" in validate and "DskipTests compile`" not in validate
    from cli import patterns
    assert "clean test-compile" in patterns.PATTERNS["java-8-to-25"].validator_note


def test_learning_keeps_paths_and_lock_files_out_of_the_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(callbacks, "_LEARNING_ENABLED", True)
    skill = tmp_path / "validate.md"
    skill.write_text("# validate\n")
    ctx = type("C", (), {"state": {"build_result": json.dumps({
        "passed": False, "summary": "order-services/src/main/resources/db/oracle/V3__x.sql failed",
        "errors": ["order-services/src/main/resources/db/oracle/V3__x.sql: possible unbalanced block"]})}})()
    callbacks.make_skill_update_callback("build_result", skill, "Validation Pass")(ctx)
    text = skill.read_text()
    assert "possible unbalanced block" in text and "order-services/" not in text and "V3__x.sql" not in text
    assert sorted(p.name for p in tmp_path.iterdir()) == ["validate.md"]          # no .lock beside it


def test_left_alone_lists_and_passing_mentions_are_not_misread():
    plan = ("## File Change Manifest\n| File | Change | What changes |\n|---|---|---|\n"
            "| `a/WebConfig.java` | Modify | implement WebMvcConfigurer; URL mappings unchanged |\n\n"
            "**Seen and deliberately left alone:**\n- `a/orders.properties` — password in clear text; raised separately\n")
    planned = {e.path: e for e in plan_coverage.parse_plan_manifest(plan)}
    assert not planned["a/WebConfig.java"].no_change_expected
    assert planned["a/orders.properties"].no_change_expected


def test_thymeleaf_2_templates_are_inventoried():
    java = migration_inventory.to_document("java-8-to-25", str(STORE), 400)
    for token in ("Thymeleaf template(s)", "Thymeleaf 2 template mode", "layout dialect decorator",
                  "Thymeleaf th:include", "src/main/resources/templates/home.html"):
        assert token in java, token
    assert (SKILLS / "java-8-to-25/references/thymeleaf-2-to-3.md").is_file()


def test_the_solr_validator_knows_what_solr_9_removed():
    report = solr_tools.validate_solr_config(_Ctx(STORE))
    for token in ("<defaultSearchField>", "<solrQueryParser", "enablePositionIncrements", "CaffeineCache",
                  "AdminHandlers", "luceneMatchVersion is older", "modules/"):
        assert token in report, token
    solr = migration_inventory.to_document("solr-4-to-9", str(STORE), 400)
    assert "SolrJ 4 server classes" in solr and "removed Solr cache / handler class" in solr


def test_the_test_summary_survives_output_clipping(monkeypatch):
    monkeypatch.setattr(config, "COMMAND_OUTPUT_MAX_CHARS", 2000)
    out = "\n".join(["[INFO] start"] * 50 + ["[INFO] Tests run: 20, Failures: 0, Errors: 0, Skipped: 0"]
                    + ["CONDITIONS EVALUATION REPORT line"] * 400)
    clipped = workspace_tools._clip_command_output(out)
    assert len(clipped) < len(out) and "Tests run: 20, Failures: 0" in clipped


def test_a_big_bang_boot_run_validates_the_packaged_jar(tmp_path, monkeypatch):
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    repo = tmp_path / "store"
    shutil.copytree(STORE, repo)
    pipeline.start(repo, "java-8-to-25", springboot_upgrade=True)
    run = Run.load(repo)
    code = {"pattern": "java-8-to-25", "iter": 0, "stages": [{"title": "", "idx": 0}], "si": 0}
    step = pipeline._validate_step(run, code, code["stages"][0], pipeline.P.get("java-8-to-25"))
    assert "`mvn -B clean package`" in step["query"]                  # the packaged JAR, tests included


def test_macos_archive_metadata_is_never_scanned():
    assert "__MACOSX" in EXCLUDED_DIRS


def test_run_command_gives_the_tool_context_only_to_a_factory_that_names_it(tmp_path, monkeypatch):
    """java_env.build_env(java_home=None) has a parameter too: the tool context must never become JAVA_HOME
    (it crashed every Java 8 -> 11 ws_run_command call), while stage_env(tool_context) still gets it."""
    import sys
    from agents.shared import java_env
    from agents.java_8_to_11 import tools as j11
    from agents.java_8_to_25 import tools as j25
    (tmp_path / "pom.xml").write_text("<project/>")
    seen = {}

    def spy(*args, **kwargs):
        seen["env"] = kwargs.get("env")
        return type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr(workspace_tools.subprocess, "run", spy)
    monkeypatch.setattr(java_env.config, "MIGRATION_JAVA_HOME", "/opt/jdk-11")
    monkeypatch.setattr(workspace_tools, "_resolve_executable", lambda exe, cwd: exe)
    ctx = _Ctx(tmp_path)
    for tools in (j11, j25):
        seen.clear()
        out = tools.run_command(ctx, "mvn -v")
        assert out.startswith("exit_code=0"), (tools.__name__, out)
    seen.clear()
    assert j11.run_command(ctx, "mvn -v").startswith("exit_code=0")
    assert seen["env"]["JAVA_HOME"] == "/opt/jdk-11"          # the configured JDK, not a repr of the context


# ── the person's requirements reach the planner, the reviewer and the reporter ───────────────────────────

def _started(tmp_path, monkeypatch, pattern, **kw):
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "orders-jsp-hibernate-monorepo", repo)
    return repo, pipeline.start(repo, pattern, **kw)


REQUEST = "Migrate the backend services to Java 11, keep the JSP WAR deployments, Spring and Hibernate to compatible versions."


def test_requirements_are_stored_shown_and_sent_to_the_planner(tmp_path, monkeypatch):
    repo, run = _started(tmp_path, monkeypatch, "java-8-to-11", requirements=REQUEST)
    assert run.state["requirements"] == REQUEST and REQUEST[:40] in pipeline.summary(run)
    pipeline.confirm(Run.load(repo), "analysis") if Run.load(repo).state.get("phase") == "analysis_review" else None
    run = Run.load(repo)
    for _ in range(20):
        step, _log = pipeline.next_step(run)
        if step["kind"] == "subagent":
            break
        run = Run.load(repo)
    assert step["id"] == "plan-java-8-to-11"
    q = step["query"]
    assert "## Requirements from the person who asked for this migration" in q and REQUEST in q
    assert "These are binding" in q and "Open Questions" in q
    assert q.index("## Requirements") < q.index("## Scope Fence")      # before the rules it may collide with


def test_without_requirements_the_query_is_unchanged(tmp_path, monkeypatch):
    repo, run = _started(tmp_path, monkeypatch, "java-8-to-11")
    assert pipeline.requirements_block(run, "plan") == ""


def test_review_and_report_check_each_requirement(tmp_path, monkeypatch):
    _repo, run = _started(tmp_path, monkeypatch, "java-8-to-11", requirements=REQUEST)
    assert "a requirement the migrated code does not meet is a finding" in pipeline.requirements_block(run, "review")
    assert 'section "Requirements"' in pipeline.requirements_block(run, "report")


def test_requirements_are_rejected_where_they_cannot_apply_or_are_too_long(tmp_path, monkeypatch):
    import pytest
    from cli.runstate import RunError
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "orders-jsp-hibernate-monorepo", repo)
    with pytest.raises(RunError, match="do not apply"):
        pipeline.start(repo, "stack-discovery", requirements="x")
    with pytest.raises(RunError, match="keep them under"):
        pipeline.start(repo, "java-8-to-11", requirements="x" * (pipeline.MAX_REQUIREMENTS_CHARS + 1))


def test_the_mcp_start_run_takes_requirements(tmp_path, monkeypatch):
    import anyio
    from cli import mcp_server
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "orders-jsp-hibernate-monorepo", repo)
    out = anyio.run(lambda: mcp_server.start_run(pattern="java-8-to-11", workspace=str(repo), requirements=REQUEST))
    assert "**Requirements:** Migrate the backend services to Java 11" in out


def test_the_java11_inventory_lists_the_files_a_spring_hibernate_move_touches():
    from agents.java_8_to_11 import inventory
    doc = inventory.to_document(inventory.build(str(FIXTURES / "orders-jsp-hibernate-monorepo")))
    part = doc[doc.index("## Spring / Hibernate API Usage"):doc.index("## Java 11 Blockers")]
    for token in ("Spring orm.hibernate3/4", "HQL with JDBC-style `?`", "Hibernate typed setters",
                  "order-services/src/main/java/com/acme/orders/dao/CustomerDao.java",
                  "order-services/src/test/java/com/acme/orders/dao/CustomerDaoTest.java"):
        assert token in part, token
    assert "WebMvcConfigurerAdapter" not in part                       # deprecated in 5.3, removed only in 6
    # the Java 11 plan's File Change Manifest is not built from this table unless the requirements ask
    assert "not work items" in part and "ONLY when the Requirements" in part


def test_the_java11_audit_knows_the_hibernate_5_changes():
    java11 = change_audit.LEGACY_MARKERS["java-8-to-11"]
    names = {m.name for m in java11}
    assert {"Spring ORM hibernate3/4 support", "HQL positional parameter"} <= names
    hql = next(m for m in java11 if m.name == "HQL positional parameter")
    line = 'session.createQuery("from C c where c.a = ?")'
    assert change_audit._scan([line], [hql], context=line)
    assert not change_audit._scan(['jdbc.query("select * from t where a = ?")'], [hql], context="JdbcTemplate")


def _validate_query(tmp_path, monkeypatch, preflight: dict | None = None, **opts) -> str:
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "orders-jsp-oracle-monorepo", repo)
    pipeline.start(repo, "java-8-to-25", **opts)
    run = Run.load(repo)
    if preflight is not None:
        run.state["preflight_json"] = json.dumps(preflight)
    code = {"pattern": "java-8-to-25", "iter": 0, "stages": [{"title": "Java 8 → Java 17 LTS", "idx": 3}], "si": 0}
    return pipeline._validate_step(run, code, code["stages"][0], pipeline.P.get("java-8-to-25"))["query"]


def test_validation_runs_the_tests_and_tolerates_only_the_baseline_failures(tmp_path, monkeypatch):
    q = _validate_query(tmp_path, monkeypatch, {"baseline_failing_tests": ["com.acme.A#old", "com.acme.B#flaky"]})
    assert "`mvn -B clean test`" in q and "RUNS THE TESTS" in q and "## Tests" in q
    assert "`com.acme.A#old`" in q and "`com.acme.B#flaky`" in q and "never fail the validation for them" in q
    assert "TEST: Class#method" in q and "Zero tests run" in q
    clean = _validate_query(tmp_path / "b", monkeypatch, {"baseline_failing_tests": []})
    assert "No test failed on the code as uploaded: every failure is the migration's." in clean


def test_with_test_running_off_validation_only_compiles_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VALIDATE_RUN_TESTS", False)
    q = _validate_query(tmp_path, monkeypatch)
    assert "mvn -q -DskipTests clean test-compile" not in q or "## Tests" not in q
    assert "## Tests" not in q and "RUNS THE TESTS" not in q


def test_the_preflight_report_names_the_tests_already_failing(monkeypatch):
    from agents.java_8_to_25 import preflight as pf25
    pf = pf25.Preflight(baseline_build_ok=True, baseline_jdk=8, baseline_tests_run=True,
                        baseline_failing_tests=["com.acme.A#old"], assignment={"8": {"major": 8, "source": "x", "exact": True}})
    md, summary = pf25.to_markdown(pf), pf25.summary(pf)
    assert "Baseline tests on JDK 8: 1 failing before any change" in md and "`com.acme.A#old`" in md
    assert "1 test(s) already failing on JDK 8" in summary
    assert json.loads(pf.to_json())["baseline_failing_tests"] == ["com.acme.A#old"]


def test_the_stale_learned_patterns_of_an_unrelated_project_are_gone_from_the_skills():
    junk = re.compile(r"Java 8_Spring|__MACOSX|6\.1\.8\.RELEASE")
    for path in SKILLS.rglob("references/steps/*.md"):
        assert not junk.search(path.read_text(encoding="utf-8")), path


def test_the_jdk_25_mockito_requirement_is_stated_where_the_planner_and_modifier_read_it():
    lib = (SKILLS / "java-8-to-25/references/legacy-library-modernization.md").read_text()
    plan = (SKILLS / "java-8-to-25/references/steps/plan.md").read_text()
    assert "5.17.0 fails, 5.23.0 passes on JDK 25" in lib and "ByteBuddy 1.17.7+" in lib
    assert "an older 5.x cannot mock on JDK 25" in plan
