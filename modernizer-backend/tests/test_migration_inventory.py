"""
The deterministic inventories that replace the reverse-engineering agents for
java-8-to-25, solr-4-to-9, oracle-19c-to-23ai and tibco-ems-to-pubsub.

Each fixture plants the constructs the pattern's own RE checklist
(agents/skills/<pattern>-re/references/*-baseline-facts.md) says to look for;
the tests assert every one is found with its real path and line, that the
document parses into the four sections the rest of the workflow reads, and that
the file-by-file rows land in the Technical Specification (the only analysis
section a planner is given).
"""
import re
from pathlib import Path

import pytest

import main
from agents.shared import migration_inventory as mi

JAVA25 = {
    "pom.xml": """<project><modelVersion>4.0.0</modelVersion>
  <groupId>com.acme</groupId><artifactId>shop-parent</artifactId><version>1.0</version><packaging>pom</packaging>
  <properties><maven.compiler.source>1.8</maven.compiler.source><maven.compiler.target>1.8</maven.compiler.target>
    <spring.version>4.3.30.RELEASE</spring.version></properties>
  <modules><module>web</module></modules>
  <dependencyManagement><dependencies>
    <dependency><groupId>org.springframework</groupId><artifactId>spring-webmvc</artifactId><version>${spring.version}</version></dependency>
  </dependencies></dependencyManagement>
</project>""",
    "web/pom.xml": """<project><modelVersion>4.0.0</modelVersion>
  <parent><groupId>com.acme</groupId><artifactId>shop-parent</artifactId><version>1.0</version></parent>
  <artifactId>shop-web</artifactId><packaging>war</packaging>
  <build><finalName>shop</finalName></build>
  <dependencies>
    <dependency><groupId>org.springframework</groupId><artifactId>spring-webmvc</artifactId></dependency>
    <dependency><groupId>net.sf.ehcache</groupId><artifactId>ehcache</artifactId><version>2.10.6</version></dependency>
    <dependency><groupId>log4j</groupId><artifactId>log4j</artifactId><version>1.2.17</version></dependency>
    <dependency><groupId>org.mockito</groupId><artifactId>mockito-all</artifactId><version>1.10.19</version><scope>test</scope></dependency>
  </dependencies>
</project>""",
    "web/src/main/java/com/acme/web/OrderController.java": """package com.acme.web;
import javax.servlet.http.HttpServletRequest;
import org.apache.log4j.Logger;
import org.springframework.web.bind.annotation.RequestMapping;
import sun.misc.BASE64Encoder;
@org.springframework.stereotype.Controller
public class OrderController {
    private static final Logger LOG = Logger.getLogger(OrderController.class);
    @RequestMapping("/orders")
    public String list(HttpServletRequest req) { return new BASE64Encoder().encode(new byte[0]); }
}
""",
    "web/src/main/java/com/acme/cache/Caches.java": """package com.acme.cache;
import net.sf.ehcache.CacheManager;
public class Caches { CacheManager cm = CacheManager.create(); }
""",
    "web/src/main/java/com/acme/script/Rules.java": """package com.acme.script;
import javax.script.ScriptEngineManager;
public class Rules { Object e = new ScriptEngineManager().getEngineByName("nashorn"); }
""",
    "web/src/main/java/com/acme/dao/OrderDao.java": """package com.acme.dao;
import javax.persistence.Entity;
@Entity public class OrderDao { org.springframework.jdbc.core.JdbcTemplate jdbc; }
""",
    "web/src/main/webapp/WEB-INF/web.xml": "<web-app><servlet><servlet-name>d</servlet-name></servlet><url-pattern>/app/*</url-pattern></web-app>",
    "web/src/main/webapp/WEB-INF/jsp/orders.jsp": "<%@ page import=\"java.util.*\" %><html></html>",
    "web/src/test/java/com/acme/OrderControllerTest.java": """package com.acme;
import org.junit.Test;
public class OrderControllerTest { @Test public void lists() {} }
""",
    "web/target/classes/Stale.java": "import net.sf.ehcache.CacheManager;",
}

