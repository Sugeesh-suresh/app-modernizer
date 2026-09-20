"""
Unit tests for agents/shared/plan_coverage.py — the conformance check that
compares what actually changed against the File Change Manifest in the plan
a human confirmed, so the review can tell under-delivery from scope creep.
"""
import pathlib

import pytest

from agents.shared.plan_coverage import (
    compare_plan_to_changes,
    parse_plan_manifest,
    to_markdown,
)

TABLE_PLAN = """
## File Change Manifest

| File | Change Type | What Changes |
|---|---|---|
| `src/main/java/com/acme/OrderServlet.java` | namespace migration | `javax.servlet.*` → `jakarta.servlet.*` |
| `src/main/java/com/acme/CacheAdmin.java` | dependency bump | Ehcache 2 → 3, `getKeys()` rewritten |
| `src/main/java/com/acme/Address.java` | no change needed | plain POJO |
"""

TASK_PLAN = """
## Stage 3: Java 8 → Java 17 LTS

### Task 3.1: Raise Spring Framework to 5.3.x
- Files: `pom.xml`, `src/main/java/com/acme/HibernateConfig.java`
- Depends on: none
- Change: bump org.springframework to 5.3.39 and rewrite orm.hibernate3 onto hibernate5
- Done when: no hibernate3 imports remain
"""


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


def _compare(plan, trees):
    baseline, workspace = trees
    paths = sorted(
        str(p.relative_to(workspace)) for p in workspace.rglob("*") if p.is_file()
    )
    return compare_plan_to_changes(plan, str(baseline), str(workspace), paths)


class TestManifestParsing:
    def test_a_manifest_table_yields_a_path_and_its_planned_change(self):
        planned = {e.path: e for e in parse_plan_manifest(TABLE_PLAN)}

        assert set(planned) == {
            "src/main/java/com/acme/OrderServlet.java",
            "src/main/java/com/acme/CacheAdmin.java",
            "src/main/java/com/acme/Address.java",
        }
        assert "jakarta.servlet" in planned["src/main/java/com/acme/OrderServlet.java"].change
        assert planned["src/main/java/com/acme/Address.java"].no_change_expected

    def test_task_blocks_attribute_the_tasks_change_text_to_each_of_its_files(self):
        planned = {e.path: e for e in parse_plan_manifest(TASK_PLAN)}

        assert set(planned) == {"pom.xml", "src/main/java/com/acme/HibernateConfig.java"}
        for entry in planned.values():
            assert "hibernate5" in entry.change
            assert entry.source == "Task 3.1"

    def test_checkbox_and_bullet_manifests_are_understood_too(self):
        plan = (
            "## File Change Manifest\n"
            "- [ ] `src/main/resources/log4j.properties` — replaced by logback.xml\n"
            "- [x] `pom.xml` — remove log4j, add slf4j\n"
        )
        planned = {e.path: e for e in parse_plan_manifest(plan)}

        assert set(planned) == {"src/main/resources/log4j.properties", "pom.xml"}
        assert "logback" in planned["src/main/resources/log4j.properties"].change

    def test_prose_and_table_headers_are_not_mistaken_for_files(self):
        plan = (
            "## File Change Manifest\n"
            "| File | Change Type | What Changes |\n|---|---|---|\n"
            "| `pom.xml` | dependency bump | Spring 5.3 |\n\n"
            "- The migration will touch the persistence layer and the web tier.\n"
            "- Files: none\n"
        )
        assert [e.path for e in parse_plan_manifest(plan)] == ["pom.xml"]

    def test_a_stage_with_both_task_blocks_and_a_table_yields_no_duplicates(self):
        """The phased plan emits both: tasks drive the modifier, the table is what
        the human approves. A path in both must not become two planned entries,
        and the table must still contribute the files no task mentions."""
        combined = TASK_PLAN + """
### File Change Manifest — Stage 3

| File | Change Type | What Changes |
|---|---|---|
| `pom.xml` | dependency bump | spring-* → 5.3.39 |
| `src/main/java/com/acme/HibernateConfig.java` | dependency bump | hibernate3 → hibernate5 |
| `src/main/java/com/acme/Address.java` | no change needed | plain POJO |
"""
        planned = {e.path: e for e in parse_plan_manifest(combined)}

        assert len(planned) == 3
        # The task's own Change: text wins for files the tasks name.
        assert planned["pom.xml"].source == "Task 3.1"
        # The table still adds the file no task touches.
        assert planned["src/main/java/com/acme/Address.java"].no_change_expected

    @pytest.mark.parametrize(
        "prose",
        [
            "- Done when: no `.jsp` remains under `src/main/webapp`",
            "- Change: packaging becomes `<packaging>jar</packaging>`",
            "- Change: `org.apache.log4j.Logger` becomes `org.slf4j.Logger`",
            "- Change: `com.fasterxml.jackson.databind` moves to `tools.jackson.databind`",
            "- Change: order ids come from `seq_order.NEXTVAL`",
            "- Change: set `maven.compiler.release` to 17",
            "- Note: the bug lives in `PricingService.applyVolumeDiscount`",
        ],
    )
    def test_prose_that_merely_looks_path_shaped_is_not_a_planned_file(self, prose):
        """A bare extension, an XML tag and a dotted Java name all have the
        shape of a path. Treating one as a manifest entry invents a file nobody
        planned, which then gets reported as an unmet promise."""
        plan = "## File Change Manifest\n" + prose + "\n"

        assert parse_plan_manifest(plan) == []

    def test_real_bare_filenames_are_still_recognised(self):
        plan = (
            "## File Change Manifest\n"
            "- [ ] `pom.xml` — plugins pinned\n"
            "- [ ] `rewrite.yml` — recipes declared\n"
        )

        assert [e.path for e in parse_plan_manifest(plan)] == ["pom.xml", "rewrite.yml"]

    def test_a_plan_with_no_manifest_parses_to_nothing(self):
        assert parse_plan_manifest("## Overview\nWe will modernise the build.\n") == []


