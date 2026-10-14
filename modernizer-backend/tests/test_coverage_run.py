"""The test-coverage pipeline (cli/coverage_run.py, agents/shared/coverage.py, agents/test_coverage/tools.py):
the engine's pieces on their own, then a whole run on a JSP + servlet repository with real Maven and JaCoCo,
the test playing the tester and fixer agents."""
import json
import shutil
import textwrap
from pathlib import Path

import anyio
import pytest

from agents import config
from agents.shared import coverage
from cli import coverage_run, mcp_server, pipeline
from cli.runstate import Run, RunError

FIXTURE = Path(__file__).parent / "fixtures" / "inventory-jsp-webapp"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MODERNIZER_WORKSPACE", raising=False)


# ── the engine, without a build ───────────────────────────────────────────────────────────────────────────

JACOCO = """<?xml version="1.0"?>
<report name="x"><package name="com/acme/shop">
 <class name="com/acme/shop/Order" sourcefilename="Order.java"><method name="getId" desc="()J" line="3"/><method name="total" desc="()I" line="9"/></class>
 <class name="com/acme/shop/Dto" sourcefilename="Dto.java"><method name="getName" desc="()S" line="3"/><method name="setName" desc="(S)V" line="4"/></class>
 <class name="com/acme/shop/Big" sourcefilename="Big.java"><method name="run" desc="()V" line="5"/></class>
 <sourcefile name="Order.java"><line nr="9" mi="2" ci="0" mb="0" cb="0"/><line nr="10" mi="0" ci="1" mb="1" cb="1"/><line nr="11" mi="3" ci="0" mb="0" cb="0"/>
  <counter type="LINE" missed="2" covered="1"/><counter type="BRANCH" missed="1" covered="1"/><counter type="METHOD" missed="1" covered="1"/></sourcefile>
 <sourcefile name="Dto.java"><line nr="3" mi="2" ci="0" mb="0" cb="0"/><counter type="LINE" missed="5" covered="0"/><counter type="BRANCH" missed="0" covered="0"/><counter type="METHOD" missed="2" covered="0"/></sourcefile>
 <sourcefile name="Big.java"><line nr="5" mi="1" ci="0" mb="0" cb="0"/><line nr="6" mi="1" ci="0" mb="0" cb="0"/><line nr="7" mi="1" ci="0" mb="0" cb="0"/><line nr="9" mi="1" ci="0" mb="0" cb="0"/>
  <counter type="LINE" missed="20" covered="0"/><counter type="BRANCH" missed="6" covered="0"/><counter type="METHOD" missed="1" covered="0"/></sourcefile>
</package></report>
"""


def test_a_jacoco_report_is_read_per_source_file_with_its_uncovered_lines(tmp_path):
    xml = tmp_path / "jacoco.xml"
    xml.write_text(JACOCO)
    rows = {c.name: c for c in coverage.parse_jacoco_xml(xml)}
    assert set(rows) == {"com.acme.shop.Order", "com.acme.shop.Dto", "com.acme.shop.Big"}
    order = rows["com.acme.shop.Order"]
    assert (order.lines_missed, order.lines_covered, order.branches_missed) == (2, 1, 1)
    assert order.missed == [9, 11] and order.partial == [10] and not order.trivial
    assert rows["com.acme.shop.Dto"].trivial                       # getters and setters only
    report = coverage.Report(list(rows.values()))
    t = report.totals()
    assert (t.lines_missed, t.lines_covered, t.line_pct) == (27, 1, 3.6)
    assert report.totals(scope=["com.acme.shop"], exclude=["*Big"]).lines_missed == 7
    assert report.totals(scope=["com.other"]).classes == 0


