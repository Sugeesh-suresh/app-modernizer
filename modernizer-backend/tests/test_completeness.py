"""The technical documents list everything — no sampling, no "…and N more":
computed sections are uncapped, every test file is listed, and an agent's
abbreviated list is replaced with a pointer to the complete computed list."""
import pytest

from agents.shared import config_matrix, dependency_graph, existing_tests, grounding, repo_fingerprint


# ── abbreviations an agent may write ────────────────────────────────────────

@pytest.mark.parametrize("text, cut", [
    ("| Pages | /a, /b, [...27 more web pages] |", "[...27 more web pages]"),
    ("- [...84 more REST end points]", "[...84 more REST end points]"),
    ("…and 12 more endpoints", "…and 12 more endpoints"),
    ("There are 40 more REST endpoints in the catalog.", "40 more REST endpoints in the catalog"),
    ("Covers /a, /b and 27 more web pages.", "and 27 more web pages"),
    ("Handles orders, payments, etc.", "etc."),
    ("(+5 more)", "(+5 more)"),
    ("- ...", "- ..."),
    ("| … | … |", "| … | … |"),
    ("The remaining ones are omitted for brevity.", "The remaining ones are omitted for brevity"),
])
def test_abbreviations_are_replaced(text, cut):
    out, found = grounding.replace_elisions(text, "‹ALL›")
    assert found == [cut] and "‹ALL›" in out


@pytest.mark.parametrize("text", [
    "Retries 3 times with 2 seconds between attempts.",
    "It loads 10 more rows when scrolling.",
    "Shows 5 more items per click.",
    "No more than 50 items per order.",
    "Pages 1-3 show more detail.",
    "The import... continues",
])
def test_behaviour_is_not_mistaken_for_an_abbreviation(text):
    assert grounding.replace_elisions(text, "‹ALL›") == (text, [])


def test_the_audit_file_lists_replaced_abbreviations():
    md = grounding.report_markdown([], None, [], None, ["[...27 more web pages]"])
    assert "Abbreviated lists replaced in the technical documents:** 1" in md
    assert "“[...27 more web pages]”" in md


# ── computed sections are complete ──────────────────────────────────────────

def test_dependency_graph_lists_every_item_for_discovery():
    nodes = [f"m{i}" for i in range(60)]
    graph = {"nodes": nodes, "edges": [("m0", n) for n in nodes[1:]], "groups": [nodes[1:], ["m0"]]}
    section = dependency_graph.to_markdown_section(graph, "java", discovery=True)
    assert "more" not in section and all(f"→ m{i} " in section for i in range(1, 60))


def test_config_matrix_lists_every_key_when_uncapped():
    matrices = [{"folder": "res", "profiles": ["default", "prod"],
                 "values": {f"k{i}": {"default": (str(i), ""), "prod": (str(i + 1), "")} for i in range(300)}}]
    md = config_matrix.to_markdown(matrices, None)
    assert "more differing keys" not in md and "`k299`" in md


def test_fingerprint_lists_every_dependency_and_import_when_uncapped():
    fp = {"manifests": [{"path": "pom.xml", "kind": "maven", "properties": {},
                         "dependencies": [{"name": f"g:a{i}", "version": "1", "scope": ""} for i in range(90)]}],
          "imports": {"java": {f"org.lib{i}": {"files": 1, "samples": ["A.java"]} for i in range(70)}}}
    md = repo_fingerprint.to_markdown(fp, None, None)
    assert "more |" not in md and "`g:a89`" in md and "`org.lib69`" in md


# ── every test file ─────────────────────────────────────────────────────────

TESTS = {
    "src/test/java/a/JobApiTest.java": """import org.junit.jupiter.api.Test;
@WebMvcTest
class JobApiTest {
  @MockBean JobService s;
  @Test void listsJobs() {}
  @ParameterizedTest @ValueSource(ints = {1, 2}) public void rejectsBad(int x) {}
  @Test
  public void createsJob() throws Exception {}
  private void helper() {}
}""",
    "src/test/java/a/Fixtures.java": "class Fixtures { static Object one() { return null; } }",
    "src/test/java/a/OldTest.java": "import junit.framework.TestCase;\n"
                                    "public class OldTest extends TestCase { public void testA() {} public void testB() {} }",
    "src/test/java/a/RepoIT.java": "import org.junit.jupiter.api.Test;\n@SpringBootTest @Testcontainers\n"
                                   "class RepoIT { @Test void saves() {} }",
    "web/src/app.test.ts": "import { describe, it } from 'vitest';\ndescribe('cart', () => {\n"
                           "  it('adds an item', () => {});\n  describe('empty', () => { test(\"shows a message\", () => {}); });\n"
                           "});\nit('top level', () => {});",
    "tests/test_api.py": "import pytest\ndef test_one():\n    pass\nclass TestX:\n    def test_two(self):\n        pass\n",
    "node_modules/lib/x.test.js": "it('never read', () => {});",
}


@pytest.fixture
def tests_repo(tmp_path):
    for rel, text in TESTS.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def test_every_test_file_and_test_is_found(tests_repo):
    found = {f["file"]: f for f in existing_tests.scan(str(tests_repo))}
    assert set(found) == {"src/test/java/a/JobApiTest.java", "src/test/java/a/OldTest.java",
                          "src/test/java/a/RepoIT.java", "web/src/app.test.ts", "tests/test_api.py"}
    api = found["src/test/java/a/JobApiTest.java"]
    assert api["framework"] == "JUnit 5" and api["tests"] == ["listsJobs", "rejectsBad", "createsJob"]
    assert api["needs"] == ["Spring MVC slice (MockMvc)", "Mockito mocks"]
    assert found["src/test/java/a/OldTest.java"]["tests"] == ["testA", "testB"]
    assert found["src/test/java/a/RepoIT.java"]["needs"] == ["Spring Boot application context",
                                                             "Docker (Testcontainers)"]
    assert found["web/src/app.test.ts"]["tests"] == ["cart › adds an item", "cart › empty › shows a message",
                                                     "top level"]
    assert found["tests/test_api.py"]["tests"] == ["test_one", "TestX.test_two"]


def test_test_files_markdown(tests_repo):
    md = existing_tests.to_markdown(existing_tests.scan(str(tests_repo)))
    assert md.startswith(existing_tests.HEADING) and "**5 test file(s), 11 test(s).**" in md
    assert "| `src/test/java/a/JobApiTest.java` | JUnit 5 |" in md and "listsJobs; rejectsBad; createsJob" in md
    assert "No test files were found" in existing_tests.to_markdown([])
