"""
Unit tests for agents/shared/change_audit.py — the deterministic audit the
code reviewer opens with, which answers the two questions reading the changed
files alone cannot: is every change really migration work, and is every
untouched file really irrelevant?
"""
import pathlib

import pytest

from agents.shared.change_audit import (
    LEGACY_MARKERS,
    MODERN_MARKERS,
    audit_changes,
    to_markdown,
)


def _write(root: pathlib.Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def trees(tmp_path):
    baseline = tmp_path / "baseline"
    workspace = tmp_path / "workspace"
    baseline.mkdir()
    workspace.mkdir()
    return baseline, workspace


def _audit(trees, pattern="java-8-to-25"):
    baseline, workspace = trees
    return audit_changes(str(baseline), str(workspace), pattern)


class TestDidAnythingChange:
    def test_identical_trees_report_no_changes_at_all(self, trees):
        baseline, workspace = trees
        for root in (baseline, workspace):
            _write(root, "src/App.java", "class App {}\n")

        audit = _audit(trees)

        assert audit.changed_total == 0
        assert audit.unchanged_total == 1
        report = to_markdown(audit)
        assert "Nothing changed" in report
        assert "CRITICAL" in report

    def test_a_missing_baseline_degrades_instead_of_crashing(self, tmp_path):
        audit = audit_changes(str(tmp_path / "gone"), str(tmp_path / "also-gone"), "java-8-to-25")

        assert audit.error
        assert "could not run" in to_markdown(audit)


class TestChangesAreRelevant:
    def test_a_legacy_import_replaced_by_a_modern_one_is_explained(self, trees):
        baseline, workspace = trees
        _write(baseline, "src/A.java", "import org.apache.log4j.Logger;\n")
        _write(workspace, "src/A.java", "import org.slf4j.Logger;\n")

        audit = _audit(trees)

        assert [e["path"] for e in audit.explained] == ["src/A.java"]
        assert audit.unexplained == []
        markers = {h["marker"] for h in audit.explained[0]["legacy_removed"]}
        assert "log4j 1.2" in markers

    def test_a_rewrite_with_no_migration_signal_is_flagged_for_adjudication(self, trees):
        baseline, workspace = trees
        _write(baseline, "src/Money.java", "class Money { int cents = 1; }\n")
        _write(workspace, "src/Money.java", "class Money {\n    int cents = 2;\n}\n")

        audit = _audit(trees)

        assert [e["path"] for e in audit.unexplained] == ["src/Money.java"]
        report = to_markdown(audit)
        assert "no migration signal" in report
        # It is a candidate, not a verdict — the reviewer decides against the plan.
        assert "scope creep" in report

    def test_an_added_file_carrying_target_stack_apis_counts_as_migration_work(self, trees):
        baseline, workspace = trees
        _write(workspace, "src/Config.java", "import jakarta.servlet.Filter;\n")

        audit = _audit(trees)

        assert audit.changed_total == 1
        assert audit.explained[0]["status"] == "added"
        assert audit.unexplained == []

    def test_re_adding_a_legacy_api_is_a_regression_not_migration_work(self, trees):
        baseline, workspace = trees
        _write(baseline, "pom.xml", "<dependencies></dependencies>\n")
        _write(workspace, "pom.xml", "<artifactId>mockito-all</artifactId>\n")

        audit = _audit(trees)

        assert [e["path"] for e in audit.regressions] == ["pom.xml"]
        assert "Mockito 1.x" in {h["marker"] for h in audit.regressions[0]["legacy_added"]}

    def test_the_add_opens_escape_hatch_is_reported_as_forbidden(self, trees):
        baseline, workspace = trees
        _write(baseline, "pom.xml", "<argLine></argLine>\n")
        _write(workspace, "pom.xml", "<argLine>--add-opens java.base/java.lang=ALL-UNNAMED</argLine>\n")

        audit = _audit(trees)

        assert audit.regressions
        assert "--add-opens" in to_markdown(audit)
        # Never silently counted as legitimate migration work.
        assert audit.explained == []


class TestUnchangedFilesAreIrrelevant:
    def test_an_untouched_file_still_holding_legacy_code_is_surfaced(self, trees):
        baseline, workspace = trees
        for root in (baseline, workspace):
            _write(root, "src/CacheOps.java", "import net.sf.ehcache.Cache;\n")
        _write(baseline, "src/A.java", "import org.apache.log4j.Logger;\n")
        _write(workspace, "src/A.java", "import org.slf4j.Logger;\n")

        audit = _audit(trees)

        assert [e["path"] for e in audit.residual_legacy] == ["src/CacheOps.java"]
        report = to_markdown(audit)
        assert "coverage gap" in report
        # The out-of-scope reading has to be offered too, or every stage boundary
        # and declined toggle becomes a false finding.
        assert "out of scope" in report

    def test_untouched_files_with_nothing_legacy_are_reported_as_genuinely_irrelevant(self, trees):
        baseline, workspace = trees
        for root in (baseline, workspace):
            _write(root, "src/Plain.java", "class Plain { }\n")
        _write(baseline, "src/A.java", "import org.apache.log4j.Logger;\n")
        _write(workspace, "src/A.java", "import org.slf4j.Logger;\n")

        audit = _audit(trees)

        assert audit.residual_legacy == []
        assert "genuinely out of scope" in to_markdown(audit)

    def test_unscannable_and_build_output_files_are_not_mistaken_for_gaps(self, trees):
        baseline, workspace = trees
        for root in (baseline, workspace):
            _write(root, "docs/notes.md", "we used net.sf.ehcache here once\n")
            _write(root, "target/classes/Old.java", "import org.apache.log4j.Logger;\n")
        _write(baseline, "src/A.java", "import org.apache.log4j.Logger;\n")
        _write(workspace, "src/A.java", "import org.slf4j.Logger;\n")

        audit = _audit(trees)

        assert audit.residual_legacy == []


class TestMarkerAccuracy:
    def test_java_se_javax_packages_are_never_treated_as_the_jakarta_rename(self, trees):
        baseline, workspace = trees
        for root in (baseline, workspace):
            _write(
                root,
                "src/Db.java",
                "import javax.sql.DataSource;\nimport javax.naming.InitialContext;\n"
                "import javax.crypto.Cipher;\nimport javax.cache.CacheManager;\n"
                "import javax.xml.parsers.DocumentBuilder;\n",
            )
        _write(baseline, "src/A.java", "import org.apache.log4j.Logger;\n")
        _write(workspace, "src/A.java", "import org.slf4j.Logger;\n")

        audit = _audit(trees)

        assert audit.residual_legacy == [], "Java SE javax.* and JSR-107 javax.cache never get renamed"

    def test_jakarta_ee_javax_packages_are_treated_as_the_jakarta_rename(self, trees):
        baseline, workspace = trees
        for root in (baseline, workspace):
            _write(root, "src/Web.java", "import javax.servlet.http.HttpServlet;\n")
        _write(baseline, "src/A.java", "import org.apache.log4j.Logger;\n")
        _write(workspace, "src/A.java", "import org.slf4j.Logger;\n")

        audit = _audit(trees)

        assert [e["path"] for e in audit.residual_legacy] == ["src/Web.java"]

    @pytest.mark.parametrize(
        "snippet, expected",
        [
            ("import org.codehaus.jackson.map.ObjectMapper;", "Jackson 1"),
            ("import org.springframework.orm.hibernate3.HibernateTemplate;", "Spring 3/4 hibernate3 support"),
            ("<artifactId>cglib-nodep</artifactId>", "cglib / javassist"),
            ("<artifactId>google-collections</artifactId>", "google-collections"),
            ("import junit.framework.TestCase;", "JUnit 3"),
            ("import org.junit.Test;", "JUnit 4"),
            ("<source>1.8</source>", "Java 8 compiler level"),
            ("<artifactId>ojdbc6</artifactId>", "legacy Oracle JDBC driver"),
            ("hibernate.dialect=org.hibernate.dialect.Oracle10gDialect", "Oracle versioned dialect"),
            ("mapper.enableDefaultTyping();", "Jackson unsafe default typing"),
        ],
    )
    def test_each_java_8_era_stack_is_detected_in_an_untouched_file(self, trees, snippet, expected):
        baseline, workspace = trees
        for root in (baseline, workspace):
            _write(root, "src/Legacy.java", snippet + "\n")
        _write(baseline, "src/A.java", "import org.apache.log4j.Logger;\n")
        _write(workspace, "src/A.java", "import org.slf4j.Logger;\n")

        audit = _audit(trees)

        assert audit.residual_legacy, f"{snippet!r} should match the {expected!r} marker"
        assert expected in {h["marker"] for h in audit.residual_legacy[0]["legacy_present"]}

    def test_every_pattern_with_legacy_markers_also_has_modern_ones(self):
        # A pattern with only legacy markers would flag every change as
        # unexplained unless it happened to delete a legacy line.
        assert set(LEGACY_MARKERS) == set(MODERN_MARKERS)

    def test_a_pattern_without_markers_still_reports_the_changed_unchanged_split(self, trees):
        baseline, workspace = trees
        _write(baseline, "a.txt", "one\n")
        _write(workspace, "a.txt", "two\n")

        audit = _audit(trees, pattern="some-future-pattern")

        assert audit.changed_total == 1
        assert not audit.markers_configured
        assert "No relevance markers are configured" in to_markdown(audit)


class TestReviewerWiring:
    """Every pattern's code reviewer gets the audit from the shared factory —
    a pattern that quietly lost it would review from the changed files alone
    and could never answer the untouched-file question."""

    @pytest.mark.parametrize(
        "module_path",
        [
            "agents.java_8_to_25.agents",
            "agents.oracle_19c_to_23ai.agents",
            "agents.solr_4_to_9.agents",
            "agents.tibco_ems_to_pubsub.agents",
            "agents.jsp_to_react_bff.agents",
        ],
    )
    def test_each_pattern_code_reviewer_can_audit_changes(self, module_path):
        import importlib

        module = importlib.import_module(module_path)
        tool_names = {getattr(t, "name", "") for t in module.code_reviewer_agent.tools}
        assert "audit_migration_changes" in tool_names

    def test_the_incremental_java_reviewer_can_audit_changes_too(self):
        from agents.java_8_to_25.agents import incremental_code_reviewer_agent

        tool_names = {getattr(t, "name", "") for t in incremental_code_reviewer_agent.tools}
        assert "audit_migration_changes" in tool_names

    def test_the_reviewer_is_told_to_audit_before_reading_files(self):
        from agents.java_8_to_25.agents import code_reviewer_agent

        assert "audit_migration_changes` FIRST" in code_reviewer_agent.instruction


class TestSkillContract:
    """The tool only produces evidence; the skill is what turns it into the
    two answers the user asked the review for."""

    @staticmethod
    def _skill(name: str) -> str:
        return (
            pathlib.Path(__file__).parent.parent / "agents" / "skills" / name / "SKILL.md"
        ).read_text(encoding="utf-8")

    def test_the_audit_is_the_reviews_first_step(self):
        body = self._skill("code-review")
        assert "audit_migration_changes` **first, before any other tool**" in body
        assert body.index("audit_migration_changes") < body.index("Call `list_files`")

    def test_the_review_must_answer_both_relevance_questions(self):
        body = self._skill("code-review")
        assert "## Change Relevance" in body
        assert "All changes relevant?" in body
        assert "All untouched files irrelevant?" in body

    def test_a_no_op_run_cannot_be_reported_as_a_success(self):
        body = self._skill("code-review")
        assert "CRITICAL headline finding" in body
        assert "NEEDS FOLLOW-UP" in body

    def test_findings_require_adjudication_against_the_plan(self):
        body = self._skill("code-review")
        assert "Adjudicate every audit candidate against the confirmed plan" in body
        assert "regex evidence, not verdicts" in body
        # An out-of-scope stage or a declined toggle is not a coverage gap.
        assert "off toggle" in body or "declined" in body

    def test_the_report_carries_the_coverage_answer_to_the_human(self):
        body = self._skill("java-8-to-25-report")
        assert "## Migration Coverage" in body
        assert "prefer it over the Modify Results" in body