def test_the_next_classes_are_the_ones_with_the_most_uncovered_code_and_accessor_classes_wait(tmp_path):
    xml = tmp_path / "jacoco.xml"
    xml.write_text(JACOCO)
    report = coverage.Report(coverage.parse_jacoco_xml(xml))
    assert [c.name for c in coverage.rank_gaps(report)] == ["com.acme.shop.Big"]          # Order misses only 2 lines
    assert [c.name for c in coverage.rank_gaps(report, min_lines=1)] == ["com.acme.shop.Big", "com.acme.shop.Order"]
    assert "com.acme.shop.Dto" in [c.name for c in coverage.rank_gaps(report, min_lines=1, include_trivial=True)]
    assert [c.name for c in coverage.rank_gaps(report, min_lines=1, skip={"com.acme.shop.Big"})] == ["com.acme.shop.Order"]
    ranked = coverage.rank_gaps(report, min_lines=1)
    assert [c.name for c in coverage.pick_batch(ranked, max_classes=1)] == ["com.acme.shop.Big"]
    assert [c.name for c in coverage.pick_batch(ranked, max_lines=21)] == ["com.acme.shop.Big"]
    assert coverage.ranges([3, 4, 5, 9, 11, 12]) == "3-5, 9, 11-12"


WEAK = textwrap.dedent("""
    package a;
    public class FooTest {
        @Test public void noAssertion() { new Foo().run(); }
        @Test public void onlyNotNull() { assertNotNull(new Foo().make()); }
        @Test public void theTrivialTrue() { assertTrue(true); }
        @Test public void verifies() { Foo f = mock(Foo.class); f.run(); verify(f).run(); }
        @Test public void asserts() { assertEquals(2, 1 + 1); }
        @Test(expected = IllegalStateException.class) public void expectsAnException() { new Foo().boom(); }
        @Test public void throwsChecked() throws Exception { assertThrows(IOException.class, () -> new Foo().io()); }
        // @Test public void commentedOut() { }
    }
""")


def test_tests_that_assert_nothing_are_found(tmp_path):
    f = tmp_path / "FooTest.java"
    f.write_text(WEAK)
    scan = coverage.scan_tests(f, "FooTest.java")
    assert scan.tests == 7 and not scan.disabled
    assert sorted(w.split(" — ")[0] for w in scan.weak) == ["noAssertion", "onlyNotNull", "theTrivialTrue"]
    f.write_text("@Ignore @Test public void a() { assertEquals(1, 1); }")
    assert coverage.scan_tests(f).disabled


def test_a_round_may_only_add_tests_and_everything_else_is_put_back(tmp_path):
    ws, base = tmp_path / "ws", tmp_path / "base"
    for root in (ws, base):
        (root / "src/main/java/a").mkdir(parents=True)
        (root / "src/test/java/a").mkdir(parents=True)
        (root / "src/main/java/a/Prod.java").write_text("class Prod {}")
        (root / "src/test/java/a/OldTest.java").write_text("class OldTest {}")
        (root / "pom.xml").write_text("<project/>")
    before = coverage.digests(ws)
    (ws / "src/test/java/a/NewTest.java").write_text("class NewTest {}")                  # allowed
    (ws / "src/main/java/a/Prod.java").write_text("class Prod { int hacked; }")           # production code changed
    (ws / "src/main/java/a/Extra.java").write_text("class Extra {}")                      # production code added
    (ws / "src/test/java/a/OldTest.java").write_text("class OldTest { /* edited */ }")    # an existing test edited
    (ws / "pom.xml").unlink()                                                             # a build file removed
    audit = coverage.audit_round(ws, base, before)
    assert audit["new_tests"] == ["src/test/java/a/NewTest.java"]
    assert sorted(audit["reverted"]) == ["pom.xml", "src/main/java/a/Extra.java", "src/main/java/a/Prod.java",
                                         "src/test/java/a/OldTest.java"]
    assert (ws / "src/main/java/a/Prod.java").read_text() == "class Prod {}"
    assert not (ws / "src/main/java/a/Extra.java").exists() and (ws / "pom.xml").is_file()
    assert (ws / "src/test/java/a/OldTest.java").read_text() == "class OldTest {}"
    assert (ws / "src/test/java/a/NewTest.java").is_file()


