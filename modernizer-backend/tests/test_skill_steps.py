"""One skill per migration, one step file per pipeline step (agents/shared/skill_steps.py)."""
import re

import pytest
from google.adk.skills import load_skill_from_dir

from agents.shared import rosters, skill_manifest, skill_steps
from agents.shared.learned_fixes import skill_targets
from cli import patterns as P

MIGRATIONS = ["oracle-19c-to-23ai", "solr-4-to-9", "tibco-ems-to-pubsub", "java-8-to-11", "java-8-to-25",
              "jsp-to-react-bff"]
OLD_PER_STEP = re.compile(r"\b(?:oracle-19c-to-23ai|solr-4-to-9|tibco-ems-to-pubsub|java-8-to-11|java-8-to-25|"
                          r"jsp-to-react-bff)-(?:re|re-module|plan|modify|validate|fix|report)\b|"
                          r"\b(?:jsp-re|jsp-logic-classifier|java-migration-readiness|springboot-incremental-upgrade|"
                          r"springboot-war-to-boot4)\b")


@pytest.mark.parametrize("migration", MIGRATIONS)
def test_each_migration_is_one_skill_with_a_step_file_per_step(migration):
    skill = load_skill_from_dir(skill_steps.SKILLS_DIR / migration)          # ADK: name matches the folder
    steps = sorted(k[len("steps/"):-3] for k in skill.resources.references if k.startswith("steps/"))
    assert {"plan", "validate", "fix", "report"} <= set(steps)
    overview = (skill_steps.SKILLS_DIR / migration / "SKILL.md").read_text()
    for step in steps:                                                       # the workflow names every step file
        assert f"`references/steps/{step}.md`" in overview, step


@pytest.mark.parametrize("migration", MIGRATIONS)
def test_every_knowledge_file_a_step_names_exists(migration):
    root = skill_steps.SKILLS_DIR / migration
    for path in [root / "SKILL.md", *sorted((root / "references" / "steps").glob("*.md"))]:
        for name in re.findall(r"`references/([\w./-]+\.md)`", path.read_text()):
            assert (root / "references" / name).is_file(), f"{path.name} names references/{name}"


def test_no_skill_text_names_a_per_step_skill_that_no_longer_exists():
    for path in skill_steps.SKILLS_DIR.rglob("*.md"):
        found = OLD_PER_STEP.findall(path.read_text())
        assert not found, f"{path.relative_to(skill_steps.SKILLS_DIR)}: {found}"


def test_every_step_the_pipelines_name_resolves():
    named = [n for roster in rosters.PLAN_SKILL_ROSTERS.values() for n, _ in roster]
    for spec in P.PATTERNS.values():
        named += [*spec.re_skills, spec.plan_skill, *spec.modify_skills, spec.validate_skill, spec.fix_skill,
                  spec.report_skill]
    from agents.java_8_to_25.stages import INCREMENTAL_STAGES
    named += [n for st in INCREMENTAL_STAGES for n in st.extra_skills]
    missing = sorted({n for n in named if not skill_steps.exists(n)})
    assert not missing
    assert not [r for roster in rosters.PLAN_SKILL_ROSTERS.values() for r in skill_manifest.resolve(roster) if r.missing]


@pytest.mark.parametrize("migration", ["oracle-19c-to-23ai", "solr-4-to-9", "tibco-ems-to-pubsub"])
def test_the_fixer_sees_the_plan_checklist_and_the_rewrite_patterns(migration):
    """The knowledge a fix needs used to sit in the plan and modify skills only."""
    knowledge = next(line for line in skill_steps.file(f"{migration}:fix").read_text().splitlines()
                     if line.startswith("**Knowledge for this step**"))
    assert "checklist" in knowledge and "patterns" in knowledge


def test_step_names_paths_labels_and_directives():
    assert skill_steps.parse("oracle-19c-to-23ai:plan") == ("oracle-19c-to-23ai", "plan")
    assert skill_steps.parse("code-review") == ("code-review", None)
    assert skill_steps.file("oracle-19c-to-23ai:plan").relative_to(skill_steps.SKILLS_DIR).as_posix() == \
        "oracle-19c-to-23ai/references/steps/plan.md"
    assert skill_steps.file("code-review").name == "SKILL.md"
    assert skill_steps.label("solr-4-to-9:fix") == "`solr-4-to-9` › fix"
    adk = skill_steps.instruction("java-8-to-25:modify", "java-8-to-25:springboot-boot4")
    assert "`java-8-to-25` skill" in adk and "`references/steps/modify.md`" in adk
    assert "`references/steps/springboot-boot4.md`" in adk
    cli = skill_steps.cli_instruction("solr-4-to-9:validate")
    assert cli.startswith("Activate the `solr-4-to-9` skill") and "references/steps/validate.md" in cli
    assert "execute" not in skill_steps.load_only("java-8-to-11:re")
    # One toolset per agent, one skill in it however many of its steps the agent follows.
    toolset = skill_steps.toolset("java-8-to-25:modify", "java-8-to-25:springboot-boot4", "java-8-to-25:readiness")
    assert [s.name for s in toolset._list_skills()] == ["java-8-to-25"]


def test_lessons_reach_the_step_files_in_the_one_skill_folder(tmp_path):
    paths = skill_targets(tmp_path, "oracle-19c-to-23ai:modify", "oracle-19c-to-23ai:fix")({})
    assert [p.relative_to(tmp_path).as_posix() for p in paths] == [
        "oracle-19c-to-23ai/references/steps/modify.md", "oracle-19c-to-23ai/references/steps/fix.md"]


def test_inventory_only_migrations_have_no_reverse_engineering_step(monkeypatch):
    """Java 8 -> 25, Solr and Oracle analyse with the deterministic inventory only: their skills have
    no `re` step, and MIGRATION_ANALYSIS=agent does not send them looking for one."""
    import main
    from agents import config
    from agents.shared import migration_inventory
    from cli import patterns, pipeline

    monkeypatch.setattr(config, "MIGRATION_ANALYSIS", "agent")
    for m in ("java-8-to-25", "solr-4-to-9", "oracle-19c-to-23ai"):
        assert m in migration_inventory.INVENTORY_ONLY
        assert not (skill_steps.SKILLS_DIR / m / "references" / "steps" / "re.md").exists(), m
        assert "`re`" not in (skill_steps.SKILLS_DIR / m / "SKILL.md").read_text(encoding="utf-8"), m
        spec = patterns.PATTERNS[m]
        assert not spec.re_skills, m
        assert pipeline._uses_inventory(m) and main._uses_inventory(m, False), m
        assert not main._analysis_review(m), m
    assert not pipeline._uses_inventory("tibco-ems-to-pubsub")       # still has its agent
