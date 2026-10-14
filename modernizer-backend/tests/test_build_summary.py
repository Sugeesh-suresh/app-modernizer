"""The short verdict shown after a build (agents/shared/build_summary.py)."""
from agents.shared import build_summary as bs

FAIL = """[INFO] Reactor Summary for parent 1.0:
[INFO]
[INFO] parent ............................................. SUCCESS [  0.3 s]
[INFO] common ............................................. SUCCESS [  4.1 s]
[INFO] web ................................................ FAILURE [  2.0 s]
[INFO] ear ................................................ SKIPPED
[INFO] BUILD FAILURE
[INFO] Total time:  7.1 s
[ERROR] /w/web/src/main/java/com/acme/A.java:[12,8] cannot find symbol
[ERROR] /w/web/src/main/java/com/acme/B.java:[3,1] package javax.xml.bind does not exist
[ERROR] Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin:3.8.1:compile (default-compile) on project web
"""
TESTS = """[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0, Time elapsed: 0.1 s <<< FAILURE! - in com.acme.SvcTest
[INFO] Results:
[ERROR] Failures:
[ERROR]   SvcTest.total:12 expected:<1> but was:<2>
[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0
[INFO] BUILD FAILURE
[INFO] Total time:  3.0 s
"""
NET = """[INFO] BUILD FAILURE
[ERROR] Failed to execute goal on project web: Could not resolve dependencies for project a:web:war:1: Could not transfer artifact org.x:y:jar:1 from/to nexus (https://u:pw@nexus.corp/repo): Connection timed out
"""


def test_a_failed_reactor_build_names_modules_and_compile_errors():
    s = bs.summarize(FAIL, 1)
    assert s.passed is False and s.duration == "7.1 s" and s.compile_error_count == 2
    text = s.text()
    assert "Build summary: maven build FAILED" in text and "2/4 modules OK" in text and "2 compile error(s)" in text
    assert "web FAILURE" in text and "ear SKIPPED" in text and "A.java:12 cannot find symbol" in text


def test_test_failures_and_totals_are_reported():
    s = bs.summarize(TESTS, 1)
    assert s.tests == (3, 1, 0, 0) and "tests 3 run, 1 failed" in s.headline
    assert "SvcTest.total" in s.text()


def test_a_download_failure_is_named_as_environment_not_code():
    t = bs.summarize(NET, 1).text()
    assert "could not be downloaded" in t and "not a code problem" in t


def test_a_cut_off_build_has_no_verdict_and_a_pass_is_a_pass():
    t = bs.summarize("[INFO] Building web\n", 124).text()
    assert "NO VERDICT" in t and "nothing can be inferred" in t
    ok = bs.summarize("[INFO] BUILD SUCCESS\n[INFO] Total time:  1.2 s\n", 0)
    assert ok.passed is True and ok.text() == "Build summary: maven build PASSED (1.2 s)"
    g = bs.summarize("BUILD SUCCESSFUL in 4s\n", 0, "gradle")
    assert g.passed is True and "gradle build PASSED" in g.headline


def test_credentials_are_redacted():
    assert "pw" not in bs.redact("https://u:pw@nexus.corp/repo")


def test_a_quiet_build_is_judged_by_its_exit_code():
    assert bs.summarize("", 0).passed is True and bs.summarize("[ERROR] boom\n", 1).passed is False
    assert bs.summarize("TIMEOUT after 5s: mvn", 124).passed is None