def test_the_repository_stack_is_read_from_its_poms_and_tests():
    stack = coverage.detect_stack(FIXTURE)
    assert stack.build_tool == "maven" and stack.java_release == 8
    assert stack.frameworks[:3] == ["JUnit 4", "Mockito", "Hamcrest"] or {"JUnit 4", "Mockito"} <= set(stack.frameworks)
    assert stack.versions["Mockito"] == "4.11.0" and stack.versions["JUnit"] == "4.13.2"
    assert stack.test_files == 3 and stack.test_methods == 25 and stack.jsp_files == 5
    assert stack.packages == ["com.acme"] or stack.packages == ["com.acme.inventory"]
    assert stack.sample.endswith("Test.java")


def test_the_jacoco_release_follows_the_jdk(monkeypatch):
    monkeypatch.setattr(config, "JACOCO_VERSION", "")
    assert [coverage.jacoco_version(m) for m in (8, 17, 23, 24, 25)] == ["0.8.12", "0.8.12", "0.8.12", "0.8.13", "0.8.14"]
    monkeypatch.setattr(config, "JACOCO_VERSION", "0.8.99")
    assert coverage.jacoco_version(8) == "0.8.99"


def test_the_writer_tools_write_only_new_tests(tmp_path):
    from agents.test_coverage import tools
    repo = tmp_path / "r"
    shutil.copytree(FIXTURE, repo)
    pipeline.start(repo, "test-coverage")
    run = Run.load(repo)
    run.state["plan_approved"] = True
    ctx = run.tool_context()
    new = "src/test/java/com/acme/inventory/service/NewTest.java"
    assert tools.write_file(ctx, new, "class NewTest {}").startswith("Wrote")
    assert tools.replace_in_file(ctx, new, "NewTest", "NewerTest").startswith("Replaced")           # created in this run
    assert tools.delete_file(ctx, new).startswith("Deleted")
    for path in ("src/main/java/com/acme/inventory/service/PricingService.java", "pom.xml",
                 "src/main/webapp/WEB-INF/web.xml", ".modernizer/run.json", "../outside/FooTest.java"):
        assert tools.write_file(ctx, path, "x").startswith("ERROR"), path
    frozen = "src/test/java/com/acme/inventory/util/InputValidatorTest.java"
    for result in (tools.write_file(ctx, frozen, "x"), tools.replace_in_file(ctx, frozen, "class", "klass"),
                   tools.delete_file(ctx, frozen)):
        assert result.startswith("ERROR") and "frozen" in result
    assert (repo / frozen).read_text().startswith("package")


def test_gates_take_only_what_they_understand(tmp_path):
    repo = tmp_path / "r"
    shutil.copytree(FIXTURE, repo)
    pipeline.start(repo, "test-coverage")
    run = Run.load(repo)
    with pytest.raises(RunError):
        pipeline.confirm(run, "coverage", ["line=85"])                    # nothing is waiting yet (baseline not made)
    run.state["cov"]["phase"] = "target"
    with pytest.raises(RunError, match="not understood"):
        pipeline.confirm(run, "coverage", ["target=high"])
    with pytest.raises(RunError, match="percentage"):
        pipeline.confirm(run, "coverage", ["line=150"])
    with pytest.raises(RunError):
        pipeline.confirm(run, "plan", [])
    msg = pipeline.confirm(run, "coverage", ["line=85", "branch=60", "rounds=3", "scope=com.acme.inventory.service",
                                             "exclude=*Dto"])
    cov = run.state["cov"]
    assert "line target 85%" in msg and cov["target"] == {"line": 85, "branch": 60} and cov["max_rounds"] == 3
    assert cov["scope"] == ["com.acme.inventory.service"] and cov["exclude"] == ["*Dto"] and cov["phase"] == "uplift"
    assert run.state["plan_approved"] is True


