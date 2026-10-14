"""The `java-8-to-25-boot` pipeline: the Java 8 -> 25 engine with the Spring Boot 4 end state fixed (executable JAR
on embedded Tomcat, every Spring component converted), checked by a deterministic scan (agents/shared/
boot_conformance.py) that the final validation cannot pass without."""
import json
import shutil
import textwrap
from pathlib import Path

import anyio
import pytest

from agents.shared import boot_conformance as bc
from agents.shared import skill_steps
from cli import mcp_server, pipeline
from cli.runstate import Run, RunError


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MODERNIZER_WORKSPACE", raising=False)


# ── repositories ──────────────────────────────────────────────────────────────────────────────────────────

LEGACY_POM = """<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version>
  <packaging>war</packaging>
  <dependencies>
    <dependency><groupId>org.springframework</groupId><artifactId>spring-webmvc</artifactId><version>4.3.30.RELEASE</version></dependency>
    <dependency><groupId>org.springframework</groupId><artifactId>spring-jdbc</artifactId><version>4.3.30.RELEASE</version></dependency>
    <dependency><groupId>org.springframework.security</groupId><artifactId>spring-security-web</artifactId><version>4.2.0</version></dependency>
    <dependency><groupId>org.hibernate</groupId><artifactId>hibernate-core</artifactId><version>5.2.0</version></dependency>
    <dependency><groupId>javax.servlet</groupId><artifactId>javax.servlet-api</artifactId><version>3.1.0</version><scope>provided</scope></dependency>
    <dependency><groupId>javax.servlet</groupId><artifactId>jstl</artifactId><version>1.2</version></dependency>
    <dependency><groupId>log4j</groupId><artifactId>log4j</artifactId><version>1.2.17</version></dependency>
  </dependencies>
  <build><plugins><plugin><artifactId>maven-war-plugin</artifactId></plugin></plugins></build>
</project>
"""

LEGACY_FILES = {
    "src/main/webapp/WEB-INF/web.xml": "<web-app/>",
    "src/main/webapp/WEB-INF/views/home.jsp": "<%@ page %>",
    "src/main/resources/applicationContext.xml": '<beans xmlns="http://www.springframework.org/schema/beans"></beans>',
    "src/main/resources/log4j.properties": "log4j.rootLogger=INFO",
    "src/main/java/com/acme/Init.java": textwrap.dedent("""
        package com.acme;
        import javax.servlet.ServletContext;
        import javax.persistence.Entity;
        import javax.sql.DataSource;
        import org.springframework.web.WebApplicationInitializer;
        public class Init implements WebApplicationInitializer { }
    """),
    "src/main/java/com/acme/WebConfig.java": textwrap.dedent("""
        package com.acme;
        @EnableWebMvc @Configuration @ImportResource("classpath:applicationContext.xml")
        public class WebConfig extends WebMvcConfigurerAdapter {
            @Bean public InternalResourceViewResolver viewResolver() { return new InternalResourceViewResolver(); }
            @Bean
            public DataSource dataSource() { return null; }
            @Bean public JdbcTemplate jdbc(DataSource ds) { return new JdbcTemplate(ds); }
        }
    """),
    "src/test/java/com/acme/FooTest.java": "@RunWith(SpringJUnit4ClassRunner.class) public class FooTest { }",
}

BOOT_POM = """<project>
  <modelVersion>4.0.0</modelVersion>
  <parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId><version>4.0.0</version></parent>
  <groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-data-jpa</artifactId></dependency>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-thymeleaf</artifactId></dependency>
  </dependencies>
  <build><plugins><plugin><groupId>org.springframework.boot</groupId><artifactId>spring-boot-maven-plugin</artifactId></plugin></plugins></build>
</project>
"""