class TestUnderDelivery:
    def test_a_planned_file_left_untouched_is_reported_with_its_planned_change(self, trees):
        baseline, workspace = trees
        for root in (baseline, workspace):
            _write(root, "src/main/java/com/acme/CacheAdmin.java", "import net.sf.ehcache.Cache;\n")
        _write(baseline, "src/main/java/com/acme/OrderServlet.java", "import javax.servlet.http.HttpServlet;\n")
        _write(workspace, "src/main/java/com/acme/OrderServlet.java", "import jakarta.servlet.http.HttpServlet;\n")

        coverage = _compare(TABLE_PLAN, trees)

        assert [e.path for e in coverage.missing] == ["src/main/java/com/acme/CacheAdmin.java"]
        report = to_markdown(coverage)
        assert "under-delivery" in report
        assert "getKeys()" in report, "the report must quote what the plan promised"

    def test_a_delivered_plan_reports_no_under_delivery(self, trees):
        baseline, workspace = trees
        _write(baseline, "pom.xml", "<project/>\n")
        _write(workspace, "pom.xml", "<project><spring>5.3.39</spring></project>\n")
        _write(baseline, "src/main/java/com/acme/HibernateConfig.java", "import org.springframework.orm.hibernate3.X;\n")
        _write(workspace, "src/main/java/com/acme/HibernateConfig.java", "import org.springframework.orm.hibernate5.X;\n")

        coverage = _compare(TASK_PLAN, trees)

        assert coverage.missing == []
        assert coverage.unplanned == []
        assert len(coverage.as_planned) == 2
        assert "every file the plan promised to change was changed" in to_markdown(coverage)


