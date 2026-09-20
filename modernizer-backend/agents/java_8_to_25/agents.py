"""
Java 8 -> Java 25 agent pipeline — tool-driven re/planner/modifier/
build-loop/reporter architecture operating on a real per-session workspace
directory (see main.py's upload handler, which sets session
state["workspace_dir"]) via agents/java_8_to_25/tools.py.

Two migration strategies, chosen by the user before upload
(session state["migration_strategy"]):

  bigbang     -- one modifier pass straight to Java 25, then one
                 build_loop(validate mvn compile, fix), like a single big
                 jump. Pipeline: `code_pipeline_bigbang`.

  incremental -- up to eight *true* staged passes grouped into four phases
                 (see INCREMENTAL_STAGES), each with its own build_loop,
                 executed strictly in order:
                   Phase 1 Readiness:         build-system modernisation, OpenRewrite
                   Phase 2 Java 17 Baseline:  Java 8 -> 17, Spring Boot 2.7 (WAR, javax)
                   Phase 3 Java 25 Baseline:  Spring Boot 3.x (WAR, jakarta), Java 17 -> 25
                   Phase 4 Boot 4:            Spring Boot 4.x (WAR), WAR -> executable JAR
                 The Spring Boot stages only run when a Spring Boot upgrade
                 was requested. The framework always moves to a version that
                 supports the next JDK *before* that JDK upgrade runs (Spring
                 Boot 2.7 tops out at Java 21), so every stage lands on a
                 supported JDK/framework combination.
                 Each stage only ever modifies/validates/fixes the slice of
                 the confirmed plan under its own "## Stage <n>: <title>" heading.
                 ADK agent instances can only belong to one parent, so each
                 stage gets its own modifier/validator/fixer/build_loop
                 instances (`_make_stage`) rather than reusing one set of
                 agents per stage. Exposed as `STAGE_PIPELINES` (registered
                 individually in agents/__init__.py as code_stage_1..code_stage_8)
                 plus a shared `reporter_agent` for the bigbang path and
                 `incremental_reporter_agent` for the incremental path (it
                 reasons over every stage's results, so it cannot reuse the
                 single-stage reporter's instruction).

Both strategies share the same `re_agent` (reverse-engineering: explores the
workspace and produces Analysis + BRD + Technical Specification + Existing
Test Inventory) and `planner_agent` (produces the confirmed Plan from the
BRD/TechSpec, strategy/JUnit/Spring-Boot-aware).

Skills (Pattern 2 -- file-based):
  Each agent loads its instructions and reference material from
  agents/skills/<skill-name>/ at runtime via SkillToolset.
"""
import os
import pathlib
from dataclasses import dataclass

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.skills import load_skill_from_dir
from google.adk.tools import FunctionTool
from google.adk.tools.skill_toolset import SkillToolset

from .. import config
from ..shared.callbacks import make_skill_update_callback
from ..shared import skill_manifest
from ..shared.plan_contract import make_plan_contract_callback
from ..shared.review_and_curate import make_code_reviewer_agent, make_skill_curator_agent
from . import tools as fs_tools

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "skills"



@dataclass(frozen=True)
class IncrementalStage:
    """One staged modifier+build_loop pass of the "incremental" strategy."""
    # Stable id (runner key, agent names, state keys). The step number users and the
    # plan see is the stage's position in the run, which differs when Spring Boot
    # stages are skipped -- so the plan section is matched by `title`, not by number.
    idx: int
    phase: int
    phase_title: str
    title: str
    # Compiler release level the build must target once this stage is applied.
    java_release: str
    # Framework stage: only runs when the user requested a Spring Boot upgrade.
    springboot: bool
    # Skills this stage's modifier loads alongside java-8-to-25-modify.
    extra_skills: tuple[str, ...]
    # What this stage must NOT do yet -- later stages own those changes.
    guardrail: str
    # Build goal the validator runs ("compile", or "package" when the artifact itself changes).
    build_goal: str = "compile"