BOOT_FILES = {
    "pom.xml": BOOT_POM,
    "src/main/resources/application.yml": "server:\n  port: 8080\n",
    "src/main/resources/templates/home.html": "<html/>",
    "src/main/java/com/acme/ShopApplication.java": textwrap.dedent("""
        package com.acme;
        import jakarta.servlet.ServletContext;
        import javax.sql.DataSource;
        import org.springframework.boot.autoconfigure.SpringBootApplication;
        @SpringBootApplication
        public class ShopApplication { public static void main(String[] a) { } }
    """),
}


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def _codes(c: bc.Conformance, level: str | None = None) -> set[str]:
    return {f.code for f in c.findings if level is None or f.level == level}


# ── the scan ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_legacy_spring_war_fails_every_part_of_the_boot_end_state(tmp_path):
    repo = _write(tmp_path / "legacy", {"pom.xml": LEGACY_POM, **LEGACY_FILES})
    scan = bc.scan(repo)
    assert not scan.ok
    assert _codes(scan, "error") >= {"B001", "B002", "B003", "B004", "B005", "B006", "B007", "B008", "B009", "B011"}
    assert _codes(scan, "warn") == {"B012", "B013"}
    text = "\n".join(scan.error_lines())
    assert "spring-webmvc" in text and "spring-boot-starter-web" in text and "spring-security-web" in text
    assert "spring-boot-starter-security" in text and "spring-boot-starter-data-jpa" in text      # hibernate-core, too
    assert "InternalResourceViewResolver" in text and "WebMvcConfigurerAdapter" in text and "@EnableWebMvc" in text
    assert "hand-declared `DataSource` bean" in text and "hand-declared `JdbcTemplate` bean" in text
    assert "web.xml" in text and "applicationContext.xml" in text and "home.jsp" in text
    md = scan.markdown()
    assert md.startswith("Spring Boot conformance: ") and "### B006" in md and "### B009" in md


def test_a_spring_boot_application_on_embedded_tomcat_passes(tmp_path):
    scan = bc.scan(_write(tmp_path / "boot", BOOT_FILES))
    assert scan.ok and not scan.findings, scan.markdown()
    assert scan.markdown().endswith("the repository meets the end state.")


def test_javax_se_packages_are_not_flagged_but_ee_ones_are(tmp_path):
    files = dict(BOOT_FILES)
    files["src/main/java/com/acme/Se.java"] = "package com.acme;\nimport javax.sql.DataSource;\nimport javax.crypto.Cipher;\nimport javax.naming.InitialContext;\nimport javax.net.ssl.SSLContext;\n"
    assert bc.scan(_write(tmp_path / "se", files)).ok
    files["src/main/java/com/acme/Ee.java"] = "package com.acme;\nimport javax.annotation.PostConstruct;\nimport javax.validation.Valid;\nimport javax.annotation.Nullable;\n"
    scan = bc.scan(_write(tmp_path / "ee", files))
    assert [f.code for f in scan.errors] == ["B008"] and "2 javax.* Java EE import(s)" in scan.errors[0].message


def test_another_server_or_a_container_scoped_tomcat_is_not_embedded_tomcat(tmp_path):
    jetty = BOOT_POM.replace("</dependencies>", "<dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-jetty</artifactId></dependency></dependencies>")
    scoped = BOOT_POM.replace("</dependencies>", "<dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-tomcat</artifactId><scope>provided</scope></dependency></dependencies>")
    excluded = BOOT_POM.replace("<artifactId>spring-boot-starter-web</artifactId>", "<artifactId>spring-boot-starter-web</artifactId><exclusions><exclusion><artifactId>spring-boot-starter-tomcat</artifactId></exclusion></exclusions>")
    for name, pom in (("jetty", jetty), ("scoped", scoped), ("excluded", excluded)):
        scan = bc.scan(_write(tmp_path / name, {**BOOT_FILES, "pom.xml": pom}))
        assert [f.code for f in scan.errors] == ["B010"], name


