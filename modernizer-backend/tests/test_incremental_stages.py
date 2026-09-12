"""
Pins the java-8-to-25 phased incremental strategy's wiring: which stages run
for which options and in what order, that every stage title the modifier
agents search for is what the plan skill tells the planner to emit, and that
the orchestrator emits one stage-start/stage-complete pair per executed stage,
numbered by position in the run.
"""
import asyncio
import pathlib
import re

import main
from agents import APP_NAME, PATTERN_RUNNERS, USER_ID, session_service
from agents.java_8_to_25.agents import (
    CURATED_SKILLS,
    INCREMENTAL_STAGES,
    incremental_reporter_agent,
    incremental_stages,
)

SKILLS_DIR = pathlib.Path(__file__).parent.parent / "agents" / "skills"

JAVA_17 = "Java 8 → Java 17 LTS"
BOOT_27 = "Upgrade to Spring Boot 2.7 (WAR intact)"
BOOT_3 = "Upgrade to Spring Boot 3.x (Jakarta namespace transition)"
JAVA_25 = "Java 17 → Java 25 LTS"
BOOT_4 = "Upgrade to Spring Boot 4.x"
WAR_TO_JAR = "Convert WAR → Executable JAR (Embedded Container)"


PLAN_WITH_TASKS = """# Migration Plan: Java 8 → Java 25 (Incremental)

## Stage 1: Modernize Build Systems (Maven/Gradle)

### Task 1.1: Pin the build plugin versions
- Files: `pom.xml`
- Change: pin every plugin version

### Task 1.2: Consolidate dependency versions
- Files: `pom.xml`
- Change: move versions into properties

## Stage 2: Automate Code Analysis (OpenRewrite)

### Task 2.1: Add rewrite.yml
- Files: `rewrite.yml`
- Change: declare the composite recipes

## Stage 3: Java 8 → Java 17 LTS
- No task breakdown here, so this stage runs as one pass.
"""


def _state(springboot_upgrade: bool, plan: str = "") -> dict:
    state = main._initial_state(
        "java-8-to-25", "", "", "{}", "incremental", False, springboot_upgrade,
    )
    state["plan"] = plan
    return state


def test_without_springboot_only_readiness_and_jdk_stages_run():
    stages = incremental_stages(False)
    assert [s.idx for s in stages] == [1, 2, 3, 6]
    assert [s.java_release for s in stages] == ["8", "8", "17", "25"]
    assert not any(s.springboot for s in stages)


def test_with_springboot_every_stage_runs_in_order():
    stages = incremental_stages(True)
    assert [s.idx for s in stages] == list(range(1, 9))
    assert [s.phase for s in stages] == [1, 1, 2, 2, 3, 3, 4, 4]
    assert [s.title for s in stages][2:] == [JAVA_17, BOOT_27, BOOT_3, JAVA_25, BOOT_4, WAR_TO_JAR]
    assert stages[-1].build_goal == "package"


def test_spring_boot_2_and_3_run_on_java_17_before_the_java_25_jump():
    # Spring Boot 2.7 supports Java 8-21: a Boot 2.x codebase must never meet a Java 25 release.
    by_title = {s.title: s for s in INCREMENTAL_STAGES}
    assert by_title[BOOT_27].java_release == "17"
    assert by_title[BOOT_3].java_release == "17"
    order = [s.title for s in INCREMENTAL_STAGES]
    assert order.index(BOOT_3) < order.index(JAVA_25) < order.index(BOOT_4)


def test_plan_skill_emits_every_stage_heading():
    plan_skill = (SKILLS_DIR / "java-8-to-25-plan" / "SKILL.md").read_text()
    # Full (Spring Boot) template: numbered by the stable id, since every stage runs.
    for stage in INCREMENTAL_STAGES:
        assert f"## Stage {stage.idx}: {stage.title}\n" in plan_skill, stage.title
    # Without Spring Boot the planner renumbers consecutively — the skill must spell that out.
    for position, stage in enumerate(incremental_stages(False), start=1):
        assert f"`## Stage {position}: {stage.title}`" in plan_skill, stage.title


def test_every_stage_skill_exists_and_is_curated():
    for stage in INCREMENTAL_STAGES:
        for name in stage.extra_skills:
            assert (SKILLS_DIR / name / "SKILL.md").is_file(), name
            assert name in CURATED_SKILLS, name