def test_gradle_and_test_free_repositories_are_stopped_with_what_to_do(tmp_path):
    gradle = tmp_path / "g"
    gradle.mkdir()
    (gradle / "build.gradle").write_text("apply plugin: 'java'")
    pipeline.start(gradle, "test-coverage")
    step, _ = pipeline.next_step(Run.load(gradle))
    assert step["id"] == "coverage-unsupported" and step["kind"] == "blocked" and "Gradle" in step["text"]
    bare = tmp_path / "b"
    (bare / "src/main/java").mkdir(parents=True)
    (bare / "pom.xml").write_text("<project><modelVersion>4.0.0</modelVersion></project>")
    pipeline.start(bare, "test-coverage")
    step, _ = pipeline.next_step(Run.load(bare))
    assert step["id"] == "coverage-no-framework" and "never edits a pom" in step["text"]


# ── a whole run on the JSP + servlet repository, real Maven and JaCoCo ────────────────────────────────────

SERVICE_TEST = '''package com.acme.inventory.service;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.acme.inventory.dao.ProductDao;
import com.acme.inventory.model.Order;
import com.acme.inventory.model.OrderLine;
import com.acme.inventory.model.OrderStatus;
import com.acme.inventory.model.Product;
import java.math.BigDecimal;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;

@RunWith(MockitoJUnitRunner.class)
public class InventoryServiceTest {
    @Mock private ProductDao dao;
    private InventoryService service;

    @Before
    public void setUp() {
        service = new InventoryService(dao);
    }

    private Product product(long id, int stock) {
        return new Product(id, "SKU-" + id, "Item " + id, BigDecimal.TEN, stock);
    }

    @Test
    public void reserve_enoughStock_decrementsStock() throws Exception {
        when(dao.findById(1L)).thenReturn(product(1, 10));
        service.reserve(1L, 4);
        verify(dao).updateStock(1L, 6);
    }

    @Test
    public void reserve_zeroQuantity_isRejectedBeforeTheDaoIsAsked() throws Exception {
        try {
            service.reserve(1L, 0);
            fail("expected IllegalArgumentException");
        } catch (IllegalArgumentException expected) {
            assertEquals("qty must be positive", expected.getMessage());
        }
        verify(dao, never()).findById(anyLong());
    }

    @Test(expected = IllegalArgumentException.class)
    public void reserve_unknownProduct_isRejected() throws Exception {
        when(dao.findById(9L)).thenReturn(null);
        service.reserve(9L, 1);
    }

    @Test
    public void reserve_notEnoughStock_reportsWhatIsAvailableAndChangesNothing() {
        when(dao.findById(2L)).thenReturn(product(2, 3));
        try {
            service.reserve(2L, 5);
            fail("expected InsufficientStockException");
        } catch (InsufficientStockException e) {
            assertEquals(3, e.getAvailable());
            assertEquals(2L, e.getProductId());
        }
        verify(dao, never()).updateStock(anyLong(), anyInt());
    }

    @Test
    public void release_addsTheQuantityBack() {
        when(dao.findById(3L)).thenReturn(product(3, 7));
        service.release(3L, 2);
        verify(dao).updateStock(3L, 9);
    }

    @Test(expected = IllegalArgumentException.class)
    public void release_negativeQuantity_isRejected() {
        service.release(3L, -1);
    }

    @Test(expected = IllegalArgumentException.class)
    public void release_unknownProduct_isRejected() {
        service.release(4L, 1);
    }

    @Test
    public void reserveOrder_everyLineAvailable_marksTheOrderReserved() throws Exception {
        when(dao.findById(1L)).thenReturn(product(1, 10));
        Order order = new Order();
        order.addLine(new OrderLine(1L, 2, BigDecimal.TEN));
        service.reserveOrder(order);
        assertEquals(OrderStatus.RESERVED, order.getStatus());
    }

    @Test
    public void reserveOrder_secondLineFails_releasesTheFirstAndLeavesTheOrderNew() throws Exception {
        when(dao.findById(1L)).thenReturn(product(1, 10));
        when(dao.findById(2L)).thenReturn(product(2, 5));
        Order order = new Order();
        order.addLine(new OrderLine(1L, 2, BigDecimal.TEN));
        order.addLine(new OrderLine(2L, 50, BigDecimal.ONE));
        try {
            service.reserveOrder(order);
            fail("expected InsufficientStockException");
        } catch (InsufficientStockException e) {
            assertEquals(2L, e.getProductId());
        }
        verify(dao).updateStock(1L, 12);
        assertEquals(OrderStatus.NEW, order.getStatus());
    }

    @Test
    public void isLowStock_atOrBelowTheThreshold_isTrue() {
        when(dao.findById(5L)).thenReturn(product(5, 4));
        assertTrue(service.isLowStock(5L, 4));
        assertFalse(service.isLowStock(5L, 3));
    }

    @Test
    public void isLowStock_unknownProduct_isFalse() {
        assertFalse(service.isLowStock(6L, 100));
    }
}
'''