_KEEP_FRAMEWORK = (
    "Do not change the Spring / Spring Boot version, the `javax`/`jakarta` namespace, or the "
    "packaging — those belong to the Spring Boot stages (when requested)."
)

# Same rule for the JDK stages, minus the Spring Framework version: see _SPRING_FLOOR_* below.
_KEEP_BOOT = (
    "Do not change the Spring Boot version or the packaging, and do not rename Jakarta EE `javax.*` "
    "packages — those belong to the Spring Boot stages (when requested)."
)

# A JDK stage cannot leave the framework behind: old Spring/Hibernate lines bundle an ASM that
# refuses newer class files, so they fail at context startup on the JDK this stage targets rather
# than at compile time. Each JDK stage therefore owns the framework floor its release requires.
_SPRING_FLOOR_17 = (
    "The one framework change this stage owns: if the app is on plain Spring Framework 3.x/4.x, "
    "raise every `org.springframework:spring-*` artifact to the newest 5.3.x (still `javax`, "
    "supports Java 8-21) — older Spring cannot read Java 17 class files — and rewrite "
    "`org.springframework.orm.hibernate3.*` (removed in Spring 5) onto `hibernate5` alongside a "
    "Hibernate 5.6.x bump. Never go past Spring 5.3 here."
)
_SPRING_FLOOR_25 = (
    "The one framework change this stage owns: if the app is still on plain Spring Framework 5.3 "
    "because no Spring Boot upgrade was requested, raise it to Spring 6.x — 5.3 does not support "
    "Java 25 — which forces the Jakarta EE `javax.*` → `jakarta.*` rename in this stage (never the "
    "Java SE `javax.sql`, `javax.naming`, `javax.crypto` or JAXP packages). If the app is already "
    "Spring Boot-managed, leave the framework version alone."
)

# The "incremental" strategy, in strict order. JDK and Spring Boot stages interleave so
# every stage lands on a supported combination: Spring Boot 2.7 (Java 8-21) and 3.x
# (Java 17+) are done on Java 17, before the Java 25 jump; Spring Boot 4 comes after it.
INCREMENTAL_STAGES: list[IncrementalStage] = [
    IncrementalStage(
        1, 1, "Readiness", "Modernize Build Systems (Maven/Gradle)", "8", False,
        ("java-migration-readiness",),
        "Keep the compiler release at 8 and do not touch application source code. Test-scoped "
        "dependencies and the test plugins are the one exception: the test stack (Mockito 1.x → "
        "`mockito-core` 4.11.0, JUnit 4.13.2, surefire/failsafe 3.2.5+) is modernised here as the "
        "migration's safety net. " + _KEEP_FRAMEWORK,
    ),
    IncrementalStage(
        2, 1, "Readiness", "Automate Code Analysis (OpenRewrite)", "8", False,
        ("java-migration-readiness",),
        "Only add OpenRewrite configuration — never wire it to run during the normal build, and do not "
        "apply recipe changes to source files, change the compiler release, or touch application code.",
    ),
    IncrementalStage(
        3, 2, "Java 17 Baseline", "Java 8 → Java 17 LTS", "17", False, (),
        "Set the compiler release to exactly 17, not further. " + _KEEP_BOOT + " " + _SPRING_FLOOR_17,
    ),
    IncrementalStage(
        4, 2, "Java 17 Baseline", "Upgrade to Spring Boot 2.7 (WAR intact)", "17", True,
        ("springboot-incremental-upgrade",),
        "Keep the compiler release at 17, keep `<packaging>war</packaging>`, and keep every `javax.*` "
        "import (Spring Boot 2.7 is still Java EE 8 / javax based) — the jakarta transition is the "
        "next Spring Boot stage.",
    ),
    IncrementalStage(
        5, 3, "Java 25 Baseline", "Upgrade to Spring Boot 3.x (Jakarta namespace transition)", "17", True,
        ("springboot-incremental-upgrade",),
        "Keep the compiler release at 17 (the Java 25 upgrade is the next stage), keep "
        "`<packaging>war</packaging>`, and stay on Spring Boot 3.x — Spring Boot 4 is a later stage. "
        "Never rename Java SE `javax.*` packages (`javax.sql`, `javax.naming`, `javax.crypto`, ...).",
    ),
    IncrementalStage(
        6, 3, "Java 25 Baseline", "Java 17 → Java 25 LTS", "25", False, (),
        "Set the compiler release to exactly 25. " + _KEEP_BOOT + " " + _SPRING_FLOOR_25,
    ),
    IncrementalStage(
        7, 4, "Spring Boot 4 & Cloud Native", "Upgrade to Spring Boot 4.x", "25", True,
        ("springboot-war-to-boot4", "springboot-incremental-upgrade"),
        "Keep `<packaging>war</packaging>` and the JSP views (with their JSP libraries) in this stage — "
        "the executable JAR conversion and JSP → Thymeleaf are the next stage.",
    ),
    IncrementalStage(
        8, 4, "Spring Boot 4 & Cloud Native", "Convert WAR → Executable JAR (Embedded Container)", "25", True,
        ("springboot-war-to-boot4", "springboot-incremental-upgrade"),
        "Do not change the Java or Spring Boot versions — this stage only changes the packaging and "
        "deployment model and converts JSP views to Thymeleaf. The result must be an executable JAR, "
        "never a WAR.",
        build_goal="package",
    ),
]