SOLR = {
    "pom.xml": """<project><groupId>com.acme</groupId><artifactId>search</artifactId><version>1</version>
  <properties><solr.version>4.10.4</solr.version></properties>
  <dependencies><dependency><groupId>org.apache.solr</groupId><artifactId>solr-solrj</artifactId><version>${solr.version}</version></dependency></dependencies>
</project>""",
    "solr/collection1/conf/schema.xml": """<schema name="products" version="1.5">
  <fieldType name="tint" class="solr.TrieIntField" precisionStep="8"/>
  <fieldType name="location" class="solr.LatLonType" subFieldSuffix="_coordinate"/>
  <field name="price" type="tint" indexed="true"/>
  <field name="stock" type="tint" indexed="true"/>
  <field name="_version_" type="long" indexed="false" stored="true"/>
</schema>""",
    "solr/collection1/conf/solrconfig.xml": """<config>
  <luceneMatchVersion>4.10.4</luceneMatchVersion>
  <lib dir="../../../contrib/extraction/lib" regex=".*\\.jar"/>
  <requestHandler name="/update/extract" class="solr.extraction.ExtractingRequestHandler"/>
</config>""",
    "src/main/java/com/acme/search/ProductSearch.java": """package com.acme.search;
import org.apache.solr.client.solrj.impl.HttpSolrServer;
public class ProductSearch {
  HttpSolrServer server = new HttpSolrServer("http://localhost:8983/solr");
  void q(org.apache.solr.client.solrj.SolrQuery q) { q.setQueryType("/select"); }
}
""",
}

ORACLE = {
    "db/schema/orders.sql": """CREATE TABLE orders (
  id RAW(16) DEFAULT SYS_GUID(),
  notes LONG,
  active NUMBER(1)
);
CREATE OR REPLACE VIEW open_orders AS SELECT * FROM orders WHERE active = 1;
CREATE SEQUENCE order_seq;
""",
    "db/plsql/order_pkg.pkb": """CREATE OR REPLACE PACKAGE BODY order_pkg AS
  PROCEDURE tree IS BEGIN
    FOR r IN (SELECT id FROM orders CONNECT BY PRIOR id = parent_id) LOOP NULL; END LOOP;
    EXECUTE IMMEDIATE 'ALTER SESSION SET optimizer_features_enable = ''11.2.0.4''';
    x := DBMS_LOB.SUBSTR(c, 32767);
  END;
END order_pkg;
""",
    "db/aq/queues.sql": "BEGIN DBMS_AQADM.CREATE_QUEUE_TABLE(queue_table => 'q', compatible => '10.0'); END;\n",
    "pom.xml": """<project><groupId>com.acme</groupId><artifactId>orders</artifactId><version>1</version>
  <dependencies><dependency><groupId>com.oracle.database.jdbc</groupId><artifactId>ojdbc8</artifactId><version>12.2.0.1</version></dependency>
  <dependency><groupId>commons-dbcp</groupId><artifactId>commons-dbcp</artifactId><version>1.4</version></dependency></dependencies>
</project>""",
    "src/main/resources/db.properties": "db.url=jdbc:oracle:thin:scott/tiger@//dbhost:1521/ORCL\n",
}

TIBCO = {
    "pom.xml": """<project><groupId>com.acme</groupId><artifactId>orders-integration</artifactId><version>1</version>
  <dependencies><dependency><groupId>com.tibco</groupId><artifactId>tibjms</artifactId><version>8.4</version></dependency>
  <dependency><groupId>javax.jms</groupId><artifactId>jms</artifactId><version>1.1</version></dependency></dependencies>
</project>""",
    "src/main/java/com/acme/OrderPublisher.java": """package com.acme;
import javax.jms.*;
import com.tibco.tibjms.TibjmsConnectionFactory;
public class OrderPublisher {
  void send() throws JMSException {
    Connection c = new TibjmsConnectionFactory("tcp://ems-prod:7222").createConnection();
    Session s = c.createSession(false, Session.CLIENT_ACKNOWLEDGE);
    MessageProducer p = s.createProducer(s.createQueue("orders.created"));
    TextMessage m = s.createTextMessage("{}");
    m.setStringProperty("region", "EU");
    p.send(m);
  }
}
""",
    "src/main/java/com/acme/AuditConsumer.java": """package com.acme;
import javax.jms.*;
public class AuditConsumer implements MessageListener {
  void start(Session s) throws JMSException {
    Topic t = s.createTopic("audit.events");
    MessageConsumer c = s.createDurableSubscriber(t, "audit-sub", "region = 'EU' AND priority > 5", false);
    c.setMessageListener(this);
  }
  public void onMessage(Message m) { try { m.acknowledge(); } catch (JMSException e) {} }
}
""",
    "config/ems.substvar": "<globalVariable><name>EMS_URL</name><value>ssl://ems-dr:7243</value></globalVariable>",
    "src/main/resources/application.properties": "queue.orders=orders.created\n",
}