SERVLET_TEST = '''package com.acme.inventory.web;

import static org.junit.Assert.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.acme.inventory.dao.DaoException;
import com.acme.inventory.dao.ProductDao;
import com.acme.inventory.model.Order;
import com.acme.inventory.model.Product;
import com.acme.inventory.service.InsufficientStockException;
import com.acme.inventory.service.InventoryService;
import com.acme.inventory.service.PricingService;
import java.math.BigDecimal;
import javax.servlet.RequestDispatcher;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import javax.servlet.http.HttpSession;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;

@RunWith(MockitoJUnitRunner.class)
public class OrderServletTest {
    @Mock private HttpServletRequest request;
    @Mock private HttpServletResponse response;
    @Mock private RequestDispatcher dispatcher;
    @Mock private HttpSession session;
    @Mock private InventoryService inventory;
    @Mock private ProductDao dao;

    private OrderServlet servlet;

    @Before
    public void setUp() {
        servlet = new OrderServlet(inventory, new PricingService(), dao);
    }

    private void validForm() {
        when(request.getParameter("customer")).thenReturn(" Ada ");
        when(request.getParameter("region")).thenReturn("EU");
        when(request.getParameter("productId")).thenReturn("1");
        when(request.getParameter("quantity")).thenReturn("2");
    }

    @Test
    public void doPost_blankCustomer_isRejectedWith400() throws Exception {
        when(request.getRequestDispatcher("/order.jsp")).thenReturn(dispatcher);
        servlet.doPost(request, response);
        verify(request).setAttribute("error", "Customer and region are required");
        verify(response).setStatus(HttpServletResponse.SC_BAD_REQUEST);
        verify(dispatcher).forward(request, response);
    }

    @Test
    public void doPost_quantityNotANumber_isRejectedWith400() throws Exception {
        when(request.getParameter("customer")).thenReturn("Ada");
        when(request.getParameter("region")).thenReturn("EU");
        when(request.getParameter("quantity")).thenReturn("many");
        when(request.getRequestDispatcher("/order.jsp")).thenReturn(dispatcher);
        servlet.doPost(request, response);
        verify(request).setAttribute("error", "Quantity must be a positive number");
        verify(inventory, never()).reserveOrder(any(Order.class));
    }

    @Test
    public void doPost_productIdNotANumber_isRejected() throws Exception {
        when(request.getParameter("customer")).thenReturn("Ada");
        when(request.getParameter("region")).thenReturn("EU");
        when(request.getParameter("quantity")).thenReturn("1");
        when(request.getParameter("productId")).thenReturn("abc");
        when(request.getRequestDispatcher("/order.jsp")).thenReturn(dispatcher);
        servlet.doPost(request, response);
        verify(request).setAttribute("error", "Invalid product");
    }

    @Test
    public void doPost_unknownProduct_isRejected() throws Exception {
        validForm();
        when(dao.findById(1L)).thenReturn(null);
        when(request.getRequestDispatcher("/order.jsp")).thenReturn(dispatcher);
        servlet.doPost(request, response);
        verify(request).setAttribute("error", "Product not found");
    }

    @Test
    public void doPost_validOrder_storesTheTotalAndRedirects() throws Exception {
        validForm();
        when(dao.findById(1L)).thenReturn(new Product(1L, "SKU-1", "Item", BigDecimal.TEN, 9));
        when(request.getSession()).thenReturn(session);
        when(request.getContextPath()).thenReturn("/shop");
        servlet.doPost(request, response);
        verify(inventory).reserveOrder(any(Order.class));
        verify(session).setAttribute(eq("lastOrderTotal"), any(BigDecimal.class));
        verify(response).sendRedirect("/shop/order.jsp?ok=1");
    }

    @Test
    public void doPost_notEnoughStock_tellsTheUserHowMuchIsLeft() throws Exception {
        validForm();
        when(dao.findById(1L)).thenReturn(new Product(1L, "SKU-1", "Item", BigDecimal.TEN, 1));
        doThrow(new InsufficientStockException(1L, 1, 2)).when(inventory).reserveOrder(any(Order.class));
        when(request.getRequestDispatcher("/order.jsp")).thenReturn(dispatcher);
        servlet.doPost(request, response);
        verify(request).setAttribute("error", "Only 1 left in stock");
        verify(response).setStatus(400);
    }

    @Test
    public void doPost_databaseFailure_answers500AndForwardsToTheErrorPage() throws Exception {
        validForm();
        when(dao.findById(1L)).thenThrow(new DaoException("db down", new RuntimeException()));
        when(request.getRequestDispatcher("/error.jsp")).thenReturn(dispatcher);
        servlet.doPost(request, response);
        verify(response).setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
        verify(dispatcher).forward(request, response);
        assertEquals(HttpServletResponse.SC_INTERNAL_SERVER_ERROR, 500);
    }
}
'''

