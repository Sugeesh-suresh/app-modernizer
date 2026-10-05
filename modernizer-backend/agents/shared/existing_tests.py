"""
Every test in the repository, read from the files — no model involved.

For each test file: the framework (from its imports), what it needs to run
(from its annotations and imports: a Spring context, a web-layer slice, a
database slice, Testcontainers/Docker, an embedded server, a browser) and every
test it declares, by name:

- Java / Kotlin / Groovy: methods annotated `@Test`, `@ParameterizedTest`,
  `@RepeatedTest`, `@TestFactory`, `@TestTemplate`; JUnit 3 `public void test…()`
  in a `TestCase`; Spock `def "name"()` feature methods.
- JavaScript / TypeScript: `it(…)`, `test(…)`, `it.each`/`test.each`, inside
  `describe(…)` blocks (named "describe › test").
- Python: `def test_…` functions and methods.

The table goes into the Existing Test Inventory as it is, so the inventory is
complete by construction rather than by how much an agent wrote.
"""
import re
from pathlib import Path

from .dependency_graph import EXCLUDED_DIRS

HEADING = "## Test Files (computed)"
MAX_FILE_BYTES = 2_000_000

_JVM_TEST_FILE = re.compile(r"(?:^|/)src/(?:test|it|integration-?test)\w*/|(?:Test|Tests|IT|ITCase|Spec|TestCase)"
                            r"\.(?:java|kt|groovy)$")
_JS_TEST_FILE = re.compile(r"\.(?:test|spec|e2e|cy)\.[cm]?[jt]sx?$|(?:^|/)__tests__/[^/]+\.[cm]?[jt]sx?$")
_PY_TEST_FILE = re.compile(r"(?:^|/)test_[^/]+\.py$|_test\.py$")

_JVM_ANNOTATIONS = ("Test", "ParameterizedTest", "RepeatedTest", "TestFactory", "TestTemplate")
_NEEDS = [
    (r"@SpringBootTest\b", "Spring Boot application context"),
    (r"@WebMvcTest\b", "Spring MVC slice (MockMvc)"),
    (r"@WebFluxTest\b", "Spring WebFlux slice"),
    (r"@DataJpaTest\b", "JPA slice with an embedded database"),
    (r"@JdbcTest\b|@DataJdbcTest\b", "JDBC slice with an embedded database"),
    (r"@DataMongoTest\b", "MongoDB slice"),
    (r"@RestClientTest\b", "REST client slice"),
    (r"@JsonTest\b", "JSON slice"),
    (r"@Testcontainers\b|org\.testcontainers", "Docker (Testcontainers)"),
    (r"@AutoConfigureMockMvc\b|MockMvc\b", "MockMvc"),
    (r"webEnvironment\s*=\s*\w*\.?(?:RANDOM_PORT|DEFINED_PORT)", "an embedded web server"),
    (r"@MockBean\b|@MockitoBean\b|@Mock\b|Mockito\.", "Mockito mocks"),
    (r"WireMock|MockWebServer", "an HTTP mock server"),
    (r"@EmbeddedKafka\b", "an embedded Kafka broker"),
    (r"Arquillian", "Arquillian container"),
    (r"Selenium|WebDriver|playwright|puppeteer|cy\.visit", "a browser"),
    (r"@pytest\.mark\.django_db|TestCase\)\s*:|django\.test", "a Django test database"),
    (r"supertest|request\(app\)", "the app's HTTP server in-process"),
]
_FRAMEWORKS = [
    (r"org\.junit\.jupiter", "JUnit 5"),
    (r"org\.junit\.Test\b|org\.junit\.\*|org\.junit\.runner", "JUnit 4"),
    (r"junit\.framework\.TestCase", "JUnit 3"),
    (r"org\.testng", "TestNG"),
    (r"spock\.lang|extends\s+Specification\b", "Spock"),
    (r"io\.kotest", "Kotest"),
    (r"from\s+['\"]vitest['\"]", "Vitest"),
    (r"@playwright/test", "Playwright"),
    (r"cy\.\w+\(", "Cypress"),
    (r"from\s+['\"]@angular/core/testing['\"]|TestBed\b", "Angular TestBed (Jasmine/Karma)"),
    (r"require\(['\"]mocha['\"]\)|from\s+['\"]mocha['\"]|require\(['\"]chai['\"]\)|from\s+['\"]chai['\"]", "Mocha/Chai"),
    (r"@testing-library/react", "React Testing Library"),
    (r"\bjest\.\w+\(|from\s+['\"]@jest/globals['\"]", "Jest"),
    (r"^\s*import\s+pytest|^\s*from\s+pytest", "pytest"),
    (r"^\s*import\s+unittest|^\s*from\s+unittest", "unittest"),
]