def test_a_pom_without_the_boot_parent_or_plugin_or_a_main_class_is_not_a_boot_build(tmp_path):
    pom = BOOT_POM.replace("<parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId><version>4.0.0</version></parent>", "") \
                  .replace("<build><plugins><plugin><groupId>org.springframework.boot</groupId><artifactId>spring-boot-maven-plugin</artifactId></plugin></plugins></build>", "")
    files = {**BOOT_FILES, "pom.xml": pom}
    del files["src/main/java/com/acme/ShopApplication.java"]
    files["src/main/java/com/acme/Other.java"] = "package com.acme;\nclass Other {}\n"
    scan = bc.scan(_write(tmp_path / "x", files))
    assert _codes(scan, "error") == {"B003", "B007"} and len([f for f in scan.errors if f.code == "B007"]) == 2


def test_a_pinned_version_of_a_managed_library_is_a_warning(tmp_path):
    pom = BOOT_POM.replace("<artifactId>spring-boot-starter-web</artifactId>", "<artifactId>spring-boot-starter-web</artifactId><version>3.0.0</version>")
    scan = bc.scan(_write(tmp_path / "w", {**BOOT_FILES, "pom.xml": pom}))
    assert scan.ok and _codes(scan) == {"W101"}


def test_a_deliberate_exception_is_kept_with_its_reason_and_reported(tmp_path):
    files = dict(BOOT_FILES)
    files["src/main/java/com/acme/Ds.java"] = textwrap.dedent("""
        package com.acme;
        public class Ds {
            // boot:keep a second, read-only reporting datasource (bound from spring.reporting.*)
            @Bean public DataSource reportingDataSource() { return null; }
            @Bean public DataSource other() { return null; }
        }
    """)
    pom = BOOT_POM.replace("</dependencies>", "<!-- boot:keep spring-ws has no starter in use here --><dependency><groupId>org.springframework.ws</groupId><artifactId>spring-ws-core</artifactId></dependency></dependencies>")
    files["pom.xml"] = pom
    scan = bc.scan(_write(tmp_path / "k", files))
    assert [f.message for f in scan.errors] == ["a hand-declared `DataSource` bean that Boot auto-configures"]
    assert scan.errors[0].line == 6                                  # the second one: only the first had a marker
    kept = " | ".join(scan.kept)
    assert "reporting datasource" in kept and "spring-ws has no starter" in kept
    assert "Kept on purpose" in scan.markdown()


def test_the_gradle_war_plugin_is_found(tmp_path):
    scan = bc.scan(_write(tmp_path / "g", {"build.gradle": "plugins { id 'war' }\n"}))
    assert "B001" in _codes(scan, "error")


# ── the pipeline ──────────────────────────────────────────────────────────────────────────────────────────

def _legacy_repo(tmp_path) -> Path:
    return _write(tmp_path / "shop", {"pom.xml": LEGACY_POM, **LEGACY_FILES})


def _tool(fn, **kw):
    return anyio.run(lambda: fn(**kw))


def _next(repo: Path) -> dict:
    step, _ = pipeline.next_step(Run.load(repo))
    return step


def _save(repo: Path, step_id: str, text: str, signalled: bool = False) -> None:
    assert _tool(mcp_server.save_output, step_id=step_id, content=text, workspace=str(repo)).startswith("Saved")
    if signalled:
        run = Run.load(repo)
        run.state["build_signalled"] = True
        run.save()
    pipeline.complete_step(Run.load(repo), step_id)


def test_the_boot_pipeline_is_the_java25_engine_with_the_boot_end_state_fixed(tmp_path):
    repo = _legacy_repo(tmp_path)
    run = pipeline.start(repo, "java-8-to-25-boot", migration_strategy="incremental", junit_upgrade=True)
    s = run.state
    assert s["pattern"] == "java-8-to-25" and s["profile"] == "boot" and s["springboot_upgrade"] is True
    assert s["migration_strategy"] == "incremental" and s["junit_upgrade"] is True
    assert "java-8-to-25-boot" in pipeline.summary(run) and "embedded Tomcat" in pipeline.summary(run)
    plain = pipeline.start(_legacy_repo(tmp_path / "p"), "java-8-to-25")
    assert plain.state["profile"] == "" and plain.state["springboot_upgrade"] is False         # unchanged
    assert "java-8-to-25-boot" in _tool(mcp_server.list_patterns)
    with pytest.raises(RunError):
        pipeline.start(_legacy_repo(tmp_path / "q"), "java-8-to-11", springboot_upgrade=True)