WEAK_LOGIN = '''package com.acme.inventory.web;

import static org.mockito.Mockito.when;

import javax.servlet.RequestDispatcher;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;

@RunWith(MockitoJUnitRunner.class)
public class LoginServletWeakTest {
    @Mock private HttpServletRequest request;
    @Mock private HttpServletResponse response;
    @Mock private RequestDispatcher dispatcher;

    @Test
    public void doPost_blankCredentials_runs() throws Exception {
        when(request.getRequestDispatcher("/login.jsp")).thenReturn(dispatcher);
        new LoginServlet().doPost(request, response);
    }
}
'''

BROKEN_DAO = '''package com.acme.inventory.dao;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class DaoBrokenTest {
    @Test
    public void arithmetic_isWrong() {
        assertEquals(5, 2 + 2);
    }
}
'''

_PROD = "src/main/java/com/acme/inventory/service/PricingService.java"


def _tool(fn, **kwargs) -> str:
    return anyio.run(lambda: fn(**kwargs))


def _next(repo: Path) -> dict:
    step, _ = pipeline.next_step(Run.load(repo))
    return step


def _save(repo: Path, step_id: str, text: str) -> None:
    assert _tool(mcp_server.save_output, step_id=step_id, content=text, workspace=str(repo)).startswith("Saved")
    pipeline.complete_step(Run.load(repo), step_id)


def _write(repo: Path, path: str, content: str) -> str:
    return _tool(mcp_server.ws_write_file, path=path, content=content, workspace=str(repo))


@pytest.fixture(scope="module")
def maven_works():
    import shutil as _sh
    if not _sh.which("mvn"):
        pytest.skip("Maven is not installed")