def test_a_runner_is_registered_per_stage():
    runners = PATTERN_RUNNERS["java-8-to-25"]
    for stage in INCREMENTAL_STAGES:
        assert f"code_stage_{stage.idx}" in runners
        # The modifier runs per task and the build loop per stage, so each half is addressable.
        assert f"code_stage_{stage.idx}_modify" in runners
        assert f"code_stage_{stage.idx}_build" in runners


def test_incremental_reporter_placeholders_are_all_initialised():
    # Skipped Spring Boot stages still need their keys, or ADK fails to render the instruction.
    state = _state(springboot_upgrade=False)
    for key in re.findall(r"\{(\w+)\}", incremental_reporter_agent.instruction):
        assert key in state, key


class _SilentRunner:
    def __init__(self, key: str, calls: list[str]):
        self._key, self._calls = key, calls

    async def run_async(self, **_kwargs):
        self._calls.append(self._key)
        return
        yield  # makes this an async generator that produces no events


def _run_incremental(monkeypatch, springboot_upgrade: bool,
                     plan: str = "") -> tuple[list[tuple[str, dict]], list[str]]:
    session = asyncio.run(session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, state=_state(springboot_upgrade, plan),
    ))
    events: list[tuple[str, dict]] = []
    calls: list[str] = []

    async def fake_push(_session_id, event_type, **kwargs):
        events.append((event_type, kwargs))

    monkeypatch.setattr(main, "_push", fake_push)
    monkeypatch.setitem(
        main.PATTERN_RUNNERS, "java-8-to-25",
        {key: _SilentRunner(key, calls) for key in PATTERN_RUNNERS["java-8-to-25"]},
    )
    asyncio.run(main._run_java8_incremental_code_step(session.id))
    return events, calls


def test_orchestrator_skips_spring_boot_stages_but_numbers_steps_consecutively(monkeypatch):
    events, calls = _run_incremental(monkeypatch, springboot_upgrade=False)
    starts = [e for t, e in events if t == "stage-start"]
    assert [e["stage"] for e in starts] == [1, 2, 3, 4]
    assert {e["total"] for e in starts} == {4}
    assert starts[3]["title"] == JAVA_25
    assert [c for c in calls if c.startswith("code_stage_")] == [
        "code_stage_1_modify", "code_stage_1_build",
        "code_stage_2_modify", "code_stage_2_build",
        "code_stage_3_modify", "code_stage_3_build",
        "code_stage_6_modify", "code_stage_6_build",
    ]


def test_each_plan_task_gets_its_own_modifier_run(monkeypatch):
    events, calls = _run_incremental(monkeypatch, springboot_upgrade=False, plan=PLAN_WITH_TASKS)

    starts = [e for t, e in events if t == "task-start"]
    assert [(e["stage"], e["task_id"]) for e in starts] == [(1, "1.1"), (1, "1.2"), (2, "2.1")]
    assert [e["task_total"] for e in starts] == [2, 2, 1]
    # Two tasks in stage 1 mean two modifier runs — each with its own fresh context — and
    # still one build loop for the finished stage.
    assert calls.count("code_stage_1_modify") == 2
    assert calls.count("code_stage_1_build") == 1
    # Stage 3 has no task blocks, so it runs as a single pass and reports no task events.
    assert calls.count("code_stage_3_modify") == 1
    assert [e for e in starts if e["stage"] == 3] == []


def test_every_task_reports_completion(monkeypatch):
    events, _calls = _run_incremental(monkeypatch, springboot_upgrade=False, plan=PLAN_WITH_TASKS)

    completes = [e for t, e in events if t == "task-complete"]
    assert [e["task_id"] for e in completes] == ["1.1", "1.2", "2.1"]


def test_orchestrator_runs_all_eight_stages_with_springboot(monkeypatch):
    events, _calls = _run_incremental(monkeypatch, springboot_upgrade=True)
    completes = [e for t, e in events if t == "stage-complete"]
    assert [e["stage"] for e in completes] == list(range(1, 9))
    assert [e["title"] for e in completes][2:] == [JAVA_17, BOOT_27, BOOT_3, JAVA_25, BOOT_4, WAR_TO_JAR]
    assert completes[3]["phase"] == 2