def test_the_overlay_skill_has_a_step_file_for_every_step_the_pipeline_asks_for():
    for step in ("plan", "modify", "validate", "fix", "review", "report"):
        assert skill_steps.exists(f"java-8-to-25-boot:{step}"), step
    assert (skill_steps.SKILLS_DIR / "java-8-to-25-boot" / "references" / "boot-conformance-rules.md").is_file()


def test_the_planner_is_told_the_end_state_and_to_follow_the_boot_skill(tmp_path):
    repo = _legacy_repo(tmp_path)
    pipeline.start(repo, "java-8-to-25-boot")
    run = Run.load(repo)
    run.state.update({"phase": "plan", "pi": 0, "selection_confirmed": True})
    run.save()
    step = _next(repo)
    q = step["query"]
    assert step["id"] == "plan-java-8-to-25"
    assert "the `java-8-to-25-boot` skill's `references/steps/plan.md`" in q
    assert "Profile: Java 8 → Java 25 + Spring Boot 4 (embedded Tomcat)" in q and "never a WAR" in q
    assert "## Spring Boot Upgrade Requested\ntrue" in q and "B001–B013" in q
    assert "| `java-8-to-25-boot` › modify |" in q and "| `java-8-to-25-boot` › review |" in q
    plain_repo = _legacy_repo(tmp_path / "plain")
    plain = pipeline.start(plain_repo, "java-8-to-25")
    plain.state.update({"phase": "plan", "pi": 0, "selection_confirmed": True})
    plain.save()
    assert "java-8-to-25-boot" not in _next(plain_repo)["query"]


BIGBANG_PLAN = "## 1. What Changes\n\n### Task 1.1: Convert to Spring Boot\n- Files: `pom.xml`\n"


def _to_boot(repo: Path) -> None:
    """What a successful conversion leaves behind."""
    for rel in list(LEGACY_FILES):
        (repo / rel).unlink(missing_ok=True)
    shutil.rmtree(repo / "src/main/webapp", ignore_errors=True)
    _write(repo, BOOT_FILES)


def test_a_bigbang_boot_run_cannot_pass_validation_until_the_result_is_a_boot_application(tmp_path):
    repo = _legacy_repo(tmp_path)
    run = pipeline.start(repo, "java-8-to-25-boot")
    run.write_doc("plan", BIGBANG_PLAN)
    run.state.update({"phase": "code", "plan_approved": True, "pi": 0, "code": None})
    run.save()
    modify = _next(repo)
    assert "java-8-to-25-boot` skill's `references/steps/modify.md" in modify["query"]
    _save(repo, modify["id"], "done")
    validate = _next(repo)
    assert validate["id"].startswith("validate-") and "references/steps/validate.md" in validate["query"]
    assert "## Spring Boot conformance" in validate["query"] and "B006" in validate["query"]
    # the validator says it passed (and signalled success): the scan still fails it
    _save(repo, validate["id"], json.dumps({"passed": True, "errors": [], "summary": "mvn package ok"}), signalled=True)
    result = json.loads(next((repo / ".modernizer/results").rglob("build_result*")).read_text())
    assert result["passed"] is False and any(e.startswith("BOOT: B001") for e in result["errors"])
    assert "not yet a Spring Boot 4 executable JAR" in result["summary"]
    fix = _next(repo)
    assert fix["id"].startswith("fix-") and "references/steps/fix.md" in fix["query"]
    # the fixer converts the application; the next validation passes and the run moves on to the review
    _to_boot(repo)
    _save(repo, fix["id"], "converted")
    validate2 = _next(repo)
    assert validate2["id"].startswith("validate-") and "meets the end state" in validate2["query"]
    _save(repo, validate2["id"], json.dumps({"passed": True, "errors": [], "summary": "ok"}), signalled=True)
    review = _next(repo)
    assert review["id"].startswith("review-")
    assert "boot_conformance.md" in review["query"] and "references/steps/review.md" in review["query"]
    assert "## Plan Conformance" in review["query"] and "newest GA 4.x" in modify["query"]