def incremental_stages(springboot_upgrade: bool) -> list[IncrementalStage]:
    """The stages an incremental run actually executes for this session's options, in
    order. A stage's displayed step number is its 1-based position in this list."""
    return [s for s in INCREMENTAL_STAGES if springboot_upgrade or not s.springboot]


def _skill(name: str) -> SkillToolset:
    return SkillToolset(skills=[load_skill_from_dir(_SKILLS_DIR / name)])


def _skills(*names: str) -> SkillToolset:
    """One SkillToolset covering multiple skills. Required whenever an agent
    needs more than one skill available (e.g. modifier_agent needs both
    java-8-to-25-modify and springboot-war-to-boot4): SkillToolset always
    exposes fixed tool names (list_skills/load_skill/...), so giving one
    agent two SEPARATE SkillToolset instances declares those names twice and
    Gemini rejects the request with "Duplicate function declaration found:
    list_skills". A single toolset holding both skills exposes each name
    exactly once and lets the model load_skill either one by name."""
    return SkillToolset(skills=[load_skill_from_dir(_SKILLS_DIR / name) for name in names])


# ── re_agent: explores the real workspace, produces Analysis/BRD/TechSpec/Tests ──
re_agent = LlmAgent(
    name="java8_re",
    model=_MODEL,
    description="Reverse-engineers a Java 8 repository workspace via list_files/read_file and produces Analysis, BRD, Technical Specification, and an Existing Test Inventory.",
    instruction="Load and execute the `java-8-to-25-re` skill, using the list_files and read_file tools to explore the workspace.",
    tools=[_skill("java-8-to-25-re"), FunctionTool(fs_tools.list_files), FunctionTool(fs_tools.read_file)],
    output_key="analysis",
    include_contents="none",
)

# ── planner_agent: pure reasoning over the confirmed BRD/TechSpec ──────────────