FIXTURES = {"java-8-to-25": JAVA25, "solr-4-to-9": SOLR, "oracle-19c-to-23ai": ORACLE, "tibco-ems-to-pubsub": TIBCO}

# (finding name, file, line) the inventory must report for each fixture.
EXPECTED = {
    "java-8-to-25": [
        ("javax EE namespace", "web/src/main/java/com/acme/web/OrderController.java", 2),
        ("log4j 1.2", "web/src/main/java/com/acme/web/OrderController.java", 3),
        ("sun.misc BASE64 encoder/decoder", "web/src/main/java/com/acme/web/OrderController.java", 5),
        ("Ehcache 2", "web/src/main/java/com/acme/cache/Caches.java", 2),
        ("Nashorn", "web/src/main/java/com/acme/script/Rules.java", 3),
        ("Mockito 1.x", "web/pom.xml", 9),
        ("JUnit 4", "web/src/test/java/com/acme/OrderControllerTest.java", 2),
        ("Java 8 compiler level", "pom.xml", 3),
    ],
    "solr-4-to-9": [
        ("Trie field types", "solr/collection1/conf/schema.xml", 2),
        ("LatLonType", "solr/collection1/conf/schema.xml", 3),
        ("old schema version", "solr/collection1/conf/schema.xml", 1),
        ("_version_ field", "solr/collection1/conf/schema.xml", 6),
        ("legacy solrconfig", "solr/collection1/conf/solrconfig.xml", 2),
        ("Solr 4 contrib lib path", "solr/collection1/conf/solrconfig.xml", 3),
        ("Solr Cell extraction handler", "solr/collection1/conf/solrconfig.xml", 4),
        ("SolrJ 4 server classes", "src/main/java/com/acme/search/ProductSearch.java", 2),
        ("SolrJ setQueryType", "src/main/java/com/acme/search/ProductSearch.java", 5),
    ],
    "oracle-19c-to-23ai": [
        ("LONG / LONG RAW column", "db/schema/orders.sql", 3),
        ("SYS_GUID key", "db/schema/orders.sql", 2),
        ("boolean-like column", "db/schema/orders.sql", 4),
        ("CONNECT BY", "db/plsql/order_pkg.pkb", 3),
        ("optimizer feature pin", "db/plsql/order_pkg.pkb", 4),
        ("32767-byte boundary", "db/plsql/order_pkg.pkb", 5),
        ("AQ queue table", "db/aq/queues.sql", 1),
        ("legacy Oracle JDBC driver", "pom.xml", 2),
        ("old connection pool", "pom.xml", 3),
    ],
    "tibco-ems-to-pubsub": [
        ("TIBCO EMS client", "src/main/java/com/acme/OrderPublisher.java", 3),
        ("JMS API", "src/main/java/com/acme/AuditConsumer.java", 2),
        ("acknowledgement mode", "src/main/java/com/acme/OrderPublisher.java", 7),
        ("JMS message properties", "src/main/java/com/acme/OrderPublisher.java", 10),
        ("durable subscriber", "src/main/java/com/acme/AuditConsumer.java", 6),
        ("message selector", "src/main/java/com/acme/AuditConsumer.java", 6),
        ("EMS server URL", "config/ems.substvar", 1),
    ],
}


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def _blocker_rows(tech: str) -> list[tuple[str, list[int], str]]:
    section = tech.split("## Legacy Stack Blockers", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        m = re.match(r"\| `([^`]+)` \| ([\d, …]+) \| ([^|]+) \|", line)
        if m:
            rows.append((m.group(1), [int(n) for n in re.findall(r"\d+", m.group(2))], m.group(3).strip()))
    return rows


@pytest.fixture(params=sorted(FIXTURES))
def generated(request, tmp_path):
    pattern = request.param
    root = _write(tmp_path / pattern, FIXTURES[pattern])
    return pattern, root, mi.to_document(pattern, str(root))


def test_every_planted_construct_is_found_at_its_real_path_and_line(generated):
    pattern, root, doc = generated
    _, _, tech, _ = main._parse_re_sections(doc)
    rows = _blocker_rows(tech)
    for name, path, line in EXPECTED[pattern]:
        assert (root / path).exists()
        match = [r for r in rows if r[0] == path and r[2] == name]
        assert match, f"{pattern}: {name} not reported for {path}\n{tech}"
        assert line in match[0][1], f"{pattern}: {name} in {path} reported at {match[0][1]}, expected {line}"
    # Every reported path is real; build output is never scanned.
    for path, _, _ in rows:
        assert (root / path).is_file(), path
        assert "/target/" not in f"/{path}"


def test_document_parses_into_the_four_sections_the_workflow_reads(generated):
    pattern, _, doc = generated
    analysis, brd, tech, tests = main._parse_re_sections(doc)
    assert all(s.strip() for s in (analysis, brd, tech, tests))
    assert "no language model read this repository" in brd
    # The planner is given brd / technical_spec / test_inventory only; the
    # file-by-file facts must be in the specification, not the analysis.
    assert "## Legacy Stack Blockers" in tech and "## Legacy Stack Blockers" not in analysis
    assert "## Repo Facts" in tech and "## Behaviour Inventory" in tech


def test_pattern_specific_facts(tmp_path):
    java = mi.to_document("java-8-to-25", str(_write(tmp_path / "j", JAVA25)))
    tech = main._parse_re_sections(java)[2]
    assert "| `web/pom.xml` | war | shop |" in tech                          # packaging + finalName
    assert "org.springframework:spring-webmvc | 4.3.30.RELEASE" in tech     # managed version via parent property
    assert "JPA/Hibernate entity, JdbcTemplate" in tech                     # persistence layer
    assert "| `web/src/main/webapp/WEB-INF/jsp/` | 1 JSP/tag file(s) |" in tech
    assert "| Spring MVC" in tech or "OrderController" in tech

    solr = main._parse_re_sections(mi.to_document("solr-4-to-9", str(_write(tmp_path / "s", SOLR))))[2]
    assert "| `solr/collection1/conf/schema.xml` | tint | `solr.TrieIntField` | 2 |" in solr
    assert "org.apache.solr:solr-solrj | 4.10.4" in solr                    # property-resolved version
    assert "| `solr/collection1/conf/solrconfig.xml` | `4.10.4` |" in solr
    assert "| request handler | `/update/extract` | `solr/collection1/conf/solrconfig.xml:4` |" in solr

    ora = main._parse_re_sections(mi.to_document("oracle-19c-to-23ai", str(_write(tmp_path / "o", ORACLE))))[2]
    assert "| TABLE | 1 |" in ora and "| VIEW | 1 |" in ora and "| PACKAGE BODY | 1 |" in ora
    assert "scott/tiger" not in ora and "jdbc:oracle:thin:<redacted>@//dbhost:1521/ORCL" in ora
    assert "| package body | `order_pkg` | `db/plsql/order_pkg.pkb:1` |" in ora   # behaviour to preserve
    assert "| view | `open_orders` | `db/schema/orders.sql:6` |" in ora

    tib = main._parse_re_sections(mi.to_document("tibco-ems-to-pubsub", str(_write(tmp_path / "t", TIBCO))))[2]
    assert "| queue | `orders.created` | `src/main/java/com/acme/OrderPublisher.java:8` |" in tib
    assert "| topic | `audit.events` | `src/main/java/com/acme/AuditConsumer.java:5` |" in tib
    assert "| queue | `orders = orders.created` |" in tib
    assert "`region = 'EU' AND priority > 5`" in tib                       # selector verbatim
    assert "| `src/main/java/com/acme/OrderPublisher.java` | producer |" in tib
    assert "| `src/main/java/com/acme/AuditConsumer.java` | consumer |" in tib
    assert "`tcp://ems-prod:7222`" in tib and "`ssl://ems-dr:7243`" in tib


def test_rows_over_the_cap_are_counted_not_dropped(tmp_path):
    files = {f"src/main/java/p{i}/C{i}.java": "import net.sf.ehcache.CacheManager;\n" for i in range(30)}
    doc = mi.to_document("java-8-to-25", str(_write(tmp_path, files)), max_rows=10)
    tech = main._parse_re_sections(doc)[2]
    assert len(_blocker_rows(tech)) == 10
    assert "20 more finding rows not listed here" in tech
    rollup = tech.split("## Directory Rollup", 1)[1].split("\n## ", 1)[0]
    assert rollup.count("| Ehcache 2 |") == 30                               # every directory still counted


def test_empty_repository_still_produces_a_valid_document(tmp_path):
    for pattern in mi.SPECS:
        analysis, brd, tech, tests = main._parse_re_sections(mi.to_document(pattern, str(tmp_path)))
        assert analysis and brd and tech and tests
        assert "none found" in tech


def test_secrets_are_never_reproduced_as_evidence(tmp_path):
    files = {
        "src/main/resources/app.properties": "ems.password=Sup3rS3cret tcp://ems:7222\n",
        "src/main/java/A.java": "import javax.jms.Queue; // url tcp://admin:hunter2@ems:7222\n",
    }
    doc = mi.to_document("tibco-ems-to-pubsub", str(_write(tmp_path, files)))
    assert "Sup3rS3cret" not in doc and "hunter2" not in doc
    assert "| `src/main/resources/app.properties` | 1 | EMS server URL | `(line names a credential" in doc


# ---------------------------------------------------------------------------
# End to end through the real workflow and the real ADK planner agents, with
# only the model scripted: upload state -> inventory -> brd-review ->
# planner (its real instruction template) -> plan-review -> code step.
# ---------------------------------------------------------------------------
import asyncio
import json

from google.adk.models import BaseLlm, LlmResponse
from google.genai import types

from agents import APP_NAME, USER_ID, session_service
from agents.java_8_to_25 import agents as j25_agents
from agents.oracle_19c_to_23ai import agents as oracle_agents
from agents.solr_4_to_9 import agents as solr_agents
from agents.tibco_ems_to_pubsub import agents as tibco_agents

PLANNERS = {
    "java-8-to-25": j25_agents.planner_agent,
    "solr-4-to-9": solr_agents.planner_agent,
    "oracle-19c-to-23ai": oracle_agents.planner_agent,
    "tibco-ems-to-pubsub": tibco_agents.planner_agent,
}


class _Planner(BaseLlm):
    """Records every request the planner sends and answers with a plan."""
    requests: list = []

    async def generate_content_async(self, req, stream=False):
        self.requests.append(req)
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="# Migration Plan\n\nscripted")]))


