"""
Regressions for the defects found in the QA pass over the pipeline.

Each test names the failure it prevents, because several of these were silent:
the run completed, the build went green, and the damage was only visible in what
the migration did or did not touch.
"""
import pathlib
import shutil
import tempfile

import pytest

import main
from agents.java_8_to_25.agents import INCREMENTAL_STAGES
from agents.shared import callbacks
from agents.shared.change_audit import GENERATED_SUBTREES, audit_changes, to_markdown
from agents.shared.dependency_graph import EXCLUDED_DIRS

SKILLS = pathlib.Path(__file__).parent.parent / "agents" / "skills"


def _skill(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def _tree(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    return d


def _w(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class TestD2StrategyIsHonouredInABundle:
    def test_the_bundle_runner_dispatches_on_strategy_not_just_pattern(self):
        """Keying only on the pattern ran a phased 8-stage plan through the
        single-pass pipeline whenever a companion migration was selected, throwing
        away per-stage compilation and per-phase rollback without telling anyone."""
        import inspect

        src = inspect.getsource(main._run_bundle_code_generation)

        assert 'migration_strategy == "incremental"' in src
        assert "_run_java8_incremental_code_step" in src

    def test_the_incremental_runner_can_stream_to_a_different_session(self):
        """A bundle run executes agents in an isolated session but must push SSE
        events to the outward one."""
        import inspect

        params = inspect.signature(main._run_java8_incremental_code_step).parameters
        assert "push_session_id" in params


class TestD3StageGuardrailsAreActionable:
    def test_the_java_25_stage_does_not_both_forbid_and_require_the_rename(self):
        """With no Spring Boot upgrade, Spring 6 is the only route to Java 25 and
        Spring 6 IS jakarta — so this stage owns the rename. Stating the blanket
        prohibition too left the stage unactionable, and the cheapest way out for
        the fixer is reverting Spring, which the skills forbid."""
        guardrail = INCREMENTAL_STAGES[5].guardrail

        assert "do not rename Jakarta EE" not in guardrail
        assert "MUST happen in this stage" in guardrail
        assert "never revert Spring to 5.3" in guardrail

    def test_the_java_17_stage_still_forbids_the_rename(self):
        """Spring 5.3 is still javax, so there the prohibition is correct."""
        assert "do not rename Jakarta EE" in INCREMENTAL_STAGES[2].guardrail

    @pytest.mark.parametrize("stage", INCREMENTAL_STAGES)
    def test_no_guardrail_contradicts_itself_about_the_rename(self, stage):
        g = stage.guardrail
        forbids = "do not rename Jakarta EE" in g
        requires = "MUST happen in this stage" in g
        assert not (forbids and requires), f"Stage {stage.idx} both forbids and requires the rename"


class TestD4BuildOutputIsNotRepositorySource:
    @pytest.mark.parametrize("d", ["dist", "out", "coverage", ".next", ".nuxt", ".svelte-kit"])
    def test_js_build_output_is_excluded(self, d):
        assert d in EXCLUDED_DIRS

    def test_the_exclusion_list_has_one_definition(self):
        from agents.shared.workspace_tools import EXCLUDED_DIRS as from_tools

        assert from_tools is EXCLUDED_DIRS

    def test_a_frontend_build_does_not_swamp_the_change_audit(self, tmp_path):
        base, ws = _tree(tmp_path, "base"), _tree(tmp_path, "ws")
        _w(base, "src/main/webapp/WEB-INF/jsp/a.jsp", "<%@ taglib %>\n")
        _w(ws, "src/main/webapp/WEB-INF/jsp/a.jsp", "<%@ taglib %>\n")
        _w(ws, "frontend/src/pages/A.tsx", "export default function A(){}\n")
        for i in range(40):
            _w(ws, f"frontend/dist/assets/chunk-{i}.js", "console.log(1)\n")

        audit = audit_changes(str(base), str(ws), "jsp-to-react-bff")

        assert audit.changed_total == 1
        assert not [e for e in audit.unexplained if "/dist/" in e["path"]]


class TestD5GeneratedPatternsLeaveTheSourceAppAlone:
    def test_jsp_declares_its_generated_subtrees(self):
        assert GENERATED_SUBTREES["jsp-to-react-bff"] == ("backend/", "frontend/")

    def test_the_untouched_original_app_is_not_a_coverage_gap(self, tmp_path):
        """This pattern generates beside the original and the plan promises the
        old app stays deployable. Scanning it reported the entire source
        repository as missed work, one finding per JSP."""
        base, ws = _tree(tmp_path, "base"), _tree(tmp_path, "ws")
        for n in range(14):
            jsp = '<%@ taglib uri="http://java.sun.com/jsp/jstl/core" %>\n'
            _w(base, f"src/main/webapp/WEB-INF/jsp/p{n}.jsp", jsp)
            _w(ws, f"src/main/webapp/WEB-INF/jsp/p{n}.jsp", jsp)
        _w(ws, "frontend/src/pages/A.tsx", "import { useState } from 'react';\n")

        audit = audit_changes(str(base), str(ws), "jsp-to-react-bff")

        assert audit.residual_legacy == []
        assert audit.unchanged_out_of_scope == 14
        assert "not** coverage gaps" in to_markdown(audit)

    def test_legacy_surviving_INTO_a_generated_tree_is_still_caught(self, tmp_path):
        """Scoping the scan must not blind it to the defect that matters: a
        scriptlet copied into a generated template."""
        base, ws = _tree(tmp_path, "base"), _tree(tmp_path, "ws")
        for root in (base, ws):
            _w(root, "backend/src/main/resources/templates/legacy.html", "<%@ taglib %>\n")
        _w(ws, "frontend/src/pages/A.tsx", "import { useState } from 'react';\n")

        audit = audit_changes(str(base), str(ws), "jsp-to-react-bff")

        assert [e["path"] for e in audit.residual_legacy] == [
            "backend/src/main/resources/templates/legacy.html"
        ]

    def test_an_in_place_pattern_still_scans_everything(self, tmp_path):
        base, ws = _tree(tmp_path, "base"), _tree(tmp_path, "ws")
        for root in (base, ws):
            _w(root, "src/main/java/CacheAdmin.java", "import net.sf.ehcache.Cache;\n")
        _w(base, "pom.xml", "<project/>\n")
        _w(ws, "pom.xml", "<project><jakarta/></project>\n")

        audit = audit_changes(str(base), str(ws), "java-8-to-25")

        assert [e["path"] for e in audit.residual_legacy] == ["src/main/java/CacheAdmin.java"]
        assert audit.unchanged_out_of_scope == 0

    @pytest.mark.parametrize("suffix", [".html", ".htm", ".vue", ".svelte"])
    def test_templates_are_scannable(self, suffix):
        from agents.shared.change_audit import _SCAN_SUFFIXES

        assert suffix in _SCAN_SUFFIXES


class TestD6D7ModifySkillsMatchTheTools:
    @pytest.mark.parametrize(
        "skill",
        ["solr-4-to-9-modify", "tibco-ems-to-pubsub-modify", "oracle-19c-to-23ai-modify",
         "java-8-to-25-modify"],
    )
    def test_no_modify_skill_mandates_an_overwrite_the_tool_refuses(self, skill):
        """write_file refuses a full overwrite above one 20,000-char read window.
        Schema, solrconfig and PL/SQL package files routinely exceed that, so a
        numbered step telling the model to overwrite them is a dead end."""
        body = _skill(skill)

        assert "COMPLETE new content of the file (full overwrite" not in body
        assert "replace_in_file" in body

    @pytest.mark.parametrize(
        "skill",
        ["solr-4-to-9-modify", "tibco-ems-to-pubsub-modify", "oracle-19c-to-23ai-modify"],
    )
    def test_the_size_limit_is_explained_where_the_edit_is_made(self, skill):
        assert "20,000-character read window" in _skill(skill)


class TestD8ReverseEngineeringSectionsFailLoudly:
    def test_a_dropped_test_inventory_marker_is_recovered_from_its_heading(self):
        combined = (
            "<!-- SECTION: ANALYSIS -->\nA\n<!-- SECTION: BRD -->\nB\n"
            "<!-- SECTION: TECHNICAL_SPECIFICATION -->\nspec body\n"
            "#### SECTION 4 — EXISTING TEST INVENTORY\n41 JUnit 4 classes\n"
            "<!-- SECTION: END -->"
        )

        _, brd, spec, inventory = main._parse_re_sections(combined)

        assert "41 JUnit 4 classes" in inventory
        assert "TEST INVENTORY" not in spec
        assert "Automated warning" in brd

    def test_the_reviewer_is_warned_rather_than_shown_a_silently_empty_section(self):
        """The plan's Coverage Gaps are answered from test_inventory, so losing it
        produces a plan that quietly claims full coverage."""
        combined = "<!-- SECTION: ANALYSIS -->\nA\n<!-- SECTION: BRD -->\nB\n<!-- SECTION: END -->"

        _, brd, _, inventory = main._parse_re_sections(combined)

        assert "Automated warning" in brd
        assert "Automated warning" in inventory

    def test_a_well_formed_document_is_untouched(self):
        combined = (
            "<!-- SECTION: ANALYSIS -->\nA\n<!-- SECTION: BRD -->\nB\n"
            "<!-- SECTION: TECHNICAL_SPECIFICATION -->\nT\n"
            "<!-- SECTION: TEST_INVENTORY -->\nI\n<!-- SECTION: END -->"
        )

        assert main._parse_re_sections(combined) == ("A", "B", "T", "I")


class TestD10SkillWritesAreSafe:
    def test_learned_entries_are_capped(self):
        content = "# Skill\n\n## Learned Patterns\n" + "".join(
            f"### Validation Pass — 2026-01-{i:02d} 10:00\n- error {i}\n" for i in range(1, 31)
        )

        pruned = callbacks._prune_learned(content, max_entries=20)

        assert pruned.count("### Validation Pass") == 20
        assert "- error 30" in pruned and "- error 1\n" not in pruned

    def test_pruning_leaves_a_file_without_the_section_alone(self):
        content = "# Skill\n\nJust instructions.\n"
        assert callbacks._prune_learned(content) == content

    def test_the_write_is_lock_guarded(self):
        """Concurrent sessions share one skills directory; an unguarded
        read-modify-write loses one run's learning or interleaves into a file
        every later run then loads as its prompt."""
        import inspect

        src = inspect.getsource(callbacks)
        assert "fcntl.flock" in src
        assert "with _locked(skill_md_path):" in src

    def test_learning_can_be_switched_off_for_a_read_only_checkout(self):
        import inspect

        assert "MODERNIZER_SKILL_LEARNING" in inspect.getsource(callbacks)


class TestReverseEngineeringOutputContract:
    """The RE skill was rewritten and its output contract listed the five section
    markers as a consecutive block, saying only "in this exact order" — never that
    each section's content goes BETWEEN its marker and the next. A model reading it
    the other way emits all five markers together and every section parses empty,
    which the missing-marker check cannot see because the markers are all present."""

    @staticmethod
    def _re_skill() -> str:
        return _skill("java-8-to-25-re")

    def test_the_markers_are_described_as_separators(self):
        body = self._re_skill()

        assert "AS SEPARATORS" in body
        assert "goes BETWEEN its opening marker" in body
        assert "Never emit two markers in a row" in body

    def test_the_skill_shows_a_worked_shape_not_just_a_marker_list(self):
        body = self._re_skill()

        for n in range(1, 5):
            assert f"...all of SECTION {n} here..." in body

    def test_the_shape_the_skill_demonstrates_actually_parses(self):
        """The strongest form of this test: take the example out of the skill,
        fill it in, and run it through the real parser."""
        import re as _re

        demo = _re.search(
            r"Emit exactly this shape:\n\n(.*?)\n\nNever emit", self._re_skill(), _re.DOTALL
        ).group(1)
        filled = demo
        for n, text in enumerate(
            ["Scope: 412 files.", "Executive summary.", "Repo facts: Maven, 1.8.",
             "41 JUnit 4 classes."], start=1,
        ):
            filled = filled.replace(f"...all of SECTION {n} here...", text)

        analysis, brd, spec, inventory = main._parse_re_sections(filled)

        assert analysis.strip() and brd.strip() and spec.strip() and inventory.strip()
        assert "Automated warning" not in brd

    def test_markers_emitted_as_a_block_are_caught_rather_than_silently_empty(self):
        combined = (
            "<!-- SECTION: ANALYSIS -->\n<!-- SECTION: BRD -->\n"
            "<!-- SECTION: TECHNICAL_SPECIFICATION -->\n<!-- SECTION: TEST_INVENTORY -->\n"
            "<!-- SECTION: END -->\nSECTION 1 — analysis text\nSECTION 4 — test text\n"
        )

        _, brd, spec, inventory = main._parse_re_sections(combined)

        assert not spec.strip()
        assert "Automated warning" in brd
        assert "emitted together instead of as separators" in brd
        assert "Automated warning" in inventory

    def test_a_well_formed_document_raises_no_warning(self):
        combined = (
            "<!-- SECTION: ANALYSIS -->\nA\n<!-- SECTION: BRD -->\nB\n"
            "<!-- SECTION: TECHNICAL_SPECIFICATION -->\nT\n"
            "<!-- SECTION: TEST_INVENTORY -->\nI\n<!-- SECTION: END -->"
        )

        assert main._parse_re_sections(combined) == ("A", "B", "T", "I")


class TestDeprecationStatusSurvivesTheRewrite:
    """The plan and report build their "Deprecated Libraries" tables from the RE
    output's Status columns. The rewrite relabelled JUnit 3/4 as a "modernization
    candidate", which reads as evidence-based caution but silently removed the
    vocabulary those tables are assembled from."""

    @staticmethod
    def _re_skill() -> str:
        return _skill("java-8-to-25-re")

    def test_the_status_vocabulary_matches_what_the_plan_consumes(self):
        body = self._re_skill()

        for status in ("Deprecated", "EOL", "Insecure"):
            assert status in body, status
        # The plan skill asks for exactly this vocabulary.
        assert "Status (deprecated / EOL / insecure)" in _skill("java-8-to-25-plan")

    def test_junit_3_and_4_are_deprecated_regardless_of_the_toggle(self):
        body = self._re_skill()

        assert "Status **Deprecated**" in body
        assert "regardless of whether a JUnit upgrade was requested" in body
        assert "the toggle\n   gates the migration work, never the call-out" in body

    def test_the_vintage_engine_is_called_out_too(self):
        assert "`junit-vintage-engine` Deprecated" in self._re_skill()

    def test_status_and_impact_stay_separate_judgements(self):
        """The rewrite's evidence-based stance is preserved: a library's
        deprecation is an upstream fact, while whether it blocks THIS migration
        is the judgement that needs evidence from the repository."""
        body = self._re_skill()

        assert "Status is a fact about the library" in body
        assert "Impact is the evidence-based judgement" in body

    def test_the_test_class_counts_the_plan_needs_are_still_requested(self):
        body = self._re_skill()

        assert "JUnit 3 `TestCase` class count" in body
        assert "JUnit 4 test\n   class count" in body