# The plan's Skill Composition section, computed from each SKILL.md's frontmatter
# rather than left to the model: the planner cannot see the roster, the order or
# the versions, so a table it wrote itself would be invented. Roles say when a row
# applies, and the planner drops the ones this run does not use.
_PLAN_SKILL_ROSTER: list[tuple[str, str]] = [
    ("java-8-to-25-re", "Reverse-engineered this repository into the confirmed BRD, Technical Specification and Test Inventory"),
    ("java-8-to-25-plan", "Produces this plan"),
    ("java-migration-readiness", "Incremental only — Stages 1-2: build modernisation, the test-stack safety net and OpenRewrite setup"),
    ("springboot-incremental-upgrade", "Incremental only, and only when a Spring Boot upgrade was requested — Stages 4-5: Spring Boot 2.7, then 3.x with the Jakarta rename"),
    ("springboot-war-to-boot4", "Only when a Spring Boot upgrade was requested — the Spring Boot 4.x target and the WAR to executable-JAR conversion"),
    ("java-8-to-25-modify", "Applies each task's file changes to the workspace"),
    ("java-8-to-25-validate", "Compiles (and packages) the workspace after each stage"),
    ("java-8-to-25-fix", "Repairs build errors inside the build loop"),
    ("code-review", "Independent review of the result against this plan's manifest"),
    ("java-8-to-25-report", "Produces the final migration report"),
]

planner_agent = LlmAgent(
    name="java8_plan",
    model=_MODEL,
    description="Creates a detailed, strategy-aware Java 8 -> Java 25 migration plan from the confirmed BRD and Technical Specification.",
    instruction=(
        "Load and execute the `java-8-to-25-plan` skill to create the migration plan.\n\n"
        + skill_manifest.planner_block(_PLAN_SKILL_ROSTER)
        + "\n\n## Migration Strategy\n{migration_strategy}\n\n"
        "## JUnit Upgrade Requested\n{junit_upgrade}\n\n"
        "## Spring Boot Upgrade Requested\n{springboot_upgrade}\n\n"
        "## Confirmed Business Requirements Document\n{brd}\n\n"
        "## Confirmed Technical Specification\n{technical_spec}\n\n"
        "## Existing Test Inventory\n{test_inventory}\n\n"
        "The Test Inventory is what question 4 is answered from — its Coverage Gaps section is the "
        "starting point for the plan's own, never a substitute for it."
    ),
    tools=[_skill("java-8-to-25-plan")],
    output_key="plan",
    after_agent_callback=make_plan_contract_callback(),
    include_contents="none",
)