class TestUnapprovedScope:
    def test_a_file_changed_outside_the_manifest_is_reported(self, trees):
        baseline, workspace = trees
        _write(baseline, "pom.xml", "<project/>\n")
        _write(workspace, "pom.xml", "<project><spring>5.3.39</spring></project>\n")
        _write(baseline, "src/main/java/com/acme/HibernateConfig.java", "import org.springframework.orm.hibernate3.X;\n")
        _write(workspace, "src/main/java/com/acme/HibernateConfig.java", "import org.springframework.orm.hibernate5.X;\n")
        # Nobody approved this one.
        _write(baseline, "src/main/java/com/acme/PricingRules.java", "double rate = 0.10;\n")
        _write(workspace, "src/main/java/com/acme/PricingRules.java", "double rate = 0.15;\n")

        coverage = _compare(TASK_PLAN, trees)

        assert [p for p, _ in coverage.unplanned] == ["src/main/java/com/acme/PricingRules.java"]
        assert "unapproved scope" in to_markdown(coverage)

    def test_a_file_the_plan_said_to_leave_alone_is_a_contradiction_not_scope_creep(self, trees):
        baseline, workspace = trees
        for root in (baseline, workspace):
            _write(root, "src/main/java/com/acme/CacheAdmin.java", "import net.sf.ehcache.Cache;\n")
        _write(baseline, "src/main/java/com/acme/OrderServlet.java", "import javax.servlet.http.HttpServlet;\n")
        _write(workspace, "src/main/java/com/acme/OrderServlet.java", "import jakarta.servlet.http.HttpServlet;\n")
        _write(baseline, "src/main/java/com/acme/Address.java", "class Address { String city; }\n")
        _write(workspace, "src/main/java/com/acme/Address.java", "class Address { String city; String zip; }\n")

        coverage = _compare(TABLE_PLAN, trees)

        assert [a for _, a in coverage.contradicted] == ["src/main/java/com/acme/Address.java"]
        assert coverage.unplanned == [], "an excluded file is not unplanned — the plan named it"
        assert 'no change needed" in the plan, but changed' in to_markdown(coverage)


class TestPathResolution:
    def test_an_abbreviated_plan_path_resolves_to_the_real_source_file(self, trees):
        baseline, workspace = trees
        plan = "| File | Change Type | What Changes |\n|---|---|---|\n| `com/acme/Order.java` | bump | x |\n"
        for root in (baseline, workspace):
            _write(root, "src/main/java/com/acme/Order.java", "class Order {}\n")
        _write(workspace, "src/main/java/com/acme/Order.java", "class Order { int id; }\n")

        coverage = _compare(plan, trees)

        assert len(coverage.as_planned) == 1
        assert coverage.as_planned[0][1] == "src/main/java/com/acme/Order.java"
        assert coverage.unresolved == []

    def test_a_glob_entry_resolves_to_every_matching_file(self, trees):
        baseline, workspace = trees
        plan = "| File | Change Type | What Changes |\n|---|---|---|\n| `src/main/resources/*.properties` | config | externalised |\n"
        for name in ("app.properties", "db.properties"):
            _write(baseline, f"src/main/resources/{name}", "a=1\n")
            _write(workspace, f"src/main/resources/{name}", "a=2\n")

        coverage = _compare(plan, trees)

        assert len(coverage.as_planned) == 2
        assert coverage.unplanned == []

    def test_a_directory_entry_resolves_to_the_files_under_it(self, trees):
        """"_23 files under_ `src/main/java/com/acme/`" is how a plan
        abbreviates a package it would be noise to list in full."""
        baseline, workspace = trees
        plan = "| File | Change Type | What Changes |\n|---|---|---|\n| `src/main/java/com/acme/` | logging | log4j → slf4j |\n"
        for name in ("A.java", "B.java"):
            _write(baseline, f"src/main/java/com/acme/{name}", "import org.apache.log4j.Logger;\n")
            _write(workspace, f"src/main/java/com/acme/{name}", "import org.slf4j.Logger;\n")

        coverage = _compare(plan, trees)

        assert len(coverage.as_planned) == 2
        assert coverage.unresolved == []
        assert coverage.unplanned == []

    def test_a_manifest_path_matching_nothing_is_reported_against_the_plan(self, trees):
        baseline, workspace = trees
        plan = "| File | Change Type | What Changes |\n|---|---|---|\n| `src/main/java/com/acme/Ghost.java` | delete | dead code |\n"
        _write(baseline, "pom.xml", "<project/>\n")
        _write(workspace, "pom.xml", "<project/>\n")

        coverage = _compare(plan, trees)

        assert [e.path for e in coverage.unresolved] == ["src/main/java/com/acme/Ghost.java"]
        assert "matching no file in the workspace" in to_markdown(coverage)

    def test_an_ambiguous_suffix_is_left_unresolved_rather_than_matched_wrongly(self, trees):
        baseline, workspace = trees
        plan = "| File | Change Type | What Changes |\n|---|---|---|\n| `Config.java` | bump | x |\n"
        for module in ("moduleA", "moduleB"):
            for root in (baseline, workspace):
                _write(root, f"{module}/src/Config.java", "class Config {}\n")

        coverage = _compare(plan, trees)

        assert [e.path for e in coverage.unresolved] == ["Config.java"]
        assert coverage.missing == [], "an ambiguous entry must not be reported as under-delivery"