@pytest.mark.parametrize("pattern", sorted(FIXTURES))
def test_end_to_end_the_planner_is_templated_with_the_inventory(monkeypatch, tmp_path, pattern):
    workspace = _write(tmp_path / "ws", FIXTURES[pattern])
    baseline = _write(tmp_path / "base", FIXTURES[pattern])
    graph = json.dumps(main.dependency_graph.build_dependency_graph(str(workspace), pattern))

    model = _Planner(model="scripted")
    model.requests = []
    monkeypatch.setattr(PLANNERS[pattern], "model", model)
    code_steps = []

    async def code_step(session_id, *args, **kwargs):
        code_steps.append(session_id)

    # The code steps are untouched by this change and have their own tests.
    monkeypatch.setattr(main, "_run_workspace_code_step", code_step)
    monkeypatch.setattr(main, "_run_java8_incremental_code_step", code_step)

    state = main._initial_state(pattern, str(workspace), str(baseline), graph, "bigbang", False, False)
    sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
    main._sse_queues[sid] = asyncio.Queue()
    for gates in (main._brd_gates, main._plan_gates, main._companion_gates):
        gates[sid] = asyncio.Event()
        gates[sid].set()
    asyncio.run(main._run_workflow(sid))

    events = []
    while not main._sse_queues[sid].empty():
        raw = main._sse_queues[sid].get_nowait()
        if raw:
            events += [json.loads(l[6:]) for l in raw.splitlines() if l.startswith("data: ")]
    assert not [e for e in events if e["type"] == "error"], events
    assert any(e["type"] == "workflow-complete" for e in events)
    assert code_steps == [sid]

    # The planner was the first and only model call of the analysis + planning phases.
    assert len(model.requests) == 1
    system = str(model.requests[0].config.system_instruction)
    assert "no language model read this repository" in system          # {brd}
    assert "## Legacy Stack Blockers" in system                          # {technical_spec}
    assert "Tests" in system                                             # {test_inventory}
    for _, path, _ in EXPECTED[pattern]:
        assert f"`{path}`" in system, path                               # real paths reach the planner
    assert "{brd}" not in system and "{technical_spec}" not in system    # every placeholder resolved
