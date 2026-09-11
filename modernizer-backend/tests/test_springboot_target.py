"""
Pins the Spring Boot target: whenever the Spring Boot upgrade is requested,
both strategies must end on the newest Spring Boot 4.x as an executable JAR
(never a WAR), with Spring Data JPA, Thymeleaf instead of JSP, and conflicting
libraries removed. These checks guard the skill text and agent wiring that
drive that outcome.
"""
import pathlib
import re

import pytest
from google.adk.skills import load_skill_from_dir

import main
from agents.java_8_to_25.agents import (
    INCREMENTAL_STAGES,
    fixer_agent,
    modifier_agent,
    reporter_agent,
    validator_agent,
)

SKILLS_DIR = pathlib.Path(__file__).parent.parent / "agents" / "skills"


def _read(relative: str) -> str:
    return (SKILLS_DIR / relative).read_text()


def test_boot4_skill_targets_an_executable_jar_not_a_war():
    skill = _read("springboot-war-to-boot4/SKILL.md")
    assert "Executable JAR" in skill
    assert "never a WAR" in skill
    assert "never change it to `jar`" not in skill  # the old WAR-preserving rule


def test_boot4_skill_ships_its_references():
    references = load_skill_from_dir(SKILLS_DIR / "springboot-war-to-boot4").resources.references
    assert set(references) >= {
        "boot4-dependency-cleanup.md", "spring-data-jpa-migration.md", "jsp-to-thymeleaf.md",
        "war-to-executable-jar.md", "jakarta-ee11-namespace-map.md", "webxml-to-javaconfig.md",
    }
    assert "war-packaging-and-lifecycle.md" not in references


def test_incremental_skill_keeps_only_its_intermediate_war_rules():
    references = load_skill_from_dir(SKILLS_DIR / "springboot-incremental-upgrade").resources.references
    assert "intermediate-war-stages.md" in references
    assert "war-to-executable-jar.md" not in references  # moved to springboot-war-to-boot4


@pytest.mark.parametrize("relative", [
    "java-8-to-25-plan/SKILL.md",
    "java-8-to-25-plan/references/java8-to-java25-checklist.md",
])
def test_plan_no_longer_offers_a_war_path(relative):
    text = _read(relative)
    assert "Path A" not in text and "Path B" not in text
    assert "Spring Boot 4" in text and "executable JAR" in text


def test_no_skill_falls_back_to_an_executable_war():
    for path in SKILLS_DIR.rglob("*.md"):
        text = path.read_text()
        assert "executable-WAR fallback" not in text, path
        assert "plan an executable WAR instead" not in text, path


def test_last_incremental_stage_packages_a_jar_with_the_boot4_skill():
    last = INCREMENTAL_STAGES[-1]
    assert "Executable JAR" in last.title
    assert last.build_goal == "package"
    assert "springboot-war-to-boot4" in last.extra_skills


def test_bigbang_validator_packages_the_jar_when_spring_boot_is_upgraded():
    assert "{springboot_upgrade}" in validator_agent.instruction
    assert "package" in validator_agent.instruction


def test_bigbang_agent_placeholders_are_all_initialised():
    state = main._initial_state("java-8-to-25", "", "", "{}", "bigbang", False, True)
    for agent in (modifier_agent, validator_agent, fixer_agent, reporter_agent):
        for key in re.findall(r"\{(\w+)\}", agent.instruction):
            assert key in state, f"{agent.name}: {key}"