STAGED = ("## Stage 1: Modernize Build Systems (Maven/Gradle)\n\n### Task 1.1: Wrapper\n- Files: `pom.xml`\n\n"
          "## Stage 8: Convert WAR → Executable JAR (Embedded Container)\n\n### Task 8.1: Boot\n- Files: `pom.xml`\n")


def test_an_incremental_boot_run_checks_the_end_state_only_at_its_last_stage(tmp_path):
    repo = _legacy_repo(tmp_path)
    run = pipeline.start(repo, "java-8-to-25-boot", migration_strategy="incremental")
    run.write_doc("plan", STAGED)
    run.state.update({"phase": "code", "plan_approved": True, "pi": 0, "code": None})
    run.save()
    step = _next(repo)
    assert step["id"] == "modify-java-8-to-25-stage1-1.1"
    _save(repo, step["id"], "done")
    first = _next(repo)
    assert first["id"] == "validate-java-8-to-25-stage1-1"
    assert "Spring Boot conformance" not in first["query"]                 # a stage on the way is still a WAR
    _save(repo, first["id"], json.dumps({"passed": True, "errors": [], "summary": "ok"}), signalled=True)
    assert json.loads(next((repo / ".modernizer/results").rglob("build_result*stage1*")).read_text())["passed"] is True
    last = _next(repo)
    assert last["id"] == "modify-java-8-to-25-stage8-8.1" and "java-8-to-25-boot` skill's `references/steps/modify.md" in last["query"]
    _save(repo, last["id"], "done")
    final = _next(repo)
    assert final["id"] == "validate-java-8-to-25-stage8-1" and "## Spring Boot conformance" in final["query"]
    _save(repo, final["id"], json.dumps({"passed": True, "errors": [], "summary": "ok"}), signalled=True)
    results = {p.name: json.loads(p.read_text()) for p in (repo / ".modernizer/results").rglob("build_result*")}
    assert results["build_result_stage8.json"]["passed"] is False and results["build_result_stage1.json"]["passed"] is True


def test_the_boot_parent_version_rule_is_printed_only_where_the_boot_version_is_chosen(tmp_path):
    repo = _legacy_repo(tmp_path)
    run = pipeline.start(repo, "java-8-to-25-boot", migration_strategy="incremental")
    marker = "Spring Boot parent version (the one version you choose)"
    assert marker not in pipeline._approved(run, "java-8-to-25", 1)
    assert marker not in pipeline._approved(run, "java-8-to-25", 4)      # Boot 2.7 / 3.x stages name their own line
    assert marker not in pipeline._approved(run, "java-8-to-25", 5)
    assert marker in pipeline._approved(run, "java-8-to-25", 7)
    assert marker in pipeline._approved(run, "java-8-to-25", 8)
    assert marker in pipeline._approved(run, "java-8-to-25")             # a big-bang run has one stage


def test_the_camel_knowledge_file_is_tagged_so_it_is_read_only_for_camel_repositories():
    from agents.shared import knowledge_slice
    path = skill_steps.SKILLS_DIR / "java-8-to-25-boot" / "references" / "camel-to-boot.md"
    sections = knowledge_slice.parse(path.read_text())
    assert sections[0].terms == ["camel"]
    assert "camel-spring-boot-xml-starter" in path.read_text() and "camel-spring-xml-starter" not in path.read_text()


def test_skill_files_no_longer_contradict_themselves_about_tests_and_the_web_starter():
    boot = skill_steps.SKILLS_DIR / "java-8-to-25-boot" / "references"
    testing = (boot / "testing-to-boot.md").read_text()
    assert "Which tests change" in testing and "stays on `@RunWith(SpringRunner.class)`" not in testing
    base = (skill_steps.SKILLS_DIR / "java-8-to-25" / "references" / "boot27-on-war.md").read_text()
    assert "junit-vintage-engine" in base and "jackson-bom.version" in base
