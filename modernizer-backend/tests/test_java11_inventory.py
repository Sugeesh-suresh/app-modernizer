"""
The deterministic Java 11 inventory: java-8-to-11's analysis step with no model.

The fixture mirrors a real multi-POM WildFly monorepo (a parent POM with
properties, an EAR, EJB, WAR with JSPs, shared and test modules) with a known
set of Java 11 problems planted in it. The inventory must find exactly those,
render them in the four-section format every later step reads, and hand the
planner real file paths — without a single model call before planning.
"""
import asyncio
import json
from pathlib import Path

import pytest

import main
from agents import APP_NAME, USER_ID, config, session_service
from agents.java_8_to_11 import inventory
from agents.shared.plan_coverage import parse_plan_manifest

P = "java-8-to-11"
MODULES = ["cdi", "pwm-config", "pwm-ear", "pwm-ejb", "pwm-shared", "pwm-standards", "pwm-test", "pwm-turnin", "pwm-web"]
BLOCKERS = {
    "pwm-shared/src/main/java/com/acme/shared/XmlUtil.java": ("JAXB (javax.xml.bind)", [2, 3]),
    "pwm-ejb/src/main/java/com/acme/ejb/Init.java": ("Common Annotations", [2]),
    "pwm-ejb/src/main/java/com/acme/ejb/TokenBean.java": ("sun.misc BASE64 encoder/decoder", [3]),
}


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def titan(tmp_path) -> Path:
    root = tmp_path / "titan-master"
    _write(root, "pom.xml", f"""<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>
<groupId>com.acme</groupId><artifactId>titan-master</artifactId><version>1.0</version><packaging>pom</packaging>
<modules>{''.join(f'<module>{m}</module>' for m in MODULES)}</modules>
<properties><java.version>1.8</java.version><spring.version>4.3.30.RELEASE</spring.version><mockito.version>1.10.19</mockito.version></properties>
<dependencyManagement><dependencies>
 <dependency><groupId>org.springframework</groupId><artifactId>spring-core</artifactId><version>${{spring.version}}</version></dependency>
 <dependency><groupId>org.mockito</groupId><artifactId>mockito-all</artifactId><version>${{mockito.version}}</version></dependency>
 <dependency><groupId>org.jboss.spec</groupId><artifactId>jboss-javaee-7.0</artifactId><version>1.1.1.Final</version><scope>provided</scope></dependency>
</dependencies></dependencyManagement>
<build><pluginManagement><plugins>
 <plugin><artifactId>maven-compiler-plugin</artifactId><version>3.1</version><configuration><source>${{java.version}}</source><target>${{java.version}}</target></configuration></plugin>
 <plugin><artifactId>maven-war-plugin</artifactId><version>2.6</version></plugin>
 <plugin><artifactId>maven-surefire-plugin</artifactId><version>2.22.2</version></plugin>
 <plugin><groupId>org.wildfly.plugins</groupId><artifactId>wildfly-maven-plugin</artifactId><version>1.2.1.Final</version></plugin>
</plugins></pluginManagement></build></project>""")
    for m in MODULES:
        packaging = {"pwm-ear": "ear", "pwm-web": "war", "pwm-ejb": "ejb"}.get(m, "jar")
        deps = {
            "pwm-shared": "<dependency><groupId>org.springframework</groupId><artifactId>spring-core</artifactId></dependency>",
            "pwm-test": "<dependency><groupId>org.mockito</groupId><artifactId>mockito-all</artifactId><scope>test</scope></dependency>",
        }.get(m, "")
        _write(root, f"{m}/pom.xml", f"""<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>
<parent><groupId>com.acme</groupId><artifactId>titan-master</artifactId><version>1.0</version></parent>
<artifactId>{m}</artifactId><packaging>{packaging}</packaging><dependencies>{deps}</dependencies>
<build><finalName>{m}</finalName></build></project>""")
        for i in range(3):
            _write(root, f"{m}/src/main/java/com/acme/{m.replace('-', '')}/C{i}.java", f"package com.acme;\nclass C{i} {{ }}\n")
    _write(root, "pwm-shared/src/main/java/com/acme/shared/XmlUtil.java",
           "package com.acme;\nimport javax.xml.bind.JAXBContext;\nimport javax.xml.bind.Marshaller;\nclass XmlUtil {}\n")
    _write(root, "pwm-ejb/src/main/java/com/acme/ejb/TokenBean.java",
           "package com.acme;\nimport javax.ejb.Stateless;\nimport sun.misc.BASE64Encoder;\n@Stateless\n"
           "public class TokenBean { String t(byte[] b) { return new BASE64Encoder().encode(b); } }\n")
    _write(root, "pwm-ejb/src/main/java/com/acme/ejb/Init.java",
           "package com.acme;\nimport javax.annotation.PostConstruct;\n"
           "class Init { @PostConstruct void go() { new java.text.SimpleDateFormat(\"dd/MM\"); } }\n")
    _write(root, "pwm-web/src/main/java/com/acme/web/OrderServlet.java",
           "package com.acme;\n@javax.servlet.annotation.WebServlet(\"/orders\")\npublic class OrderServlet {}\n")
    _write(root, "pwm-web/src/main/webapp/token.jsp",
           '<%@ page import="sun.misc.BASE64Encoder" %>\n<%= new BASE64Encoder().encode("x".getBytes()) %>\n')
    _write(root, "pwm-web/src/main/webapp/WEB-INF/web.xml",
           "<web-app><servlet-mapping><servlet-name>a</servlet-name><url-pattern>/legacy/*</url-pattern></servlet-mapping></web-app>")
    _write(root, "pwm-web/src/main/webapp/WEB-INF/jboss-web.xml", "<jboss-web><context-root>/pwm</context-root></jboss-web>")
    _write(root, "pwm-test/src/test/java/com/acme/OrderTest.java",
           "import org.junit.Test;\nimport org.mockito.Mockito;\npublic class OrderTest { @Test public void t() {} }\n")
    _write(root, "pwm-web/target/classes/Stale.java", "import javax.xml.bind.JAXB;\n")   # build output
    _write(root, "pwm-web/src/main/java/com/acme/web/Notes.java", "// javax.xml.bind is gone in 11\nclass Notes {}\n")
    return root