class TestDegradedInputs:
    def test_a_plan_with_no_manifest_says_so_instead_of_blaming_every_file(self, trees):
        baseline, workspace = trees
        _write(baseline, "pom.xml", "<project/>\n")
        _write(workspace, "pom.xml", "<project><a/></project>\n")

        coverage = _compare("## Overview\nWe will modernise the build.\n", trees)

        assert not coverage.manifest_found
        report = to_markdown(coverage)
        assert "No file manifest could be parsed" in report
        assert "do not report them individually" in report

    def test_a_missing_baseline_degrades_instead_of_crashing(self, tmp_path):
        coverage = compare_plan_to_changes(TABLE_PLAN, "", "", [])

        assert coverage.error
        assert "could not be checked" in to_markdown(coverage)


class TestWiring:
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
    def test_each_pattern_code_reviewer_can_check_plan_conformance(self, module_path):
        import importlib

        module = importlib.import_module(module_path)
        tool_names = {getattr(t, "name", "") for t in module.code_reviewer_agent.tools}
        assert "compare_plan_to_actual_changes" in tool_names

    def test_the_incremental_java_reviewer_can_check_plan_conformance_too(self):
        from agents.java_8_to_25.agents import incremental_code_reviewer_agent

        tool_names = {getattr(t, "name", "") for t in incremental_code_reviewer_agent.tools}
        assert "compare_plan_to_actual_changes" in tool_names


class TestSkillContract:
    @staticmethod
    def _skill(name: str) -> str:
        return (
            pathlib.Path(__file__).parent.parent / "agents" / "skills" / name / "SKILL.md"
        ).read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "skill",
        [
            "java-8-to-25-plan",
            "solr-4-to-9-plan",
            "oracle-19c-to-23ai-plan",
            "tibco-ems-to-pubsub-plan",
            "jsp-to-react-bff-plan",
        ],
    )
    def test_every_plan_states_the_change_per_file_in_a_parseable_table(self, skill):
        body = self._skill(skill)
        assert "| File | Change Type |" in body
        # A path that is neither backticked nor real cannot be checked afterwards.
        assert "backticked" in body.lower()
        assert "never invented" in body

    def test_every_in_scope_file_needs_a_row_including_the_untouched_ones(self):
        for skill in ("java-8-to-25-plan", "solr-4-to-9-plan", "oracle-19c-to-23ai-plan",
                      "tibco-ems-to-pubsub-plan"):
            body = self._skill(skill)
            assert "no change needed" in body
            assert "Every in-scope file gets a row" in body

    def test_the_phased_plan_keeps_its_task_blocks_and_adds_the_table(self):
        body = self._skill("java-8-to-25-plan")
        # Task blocks stay load-bearing for the per-task modifier runs.
        assert "### Task <stage number>.<task number>" in body
        assert "- Files: `path/one.java`, `path/two.java`" in body
        assert "Each stage then closes with its own **File Change Manifest** table" in body

    def test_the_review_runs_the_plan_check_and_reports_both_directions(self):
        body = self._skill("code-review")
        assert "compare_plan_to_actual_changes` second" in body
        assert "## Plan Conformance" in body
        assert "Under-delivered:" in body
        assert "Beyond the plan:" in body

    def test_an_undelivered_plan_cannot_be_reported_as_clean(self):
        body = self._skill("code-review")
        assert "where the manifest promised work that was not delivered, is always **NEEDS FOLLOW-UP**" in body

    def test_the_report_carries_plan_conformance_to_the_human(self):
        body = self._skill("java-8-to-25-report")
        assert "Plan Conformance" in body
        assert "Carry every confirmed under-delivery into Follow-up Recommendations" in body