# ── bigbang code path: one modifier -> one build_loop -> one reporter ──────────
modifier_agent = LlmAgent(
    name="modifier_agent",
    model=_MODEL,
    description="Applies the confirmed migration plan to the workspace, reading and rewriting files in place via read_file/write_file.",
    instruction=(
        "Load and execute the `java-8-to-25-modify` skill to apply the confirmed migration plan "
        "to the files in the workspace, using the list_files, read_file and write_file tools. "
        "Spring Boot upgrade requested: {springboot_upgrade}. If true, also load and follow the "
        "`springboot-war-to-boot4` skill for the plan's Spring Boot 4 Target section — the final state is "
        "the newest Spring Boot 4.x as an executable JAR on an embedded Tomcat (never a WAR), with "
        "Spring Data JPA, Thymeleaf instead of JSP, and every conflicting legacy library removed. It "
        "supersedes the base skill's generic Spring Boot guidance.\n\n"
        "## Confirmed Migration Plan\n{plan}"
    ),
    tools=[
        _skills("java-8-to-25-modify", "springboot-war-to-boot4"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
        FunctionTool(fs_tools.replace_in_file),
        FunctionTool(fs_tools.write_file),
    ],
    output_key="modify_result",
    include_contents="none",
)

validator_agent = LlmAgent(
    name="validator_agent",
    model=_MODEL,
    description="Runs the real build (mvn/gradle compile) against the modified workspace and reports pass/fail as JSON.",
    instruction=(
        "Load and execute the `java-8-to-25-validate` skill to build the workspace and report the result.\n\n"
        "Spring Boot upgrade requested: {springboot_upgrade}. If true, run the `package` goal instead of "
        "`compile` (`mvn -q -DskipTests package`, or `./gradlew assemble` for Gradle) so the executable "
        "Spring Boot JAR is actually produced — a failed repackage is a failed build."
    ),
    tools=[
        _skill("java-8-to-25-validate"),
        FunctionTool(fs_tools.run_command),
        FunctionTool(fs_tools.signal_build_success),
    ],
    output_key="build_result",
    include_contents="none",
    after_agent_callback=make_skill_update_callback(
        validation_key="build_result",
        skill_md_path=_SKILLS_DIR / "java-8-to-25-validate" / "SKILL.md",
        section_header="Validation Pass",
    ),
)

fixer_agent = LlmAgent(
    name="fixer_agent",
    model=_MODEL,
    description="Reads the files implicated by validator_agent's build report and fixes them in place in the workspace.",
    instruction=(
        "Load and execute the `java-8-to-25-fix` skill. For errors caused by the Spring Boot 4 migration "
        "(dependencies, Jakarta namespace, Spring Data JPA, Thymeleaf, executable JAR packaging), also "
        "load the `springboot-war-to-boot4` skill — fix within its target state, never by reverting to "
        "a WAR or re-adding a removed conflicting library.\n\n"
        "## Build Report (errors to fix)\n{build_result}"
    ),
    tools=[
        _skills("java-8-to-25-fix", "springboot-war-to-boot4"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
        FunctionTool(fs_tools.replace_in_file),
        FunctionTool(fs_tools.write_file),
    ],
    output_key="fix_result",
    include_contents="none",
    after_agent_callback=make_skill_update_callback(
        validation_key="build_result",
        skill_md_path=_SKILLS_DIR / "java-8-to-25-fix" / "SKILL.md",
        section_header="Fix Pass",
    ),
)

build_loop = LoopAgent(
    name="build_loop",
    description="Iteratively builds and fixes the migrated workspace (configurable max iterations).",
    sub_agents=[validator_agent, fixer_agent],
    max_iterations=config.BUILD_LOOP_MAX_ITERATIONS,
)

# Skills the skill-curator agent may refine for this pattern (bigbang and incremental alike).
CURATED_SKILLS: list[str] = [
    "java-8-to-25-re", "java-8-to-25-plan", "java-8-to-25-modify",
    "java-8-to-25-validate", "java-8-to-25-fix", "java-8-to-25-report",
    "springboot-war-to-boot4", "java-migration-readiness", "springboot-incremental-upgrade",
]

code_reviewer_agent = make_code_reviewer_agent(
    _MODEL,
    FunctionTool(fs_tools.list_files),
    FunctionTool(fs_tools.read_file),
    context_instruction="## Confirmed Migration Plan\n{plan}\n\n## Final Build Result\n{build_result}",
)

reporter_agent = LlmAgent(
    name="reporter_agent",
    model=_MODEL,
    description="Summarises the bigbang migration run -- what changed, final build status, and any remaining issues.",
    instruction=(
        "Load and execute the `java-8-to-25-report` skill to produce the final migration report. Fold "
        "the Independent Code Review's findings into a dedicated report section rather than ignoring "
        "them.\n\n"
        "## Modify Result\n{modify_result}\n\n"
        "## Final Build Result\n{build_result}\n\n"
        "## Independent Code Review\n{code_review}"
    ),
    tools=[_skill("java-8-to-25-report")],
    output_key="final_report",
    include_contents="none",
)

skill_curator_agent = make_skill_curator_agent(
    _MODEL,
    allowed_skills=CURATED_SKILLS,
    context_instruction=(
        "## Confirmed Migration Plan\n{plan}\n\n## Modify Result\n{modify_result}\n\n"
        "## Final Build Result\n{build_result}\n\n## Independent Code Review\n{code_review}"
    ),
)

code_pipeline_bigbang = SequentialAgent(
    name="java8_code_pipeline_bigbang",
    description="Applies the full Java 8 -> 25 migration plan in one pass, builds/fixes in a loop, reviews and reports the outcome, then curates the skill library.",
    sub_agents=[modifier_agent, build_loop, code_reviewer_agent, reporter_agent, skill_curator_agent],
)


# ── incremental code path: staged modifier+build_loop passes (INCREMENTAL_STAGES) ──

def _make_stage(stage: IncrementalStage) -> SequentialAgent:
    idx = stage.idx
    stage_label = stage.title
    phase_label = f"Phase {stage.phase} ({stage.phase_title})"

    skills_note = ""
    if stage.extra_skills:
        names = " and ".join(f"`{name}`" for name in stage.extra_skills)
        skills_note = (
            f"Also load and follow the {names} skill{'s' if len(stage.extra_skills) > 1 else ''} — use "
            f"the part covering '{stage.title}'; it governs how this stage's changes are made and "
            "supersedes the base skill's generic guidance for this stage.\n\n"
        )

    modifier = LlmAgent(
        name=f"modifier_stage{idx}",
        model=_MODEL,
        description=f"Applies ONLY the {stage_label} portion of the confirmed migration plan to the workspace.",
        instruction=(
            "Load and execute the `java-8-to-25-modify` skill and apply ONLY the work described under "
            "'## Your Task' below. It is one task of the "
            f"'{stage_label}' stage; earlier tasks and stages are already applied to the workspace, and "
            "the remaining ones run as separate passes — do not do their work, and do not re-do work "
            "that is already in place. Use the list_files, read_file, replace_in_file and write_file "
            "tools, preferring replace_in_file for edits to existing files.\n\n"
            f"This is {phase_label} of an incremental migration. After this stage the build's compiler "
            "release level (`maven.compiler.release` / `sourceCompatibility` / `targetCompatibility` / "
            f"toolchain) must be exactly {stage.java_release}.\n\n"
            f"Guardrail for this stage: {stage.guardrail}\n\n"
            + skills_note
            + "## Your Task\n{current_task}"
        ),
        tools=[
            _skills("java-8-to-25-modify", *stage.extra_skills),
            FunctionTool(fs_tools.list_files),
            FunctionTool(fs_tools.read_file),
            FunctionTool(fs_tools.replace_in_file),
            FunctionTool(fs_tools.write_file),
        ],
        output_key=f"modify_result_stage{idx}",
        include_contents="none",
    )

    goal_note = ""
    if stage.build_goal == "package":
        goal_note = (
            " For this stage run the `package` goal instead of `compile` (`mvn -q -DskipTests package`, "
            "or `./gradlew assemble` for Gradle) so the new executable artifact is actually produced — "
            "a failed repackage is a failed build."
        )

    validator = LlmAgent(
        name=f"validator_stage{idx}",
        model=_MODEL,
        description=f"Runs the real build against the workspace after {stage_label} and reports pass/fail as JSON.",
        instruction=(
            "Load and execute the `java-8-to-25-validate` skill to build the workspace and report the "
            f"result. This is validating the '{stage_label}' stage ({phase_label}) of an incremental migration -- "
            f"the build should target Java {stage.java_release}." + goal_note
        ),
        tools=[
            _skill("java-8-to-25-validate"),
            FunctionTool(fs_tools.run_command),
            FunctionTool(fs_tools.signal_build_success),
        ],
        output_key=f"build_result_stage{idx}",
        include_contents="none",
        after_agent_callback=make_skill_update_callback(
            validation_key=f"build_result_stage{idx}",
            skill_md_path=_SKILLS_DIR / "java-8-to-25-validate" / "SKILL.md",
            section_header=f"Validation Pass — {stage.title}",
        ),
    )

    fixer = LlmAgent(
        name=f"fixer_stage{idx}",
        model=_MODEL,
        description=f"Fixes build errors reported for {stage_label}.",
        instruction=(
            "Load and execute the `java-8-to-25-fix` skill.\n\n"
            f"You are fixing the '{stage_label}' stage ({phase_label}) of an incremental migration. Fix the reported "
            f"errors without advancing the migration past this stage. {stage.guardrail}\n\n"
            f"## Build Report for {stage_label} (errors to fix)\n{{build_result_stage{idx}}}"
        ),
        tools=[
            _skills("java-8-to-25-fix", *stage.extra_skills),
            FunctionTool(fs_tools.list_files),
            FunctionTool(fs_tools.read_file),
            FunctionTool(fs_tools.replace_in_file),
            FunctionTool(fs_tools.write_file),
        ],
        output_key=f"fix_result_stage{idx}",
        include_contents="none",
        after_agent_callback=make_skill_update_callback(
            validation_key=f"build_result_stage{idx}",
            skill_md_path=_SKILLS_DIR / "java-8-to-25-fix" / "SKILL.md",
            section_header=f"Fix Pass — {stage.title}",
        ),
    )

    stage_loop = LoopAgent(
        name=f"build_loop_stage{idx}",
        description=f"Iteratively builds and fixes the workspace for {stage_label} (configurable max iterations).",
        sub_agents=[validator, fixer],
        max_iterations=config.BUILD_LOOP_MAX_ITERATIONS,
    )

    return SequentialAgent(
        name=f"stage{idx}_pipeline",
        description=f"Applies and validates {stage_label}.",
        sub_agents=[modifier, stage_loop],
    )


STAGE_PIPELINES: list[SequentialAgent] = [_make_stage(stage) for stage in INCREMENTAL_STAGES]

# main.py drives the two halves of a stage separately: the modifier runs once per plan task
# (a fresh context each time), then the build loop runs once over the finished stage.
STAGE_MODIFIERS: list[LlmAgent] = [pipeline.sub_agents[0] for pipeline in STAGE_PIPELINES]
STAGE_BUILD_LOOPS: list[LoopAgent] = [pipeline.sub_agents[1] for pipeline in STAGE_PIPELINES]

_incremental_stage_results = (
    "Stages are listed in execution order. Stages whose Modify Result and Final Build Result are "
    "both empty were not run — the Spring Boot stages only run when a Spring Boot upgrade was "
    "requested. Treat them as skipped, not failed.\n\n"
    + "\n\n".join(
        f"## {stage.title} [Phase {stage.phase}: {stage.phase_title}] — Modify Result\n"
        f"{{modify_result_stage{stage.idx}}}\n\n"
        f"## {stage.title} — Final Build Result\n{{build_result_stage{stage.idx}}}"
        for stage in INCREMENTAL_STAGES
    )
)

incremental_code_reviewer_agent = make_code_reviewer_agent(
    _MODEL,
    FunctionTool(fs_tools.list_files),
    FunctionTool(fs_tools.read_file),
    context_instruction=(
        "This is the FULL final codebase after every incremental stage completed — review it as one "
        "whole, not stage by stage.\n\n"
        "## Confirmed Migration Plan (all stages)\n{plan}\n\n" + _incremental_stage_results
    ),
)

incremental_reporter_agent = LlmAgent(
    name="incremental_reporter_agent",
    model=_MODEL,
    description="Summarises a full phased incremental migration run (Java 8 -> 17 -> 25, with optional Spring Boot 2.7 -> 3 -> 4 -> JAR stages interleaved) across all of its stages.",
    instruction=(
        "Load and execute the `java-8-to-25-report` skill to produce the final migration report, covering "
        "every stage of this phased incremental migration. Fold the Independent Code Review's "
        "findings into a dedicated report section rather than ignoring them.\n\n"
        + _incremental_stage_results
        + "\n\n## Independent Code Review (of the final codebase, across all stages)\n{code_review}"
    ),
    tools=[_skill("java-8-to-25-report")],
    output_key="final_report",
    include_contents="none",
)

incremental_skill_curator_agent = make_skill_curator_agent(
    _MODEL,
    allowed_skills=CURATED_SKILLS,
    context_instruction=(
        "## Confirmed Migration Plan (all stages)\n{plan}\n\n"
        + _incremental_stage_results
        + "\n\n## Independent Code Review (of the final codebase, across all stages)\n{code_review}"
    ),
)
