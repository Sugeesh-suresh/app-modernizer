"""Regressions for what driving the Gemini CLI pipeline end to end on two applications found
(tests/fixtures/orders-jsp-oracle-monorepo: Java 8 -> 25 incremental + Oracle; tests/fixtures/
storefront-thymeleaf-solr4-oracle: big bang + Spring Boot + Oracle + Solr)."""
import json
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
    assert "`mvn -q -DskipTests clean package`" in step["query"]


def test_macos_archive_metadata_is_never_scanned():
    assert "__MACOSX" in EXCLUDED_DIRS