class TestInventory:
    def test_finds_exactly_the_planted_blockers_with_lines(self, titan):
        inv = inventory.build(str(titan))
        found = {f: (cat, lines) for cat, rows in inv.blockers.items() for f, lines, _ in rows
                 if any(c.name == cat and c.change for c in inventory.CATEGORIES)}
        comment = "pwm-web/src/main/java/com/acme/web/Notes.java"
        assert found.pop(comment)[0] == "JAXB (javax.xml.bind)"   # a comment still matches: reported, judged later
        assert found == BLOCKERS
        assert not any("target/" in f for rows in inv.blockers.values() for f, _, _ in rows)

    def test_build_facts_resolve_properties_through_the_parent(self, titan):
        inv = inventory.build(str(titan))
        plugins = {(p, i): (v, f) for p, i, v, f in inv.build_findings}
        assert plugins[("pom.xml", "org.apache.maven.plugins:maven-compiler-plugin")][0] == "3.1"
        assert plugins[("pom.xml", "org.apache.maven.plugins:maven-war-plugin")][1].startswith("must move")
        assert ("pom.xml", "org.apache.maven.plugins:maven-surefire-plugin") not in plugins  # 2.22.2 is fine
        deps = {(p, c): (v, f) for p, c, v, s, f in inv.dependency_rows}
        assert deps[("pwm-shared/pom.xml", "org.springframework:spring-core")][0] == "4.3.30.RELEASE"
        assert deps[("pwm-test/pom.xml", "org.mockito:mockito-all")][1].startswith("must change")
        assert {p.packaging for p in inv.modules} >= {"ear", "ejb", "war", "pom"}

    def test_endpoints_risks_jsp_frozen_and_wildfly(self, titan):
        inv = inventory.build(str(titan))
        endpoints = {(k, v) for k, v, _ in inv.endpoints}
        assert ("Servlet", '"/orders"') in endpoints and ("EJB", "Stateless") in endpoints
        assert ("web.xml url-pattern", "/legacy/*") in endpoints
        assert [f for f, _, _ in inv.blockers["locale-sensitive formatting (CLDR default since Java 9)"]] == \
            ["pwm-ejb/src/main/java/com/acme/ejb/Init.java"]
        assert [f for f, _, _ in inv.jsp_risks["sun.misc BASE64 encoder/decoder"]] == ["pwm-web/src/main/webapp/token.jsp"]
        assert inv.frozen[(next(k for k, p in inv.frozen if p == "pwm-web/src/main/webapp/"), "pwm-web/src/main/webapp/")] == 3
        assert inventory.frozen_unit("pwm-ejb/src/main/resources/META-INF/persistence.xml") == "pwm-ejb/src/main/resources/META-INF/"
        assert inventory.frozen_unit("wildfly/standalone.xml") == "wildfly/standalone.xml"
        assert any("wildfly-maven-plugin" in e for e in inv.wildfly) and any("jboss-javaee-7.0" in e for e in inv.wildfly)

    def test_the_document_parses_into_four_complete_sections(self, titan):
        doc = inventory.to_document(inventory.build(str(titan)))
        analysis, brd, spec, tests = main._parse_re_sections(doc)
        assert all(part.strip() for part in (analysis, brd, spec, tests))
        assert "Automated warning" not in brd
        # The planner reads the Technical Specification, never the Analysis section.
        assert "pwm-ejb/src/main/java/com/acme/ejb/TokenBean.java" in spec
        assert "frozen — unchanged" in brd

    def test_frozen_rows_are_held_to_no_change_by_plan_conformance(self, titan):
        doc = inventory.to_document(inventory.build(str(titan)))
        planned = {e.path: e for e in parse_plan_manifest(doc)}
        assert planned["pwm-web/src/main/webapp/"].no_change_expected
        # Never the whole module: its Java sources (OrderServlet.java) may and must change.
        assert "pwm-web/" not in planned and "pwm-web/src/" not in planned

    def test_row_caps_are_stated_never_silent(self, titan):
        doc = inventory.to_document(inventory.build(str(titan)), max_rows=1)
        assert "more blocker rows not listed here" in doc and "must still be planned" in doc


