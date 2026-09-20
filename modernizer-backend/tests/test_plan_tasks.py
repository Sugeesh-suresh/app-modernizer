"""
Parsing a confirmed plan into per-stage tasks. The plan is user-editable in
the review screen, so the parser has to be forgiving: anything it cannot read
falls back to running the whole stage in one pass.
"""
from agents.shared import plan_tasks

PLAN = """# Migration Plan: Java 8 → Java 25 (Incremental)

## Overview
Current state and roadmap.

## Phase 1: Readiness
Goal: a reproducible build.

## Stage 1: Modernize Build Systems (Maven/Gradle)

### Task 1.1: Pin the build plugin versions
- Files: `pom.xml`
- Depends on: none
- Change: pin maven-compiler-plugin and maven-war-plugin
- Done when: no plugin is declared without a version

### Task 1.2: Consolidate dependency versions
- Files: `pom.xml`, `parent/pom.xml`
- Change: move hard-coded versions into properties

## Stage 3: Java 8 → Java 17 LTS

### Task 3.1: Bump the compiler release
- Files: pom.xml
- Change: set maven.compiler.release to 17
"""


def test_stage_section_is_found_by_title_not_number():
    section = plan_tasks.stage_section(PLAN, "Java 8 → Java 17 LTS")

    assert "Task 3.1" in section
    # The section must stop before the next "## " heading.
    assert "Task 1.1" not in section


def test_stage_section_tolerates_different_dashes_and_spacing():
    assert plan_tasks.stage_section(PLAN, "Java 8 - Java 17  LTS")


def test_stage_section_is_empty_when_the_stage_is_missing():
    assert plan_tasks.stage_section(PLAN, "Convert WAR → Executable JAR") == ""


def test_parse_tasks_reads_id_title_files_and_body():
    tasks = plan_tasks.parse_tasks(plan_tasks.stage_section(PLAN, "Modernize Build Systems (Maven/Gradle)"))

    assert [t.id for t in tasks] == ["1.1", "1.2"]
    assert tasks[0].title == "Pin the build plugin versions"
    assert tasks[0].files == ["pom.xml"]
    assert tasks[1].files == ["pom.xml", "parent/pom.xml"]
    # The body is what the modifier is given, so it must carry the task's instructions.
    assert "maven-compiler-plugin" in tasks[0].body
    assert "Task 1.2" not in tasks[0].body


def test_parse_tasks_reads_an_unbackticked_file_list():
    tasks = plan_tasks.parse_tasks(plan_tasks.stage_section(PLAN, "Java 8 → Java 17 LTS"))

    assert tasks[0].files == ["pom.xml"]


def test_stage_units_returns_the_plan_tasks_when_there_are_any():
    units, from_plan = plan_tasks.stage_units(PLAN, "Modernize Build Systems (Maven/Gradle)")

    assert from_plan is True
    assert [u.id for u in units] == ["1.1", "1.2"]


def test_stage_units_falls_back_to_the_whole_stage_without_task_blocks():
    plan = "## Stage 1: Modernize Build Systems (Maven/Gradle)\n- Pin plugin versions\n"

    units, from_plan = plan_tasks.stage_units(plan, "Modernize Build Systems (Maven/Gradle)")

    assert from_plan is False
    assert len(units) == 1
    assert "Pin plugin versions" in units[0].body


def test_stage_units_returns_nothing_when_the_stage_heading_is_missing():
    """It used to fall back to the WHOLE PLAN, so a stage the planner omitted
    handed its modifier every other stage's instructions to apply under this
    stage's guardrail — a silent, repo-wide scope explosion. A stage with no
    section is skipped by the caller instead."""
    plan = "## Stage 1: Modernize Build Systems (Maven/Gradle)\nJust build files.\n"

    units, from_plan = plan_tasks.stage_units(plan, "Java 17 → Java 25 LTS")

    assert units == []
    assert from_plan is False


def test_stage_units_still_falls_back_within_a_section_that_has_no_tasks():
    """A hand-edited plan whose stage section is real but has no `### Task`
    blocks must still run — as one whole-section pass, scoped to that section."""
    plan = (
        "## Stage 1: Modernize Build Systems (Maven/Gradle)\nOnly build files.\n\n"
        "## Stage 3: Java 8 → Java 17 LTS\nRaise Spring to 5.3.\n"
    )

    units, from_plan = plan_tasks.stage_units(plan, "Modernize Build Systems (Maven/Gradle)")

    assert len(units) == 1 and from_plan is False
    assert "Only build files." in units[0].body
    # Scoped to its own section — never the next stage's content.
    assert "Raise Spring to 5.3" not in units[0].body