def _files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if EXCLUDED_DIRS & set(Path(rel).parts) or "/node_modules/" in "/" + rel:
            continue
        suffix = path.suffix.lower()
        kind = None
        if suffix in (".java", ".kt", ".groovy") and _JVM_TEST_FILE.search(rel):
            kind = "jvm"
        elif suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs") and _JS_TEST_FILE.search(rel):
            kind = "js"
        elif suffix == ".py" and _PY_TEST_FILE.search(rel):
            kind = "py"
        if kind:
            yield path, rel, kind


def _jvm_tests(text: str) -> list[str]:
    names = []
    ann = "|".join(_JVM_ANNOTATIONS)
    for m in re.finditer(rf"@(?:{ann})\b(?:\s*\([^)]*\))?(?:\s*@\w+(?:\s*\([^)]*\))?)*\s*"
                         rf"(?:(?:public|protected|private|static|final|suspend|open|override)\s+)*"
                         rf"(?:fun\s+|void\s+|def\s+|[\w<>\[\],.? ]+\s+)?`?([\w ]+?)`?\s*\(", text):
        names.append(m.group(1).strip())
    if "TestCase" in text:
        names += [n for n in re.findall(r"public\s+void\s+(test\w*)\s*\(", text) if n not in names]
    names += [n for n in re.findall(r"^\s*def\s+[\"']([^\"']+)[\"']\s*\(", text, re.M) if n not in names]   # Spock
    return names


_JS_CALL = re.compile(r"\b(describe|context|suite|it|test|specify)(?:\.(?:each|only|skip|concurrent)\s*"
                      r"(?:\([^)]*\)|`[^`]*`)?)?\s*\(\s*(['\"`])((?:\\.|(?!\2).)*)\2", re.S)


def _js_tests(text: str) -> list[str]:
    """Test names, prefixed with their describe blocks (by brace depth)."""
    names, stack = [], []          # stack: (describe name, depth at which it opened)
    depth = 0
    pos = 0
    for m in _JS_CALL.finditer(text):
        segment = text[pos:m.start()]
        for ch in segment:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                while stack and depth < stack[-1][1]:
                    stack.pop()
        pos = m.start()
        kind, name = m.group(1), m.group(3)
        if kind in ("describe", "context", "suite"):
            stack.append((name, depth + 1))
        else:
            names.append(" › ".join([s for s, _ in stack] + [name]))
    return names


def _py_tests(text: str) -> list[str]:
    out, cls = [], ""
    for line in text.splitlines():
        c = re.match(r"^class\s+(\w+)", line)
        if c:
            cls = c.group(1)
            continue
        f = re.match(r"^(\s*)(?:async\s+)?def\s+(test\w*)\s*\(", line)
        if f:
            out.append(f"{cls}.{f.group(2)}" if f.group(1) and cls else f.group(2))
        elif re.match(r"^\S", line):
            cls = "" if not line.startswith(("class", "@", "#")) else cls
    return out


def scan(workspace_dir: str) -> list[dict]:
    """[{"file", "framework", "needs", "tests"}], one per test file, in path order."""
    root = Path(workspace_dir)
    out = []
    if not root.is_dir():
        return out
    for path, rel, kind in _files(root):
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tests = _jvm_tests(text) if kind == "jvm" else _js_tests(text) if kind == "js" else _py_tests(text)
        frameworks = [name for pattern, name in _FRAMEWORKS if re.search(pattern, text, re.M)]
        if kind == "js" and not frameworks and tests:
            frameworks = ["Jest/Mocha-style (no framework import)"]
        if kind == "py" and not frameworks and tests:
            frameworks = ["pytest (by convention)"]
        needs = list(dict.fromkeys(label for pattern, label in _NEEDS if re.search(pattern, text)))
        if not tests and kind == "jvm" and not re.search(r"@(?:" + "|".join(_JVM_ANNOTATIONS) + r")\b", text):
            continue                                        # a helper or fixture class in the test tree
        out.append({"file": rel, "framework": ", ".join(frameworks) or "not identified", "needs": needs,
                    "tests": tests})
    return out


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def to_markdown(files: list[dict]) -> str:
    if not files:
        return f"{HEADING}\n\nNo test files were found in the repository."
    total = sum(len(f["tests"]) for f in files)
    lines = [HEADING, "",
             "_Read from the test files by the pipeline — not generated by an agent. Every test file and every test "
             "it declares is listed._", "",
             f"**{len(files)} test file(s), {total} test(s).**", "",
             "| Test file | Framework | Needs to run | Tests | Test names |", "|---|---|---|---|---|"]
    for f in files:
        lines.append(f"| `{_cell(f['file'])}` | {_cell(f['framework'])} | {_cell(', '.join(f['needs'])) or '—'} | "
                     f"{len(f['tests'])} | {_cell('; '.join(f['tests'])) or '—'} |")
    return "\n".join(lines)