@pytest.mark.slow
def test_a_whole_coverage_run_on_a_jsp_servlet_repository(tmp_path, monkeypatch, maven_works):
    repo = tmp_path / "inventory"
    shutil.copytree(FIXTURE, repo)
    pipeline.start(repo, "test-coverage", requirements="Focus on the order and stock logic.")

    # 1. The baseline: the repository's own 25 tests, run under JaCoCo.
    gate = _next(repo)
    if gate["kind"] == "blocked":
        pytest.skip(f"the baseline could not be measured here: {gate['text'][:300]}")
    assert gate["id"] == "coverage-target" and gate["kind"] == "ask_user"
    assert "25 existing tests" in gate["text"] and "JUnit 4" in gate["text"] and "JSP file(s)" in gate["text"]
    run = Run.load(repo)
    baseline = run.state["cov"]["baseline"]
    assert 20 < baseline["line"] < 35 and baseline["tests"] == 25
    assert _tool(mcp_server.ws_write_file, path="src/test/java/x/NewTest.java", content="x", workspace=str(repo)) \
        .startswith("ERROR")                                     # nothing may be written before the gate
    pipeline.confirm(Run.load(repo), "coverage", ["line=90", "rounds=1"])

    # 2. Round 1: the tester writes tests — some good, some not, one rogue edit of production code.
    step = _next(repo)
    assert step["id"] == "tests-round-1" and step["subagent"] == "modernizer-tester"
    q = step["query"]
    assert "com.acme.inventory.web.OrderServlet" in q and "Uncovered lines:" in q and "Focus on the order and stock logic" in q
    assert "ProductListServletTest.java" in q or "Style sample" in q
    for path, why in ((_PROD, "production"), ("pom.xml", "build file"),
                      ("src/test/java/com/acme/inventory/util/InputValidatorTest.java", "existing test")):
        assert _write(repo, path, "x").startswith("ERROR"), why
    assert _write(repo, "src/test/java/com/acme/inventory/service/InventoryServiceTest.java", SERVICE_TEST).startswith("Wrote")
    check = _tool(mcp_server.ws_run_command, command="mvn -q -B test -Dtest=InventoryServiceTest", workspace=str(repo))
    assert check.startswith("exit_code=0") and "Build summary: maven build PASSED" in check
    assert _tool(mcp_server.ws_run_command, command="javac Foo.java", workspace=str(repo)).startswith("ERROR")   # builds only
    assert _write(repo, "src/test/java/com/acme/inventory/web/OrderServletTest.java", SERVLET_TEST).startswith("Wrote")
    assert _write(repo, "src/test/java/com/acme/inventory/web/LoginServletWeakTest.java", WEAK_LOGIN).startswith("Wrote")
    assert _write(repo, "src/test/java/com/acme/inventory/dao/DaoBrokenTest.java", BROKEN_DAO).startswith("Wrote")
    original = (repo / _PROD).read_text()
    (repo / _PROD).write_text(original + "\n// a writer went around the tools\n")        # a rogue edit
    (repo / "src/main/java/com/acme/inventory/Rogue.java").write_text("package com.acme.inventory; class Rogue {}")
    _save(repo, "tests-round-1", "## Tests written\n- InventoryServiceTest, OrderServletTest\n\n## UNTESTABLE:\n"
                                 "UNTESTABLE: com.acme.inventory.util.CsvExporter — writes to a fixed path\n")
    assert Run.load(repo).state["cov"]["untestable"] == {"com.acme.inventory.util.CsvExporter": "writes to a fixed path"}

    # 3. The pipeline's own check: the rogue edits are put back, the weak and failing tests go to the fixer.
    fix = _next(repo)
    assert fix["id"] == "fix-tests-1-1" and fix["subagent"] == "modernizer-tester"
    assert (repo / _PROD).read_text() == original and not (repo / "src/main/java/com/acme/inventory/Rogue.java").exists()
    assert "LoginServletWeakTest" in fix["query"] and "no assertion" in fix["query"]
    assert "DaoBrokenTest" in fix["query"] and "arithmetic_isWrong" in fix["query"]
    assert "InventoryServiceTest" not in fix["query"].split("## What the pipeline found")[1].split("## This round")[0]
    weak = "src/test/java/com/acme/inventory/web/LoginServletWeakTest.java"
    assert _tool(mcp_server.ws_replace_in_file, path=weak, workspace=str(repo),
                 old_text="new LoginServlet().doPost(request, response);\n    }",
                 new_text="new LoginServlet().doPost(request, response);\n        verify(dispatcher).forward(request, response);\n    }"
                 ).startswith("Replaced")
    assert _tool(mcp_server.ws_replace_in_file, path=weak, workspace=str(repo), old_text="import static org.mockito.Mockito.when;",
                 new_text="import static org.mockito.Mockito.verify;\nimport static org.mockito.Mockito.when;").startswith("Replaced")
    _save(repo, "fix-tests-1-1", "## Fixed\n- LoginServletWeakTest now verifies the forward.\n")   # the broken test is left

    # 4. The broken test survives a second repair pass, so the pipeline deletes it itself.
    again = _next(repo)
    assert again["id"] == "fix-tests-1-2" and "DaoBrokenTest" in again["query"] and "LoginServletWeakTest" not in \
        again["query"].split("## What the pipeline found")[1].split("## This round")[0]
    _save(repo, "fix-tests-1-2", "## Fixed\nNothing — I could not see the problem.\n")
    gate = _next(repo)
    cov = Run.load(repo).state["cov"]
    assert not (repo / "src/test/java/com/acme/inventory/dao/DaoBrokenTest.java").exists()
    assert [d["file"].split("/")[-1] for d in cov["dropped"]] == ["DaoBrokenTest.java"]
    assert (repo / weak).is_file()                                    # the strengthened test stayed

    # 5. Round 1 raised coverage; the one round allowed is used, so the run asks.
    row = cov["history"][0]
    assert row["gain"] > 15 and row["line"] > baseline["line"] + 15 and row["tests"] >= 17
    assert gate["id"] == "coverage-stalled" and gate["kind"] == "ask_user" and "all 1 rounds were used" in gate["text"]
    assert "CsvExporter" in gate["text"]
    with pytest.raises(RunError):
        pipeline.confirm(Run.load(repo), "coverage", [])               # a choice is needed
    pipeline.confirm(Run.load(repo), "coverage", [f"line={int(row['line'])}"])         # a target already met
    done = _next(repo)
    assert done["kind"] == "done" and "no production code was changed" in done["text"]

    # 6. The report and the delivered change: tests only.
    report = (repo / ".modernizer/results/test-coverage/coverage_report.md").read_text()
    assert "## Coverage by package" in report and "DaoBrokenTest.java" in report and "CsvExporter" in report
    assert "InventoryServiceTest.java" in report and "the target was reached" in report
    changes = (repo / ".modernizer/results/changes.md").read_text()
    changed = [l for l in changes.splitlines() if l.startswith("| ") and "`" in l]
    assert changed and all("src/test/java/" in l for l in changed), changed
    assert (repo / _PROD).read_text() == original
    assert Run.load(repo).state["phase"] == "done"


