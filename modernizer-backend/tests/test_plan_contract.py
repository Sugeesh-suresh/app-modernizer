"""
Unit tests for the six questions every migration plan must answer
(agents/shared/plan_contract.py) and for the Skill Composition table the
application computes rather than letting the planner invent
(agents/shared/skill_manifest.py).
"""
import importlib
import pathlib
import re

import pytest

from agents.shared import skill_manifest
from agents.shared.plan_contract import (
    QUESTIONS,
    check,
    make_plan_contract_callback,
    to_markdown,
)

PATTERNS = [
    "java_8_to_25",
    "oracle_19c_to_23ai",
    "solr_4_to_9",
    "tibco_ems_to_pubsub",
    "jsp_to_react_bff",
]

PLAN_SKILLS = [
    "java-8-to-25-plan",
    "oracle-19c-to-23ai-plan",
    "solr-4-to-9-plan",
    "tibco-ems-to-pubsub-plan",
    "jsp-to-react-bff-plan",
]

SKILLS_DIR = pathlib.Path(__file__).parent.parent / "agents" / "skills"


def _skill(name: str) -> str:
    return (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")


def _complete_plan() -> str:
    lines = ["# Migration Plan", "", "## Overview", "Current state.", ""]
    for question in QUESTIONS:
        lines += [f"## {question.number}. {question.heading}", ""]
        for part, _ in question.parts:
            lines += [f"### {part.split('|')[0]}", "Content.", ""]
    return "\n".join(lines)


class TestTheContract:
    def test_the_six_questions_are_the_ones_asked(self):
        assert [q.heading for q in QUESTIONS] == [
            "What Changes",
            "What Stays the Same",
            "Why This Is Safe",
            "How We'll Prove It Worked",
            "What Happens If It Fails",
            "What the Planner Doesn't Know",
        ]

    def test_a_plan_answering_all_six_is_complete(self):
        result = check(_complete_plan())

        assert result.complete
        assert to_markdown(result) == ""

    def test_a_missing_question_is_reported_with_all_of_its_parts(self):
        plan = _complete_plan().replace("## 2. What Stays the Same", "## Something Else")

        result = check(plan)

        assert [q.number for q in result.missing_questions] == [2]
        report = to_markdown(result)
        assert "Explicit Non-Changes" in report
        assert "Out of Scope" in report

    def test_a_present_but_incomplete_question_is_reported_by_part(self):
        plan = _complete_plan().replace("### Behaviour Inventory", "### Something Else")

        result = check(plan)

        assert result.missing_questions == []
        assert [part for _, part, _ in result.missing_parts] == ["Behaviour Inventory"]
        assert "is missing `Behaviour Inventory`" in to_markdown(result)

    def test_an_empty_plan_is_missing_everything(self):
        assert len(check("").missing_questions) == len(QUESTIONS)

    @pytest.mark.parametrize(
        "heading",
        [
            "## 2. What Stays the Same",
            "## What stays the same",
            "## 2) What Stays The Same",
            "### What Stays the Same",
        ],
    )
    def test_heading_matching_survives_a_reviewers_rewording(self, heading):
        """The plan is hand-editable in the review screen, so a reviewer's
        renumbering or recapitalisation must not trip the check."""
        plan = _complete_plan().replace("## 2. What Stays the Same", heading)

        assert check(plan).complete


class TestTheCallback:
    class _State(dict):
        pass

    class _Ctx:
        def __init__(self, state):
            self.state = state

    def test_a_plan_with_gaps_is_annotated_for_the_human_reviewer(self):
        state = self._State({"plan": "# Plan\n\n## Overview\nOnly this.\n"})
        make_plan_contract_callback()(self._Ctx(state))

        assert "## ⚠ Plan Completeness Check" in state["plan"]
        # The original plan is kept — the check annotates, never rewrites.
        assert "Only this." in state["plan"]

    def test_a_complete_plan_is_left_untouched(self):
        plan = _complete_plan()
        state = self._State({"plan": plan})
        make_plan_contract_callback()(self._Ctx(state))

        assert state["plan"] == plan

    def test_the_warning_is_not_appended_twice_on_a_refine_pass(self):
        state = self._State({"plan": "# Plan\n\n## Overview\nThin.\n"})
        callback = make_plan_contract_callback()
        callback(self._Ctx(state))
        first = state["plan"]
        callback(self._Ctx(state))

        assert state["plan"] == first

    def test_an_empty_plan_is_not_annotated(self):
        state = self._State({"plan": ""})
        make_plan_contract_callback()(self._Ctx(state))

        assert state["plan"] == ""


class TestSkillComposition:
    """The table names the skills and their order — nothing that has to be
    hand-maintained. A version or maturity field would be a number any person
    could set to "stable" without evidence, which reads as an assurance to an
    approver while carrying none."""

    def test_the_table_is_the_roster_and_the_order_only(self):
        table = skill_manifest.to_markdown([
            ("java-8-to-25-re", "Reverse-engineered this repository"),
            ("java-8-to-25-plan", "Produces this plan"),
        ])

        assert "| # | Skill | What it governs in this run |" in table
        assert "| 1 | `java-8-to-25-re` |" in table
        assert "| 2 | `java-8-to-25-plan` |" in table

    def test_no_version_or_maturity_is_claimed_anywhere(self):
        table = skill_manifest.to_markdown([("java-8-to-25-plan", "Produces this plan")])

        for unearned in ("version", "maturity", "stable", "experimental", "0.1.0"):
            assert unearned not in table.lower()

    def test_no_skill_declares_a_hand_maintained_version_or_maturity(self):
        for path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
            body = path.read_text(encoding="utf-8")
            assert not re.search(r"^version:", body, re.MULTILINE), path.parent.name
            assert not re.search(r"^maturity:", body, re.MULTILINE), path.parent.name

    def test_a_missing_skill_is_reported_rather_than_silently_dropped(self):
        """This one IS earned — the file is either on disk or it is not."""
        table = skill_manifest.to_markdown([("no-such-skill", "Does nothing")])

        assert "not found on disk" in table
        assert "report this before approving" in table

    def test_a_real_skill_is_not_flagged_as_missing(self):
        table = skill_manifest.to_markdown([("java-8-to-25-plan", "Produces this plan")])

        assert "not found" not in table

    def test_the_planner_is_told_to_copy_the_table_not_write_one(self):
        block = skill_manifest.planner_block([("java-8-to-25-plan", "Produces this plan")])

        assert "never reorder them" in block
        # It may drop rows for a strategy this run did not ask for.
        assert "DROP a row" in block


class TestWiring:
    @pytest.mark.parametrize("module_path", PATTERNS)
    def test_every_planner_gets_the_composition_table(self, module_path):
        planner = importlib.import_module(f"agents.{module_path}.agents").planner_agent

        assert "| # | Skill | What it governs in this run |" in planner.instruction

    @pytest.mark.parametrize("module_path", PATTERNS)
    def test_every_planner_receives_the_test_inventory(self, module_path):
        """Question 4 is answered from it — a planner without it can only guess
        at coverage gaps."""
        planner = importlib.import_module(f"agents.{module_path}.agents").planner_agent

        assert "{test_inventory}" in planner.instruction

    @pytest.mark.parametrize("module_path", PATTERNS)
    def test_every_planner_runs_the_completeness_check(self, module_path):
        planner = importlib.import_module(f"agents.{module_path}.agents").planner_agent

        assert planner.after_agent_callback is not None

    def test_the_jsp_planner_keeps_its_ux_design_callback(self):
        from agents.jsp_to_react_bff.agents import planner_agent

        assert planner_agent.before_model_callback is not None


class TestPlanSkillsDeclareTheSixQuestions:
    @pytest.mark.parametrize("skill", PLAN_SKILLS)
    def test_the_skill_tells_the_planner_to_emit_all_six(self, skill):
        body = _skill(skill)
        for question in QUESTIONS:
            assert question.heading in body, f"{skill} never mentions {question.heading}"

    @pytest.mark.parametrize("skill", PLAN_SKILLS)
    def test_the_skill_names_every_required_subsection(self, skill):
        body = _skill(skill)
        for question in QUESTIONS:
            for part, _ in question.parts:
                # A part may offer `|`-separated alternatives (a two-tree pattern
                # calls its manifests "Backend/Frontend File Manifest").
                assert any(alt in body for alt in part.split("|")), \
                    f"{skill} never mentions {part}"

    @pytest.mark.parametrize("skill", PLAN_SKILLS)
    def test_inferred_claims_must_be_marked(self, skill):
        body = _skill(skill)
        assert "verified" in body and "inferred" in body

    @pytest.mark.parametrize("skill", ["oracle-19c-to-23ai-plan", "tibco-ems-to-pubsub-plan"])
    def test_patterns_without_clean_rollback_say_so_outright(self, skill):
        """Oracle DDL and published messages cannot be reversed, and the
        approver needs that before approving, not after."""
        body = _skill(skill)

        assert "**Rollback is not clean" in body
        assert "before approving, not after" in body

    def test_the_phased_java_plan_keeps_its_parseable_stage_headings(self):
        """The six questions are siblings of the stages, never parents — the
        modifier finds a stage by its `## Stage <n>: <title>` heading."""
        body = _skill("java-8-to-25-plan")

        assert "## Stage 1: Modernize Build Systems (Maven/Gradle)" in body
        assert "stay at `##` level" in body