# ---------------------------------------------------------------------------
# In the workflow
# ---------------------------------------------------------------------------

def _run_to_plan(monkeypatch, root: Path, feedback: str | None = None):
    seen: list[tuple[str, dict]] = []

    async def fake_run_step(session_id, step_key, pattern, message, sse_event_type):
        state = await main._get_state(session_id)
        seen.append((step_key, dict(state)))
        await main._update_state(session_id, {"plan": "# plan"})

    monkeypatch.setattr(main, "_run_step", fake_run_step)
    # The graph is computed at upload in the real flow (main.upload_repository).
    graph_json = json.dumps(main.dependency_graph.build_dependency_graph(str(root), P))
    state = main._initial_state(P, str(root), str(root) + "-base", graph_json, "bigbang", False, False)
    sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
    main._sse_queues[sid] = asyncio.Queue()
    asyncio.run(main._run_bundle_re(sid, [P], feedback=feedback))
    asyncio.run(main._run_bundle_plan(sid, [P]))
    return seen, asyncio.run(main._get_state(sid))


def test_no_model_call_before_the_planner_and_the_planner_gets_real_paths(monkeypatch, titan):
    seen, _ = _run_to_plan(monkeypatch, titan)
    assert [step for step, _ in seen] == ["plan"]
    planner_input = seen[0][1]
    for path in BLOCKERS:
        assert path in planner_input["brd"] + planner_input["technical_spec"]
    assert "org.springframework:spring-core" in planner_input["technical_spec"]
    assert "Dependency Graph & Migration Groups" in planner_input["technical_spec"]


def test_refine_keeps_reviewer_notes_without_a_model(monkeypatch, titan):
    seen, state = _run_to_plan(monkeypatch, titan, feedback="Treat pwm-turnin as out of scope.")
    assert [step for step, _ in seen] == ["plan"]
    assert "## Reviewer Notes" in state["brd"] and "pwm-turnin as out of scope" in state["brd"]


def test_agent_analysis_is_still_available_by_setting(monkeypatch, titan):
    monkeypatch.setattr(config, "JAVA11_ANALYSIS", "agent")
    called = []

    async def fake_agent_re(session_id, message, refine=False):
        called.append(refine)
        await main._update_state(session_id, {"analysis": inventory.to_document(inventory.build(str(titan)))})

    monkeypatch.setattr(main, "_run_java11_re", fake_agent_re)
    _run_to_plan(monkeypatch, titan)
    assert called == [False]