def test_the_agent_and_its_data_file_live_in_a_short_folder_without_spaces():
    folder = coverage._short_dir()
    assert " " not in str(folder) and len(str(folder)) < 30 and folder.is_dir()


def test_a_measurement_where_the_agent_never_wrote_is_not_a_zero_percent_baseline(tmp_path, monkeypatch):
    """A JDK 8 ignores an agent whose JAVA_TOOL_OPTIONS is too long: the tests pass, nothing is recorded. That must
    stop the run with the reason, never report 0%."""
    root = tmp_path / "r"
    (root / "target/surefire-reports").mkdir(parents=True)
    (root / "pom.xml").write_text("<project/>")
    jar = tmp_path / "agent.jar"
    jar.write_bytes(b"x")
    monkeypatch.setattr(coverage, "_agent_jar", lambda *a, **k: jar)

    def fake_maven(cwd, args, java_home=None, timeout=None, env_extra=None):
        (cwd / "target/surefire-reports").mkdir(parents=True, exist_ok=True)
        (cwd / "target/surefire-reports/TEST-a.FooTest.xml").write_text('<testsuite name="a.FooTest" tests="3" skipped="0"/>')
        return 0, "[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0\n[INFO] BUILD SUCCESS\n"
    monkeypatch.setattr(coverage.java_env, "run_maven", fake_maven)
    m = coverage.measure(root, None, packages=["a"])
    assert not m.ok and "3 test(s) ran but JaCoCo recorded nothing" in m.problem and "JAVA_TOOL_OPTIONS" in m.problem
