"""
Java 8 -> Java 11 agent pipeline for large JSP + WildFly monoliths.

A JDK upgrade and nothing else. The application keeps its JSP views, its WAR
packaging, its `javax.*` Java EE namespace and its WildFly deployment exactly
as uploaded; only `.java` sources and build files change, and only as far as
Java 11 requires -- the compiler release, the JDK 11 blockers in the code
(APIs removed from the JDK, Java EE modules dropped from it), and the
libraries and build plugins that cannot build or run on JDK 11.

That scope is enforced, not requested. The modifier and fixer hold the
fenced `write_file` / `replace_in_file` from agents/java_8_to_11/tools.py,
the validator's `signal_build_success` refuses to end the loop while
`check_java11_invariants` fails, and main.py restores every frozen file from
the baseline before the diff (agents/shared/scope_fence.py).

Shape: re -> HITL -> plan -> HITL -> per-task modifier runs -> one
build_loop(validate, fix) -> code review -> report -> skill curation.

The modifier is registered on its own (`code_modify`) and main.py runs it
once per `### Task` block of the plan's single `## Stage 1: Java 8 → Java 11`
section (agents/shared/plan_tasks.py), each run with a fresh context holding
only that task's files. A large monolith applied in one pass would accumulate
every file it touched in one context. `code_finish` then builds, fixes,
reviews, reports and curates once, over the finished workspace -- see
main.py's _run_java11_code_step.
"""
import pathlib

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.skills import load_skill_from_dir
from google.adk.tools import FunctionTool
from google.adk.tools.skill_toolset import SkillToolset

from .. import config
from ..shared.model_config import make_model
from ..shared import skill_manifest
from ..shared.callbacks import make_skill_update_callback
from ..shared.learned_fixes import (
    jsp_targets, make_lesson_capture_callback, make_lesson_verify_callback, skill_targets,
)
from ..shared.plan_contract import make_plan_contract_callback
from ..shared.review_and_curate import make_code_reviewer_agent, make_skill_curator_agent
from . import tools as fs_tools

_MODEL = make_model()
_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "skills"

#: The plan's one stage heading. main.py splits the plan into tasks under it, so
#: the planner skill must emit this title character for character.
STAGE_TITLE = "Java 8 → Java 11"

#: The rules every writing agent is held to, stated once so the modifier and the
#: fixer cannot drift apart. The tools enforce them regardless; stating them
#: saves the agent the refused call.
FENCE_RULES = (
    "Scope fence — enforced by your write tools, which refuse anything outside it:\n"
    "- Only `.java` sources and build files (pom.xml, build.gradle[.kts], settings.gradle, "
    "gradle.properties, Maven/Gradle wrapper properties) may change.\n"
    "- JSP (.jsp/.jspf/.tag/.tld), everything under src/main/webapp, WEB-INF and META-INF, web.xml, "
    "every WildFly/JBoss descriptor (jboss-*.xml, standalone*.xml, *-ds.xml, module.xml, *.cli) and "
    "container launch configuration (standalone.conf, Dockerfile) are FROZEN.\n"
    "- In build files: `<packaging>`, `<finalName>`, WildFly/JBoss deployment plugins and the "
    "maven-war-plugin configuration stay exactly as they are (the WAR plugin's version alone may "
    "move); the Java level is exactly 11, never higher; Spring Boot is never introduced.\n"
    "- The Java EE namespace stays `javax.*` — never add a `jakarta.*` import.\n"
    "- A dependency the WildFly container supplies (scope `provided`, or listed in "
    "jboss-deployment-structure.xml) keeps its version: WildFly supplies it at runtime, not the WAR.\n"
    "If the Java 11 upgrade genuinely cannot be completed inside the fence, stop and say exactly "
    "what and why in your summary — never work around a refusal."
)


def _skill(name: str) -> SkillToolset:
    return SkillToolset(skills=[load_skill_from_dir(_SKILLS_DIR / name)])


def _skills(*names: str) -> SkillToolset:
    """One SkillToolset for several skills — two separate toolsets would declare
    list_skills/load_skill twice, which Gemini rejects."""
    return SkillToolset(skills=[load_skill_from_dir(_SKILLS_DIR / name) for name in names])


def _writing_tools() -> list:
    return [
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
        FunctionTool(fs_tools.replace_in_file),
        FunctionTool(fs_tools.write_file),
    ]


# ── re_agent: explores the real workspace, produces Analysis/BRD/TechSpec/Tests ──
re_agent = LlmAgent(
    name="java11_re",
    model=_MODEL,
    description="Reverse-engineers a Java 8 JSP/WildFly monolith for a Java 11 upgrade and produces Analysis, BRD, Technical Specification, and an Existing Test Inventory.",
    instruction=(
        "Load and execute the `java-8-to-11-re` skill, using the list_files, search_files and read_file "
        "tools to explore the workspace. Use search_files to find where an API, import or setting is "
        "used across the repository, then read_file to understand the hits. These tools are the only "
        "way to inspect the code: nothing in this environment executes code."
    ),
    tools=[
        _skill("java-8-to-11-re"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.search_files),
        FunctionTool(fs_tools.read_file),
    ],
    output_key="analysis",
    include_contents="none",
)

# ── chunked reverse engineering (large repositories) ────────────────────────────
# `re_agent` above analyses the whole repository in one run. On a large monolith
# that run resends every file it has read on every model call, so requests grow
# until they exhaust the token quota (429) or the context window. main.py's
# _run_java11_re instead splits the repository into units (agents/shared/
# re_units.py), runs `module_re_agent` once per unit with a fresh context, merges
# the findings in bounded batches if they are too large for one request
# (`findings_merge_agent`), and writes the four-section document from them
# (`re_synthesis_agent`). Setting RE_UNIT_MAX_FILES=0 restores the single run.

module_re_agent = LlmAgent(
    name="java11_module_re",
    model=_MODEL,
    description="Reverse-engineers ONE unit of a large Java 8 JSP/WildFly repository and writes structured Module Findings.",
    instruction=(
        "Load and execute the `java-8-to-11-re-module` skill for the unit below, using list_files, "
        "search_files and read_file. These tools are the only way to inspect the code: nothing in this "
        "environment executes code.\n\n## Your Unit\n{re_scope}"
    ),
    tools=[
        _skills("java-8-to-11-re-module", "java-8-to-11-re"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.search_files),
        FunctionTool(fs_tools.read_file),
    ],
    output_key="module_findings",
    include_contents="none",
)

findings_merge_agent = LlmAgent(
    name="java11_findings_merge",
    model=_MODEL,
    description="Merges several units' Module Findings into one, when all of them are too large for a single request.",
    instruction=(
        "Load the `java-8-to-11-re-module` skill for the Module Findings format. Merge the findings below "
        "into ONE findings document in that same format, headed `## Units <first id>-<last id>`. Keep "
        "every row of every Java 11 Blockers table — the migration plan's file manifest is built from "
        "them — merging only exact duplicates. Keep every Frozen-Zone row. Keep every build fact that "
        "differs between units. Entry points and tests may be summarised as counts per unit plus the "
        "rows that matter for Java 11. Keep every open question. Do not add anything the findings do "
        "not say.\n\n## Findings to merge\n{re_findings}"
    ),
    tools=[_skill("java-8-to-11-re-module")],
    output_key="merged_findings",
    include_contents="none",
)

re_synthesis_agent = LlmAgent(
    name="java11_re_synthesize",
    model=_MODEL,
    description="Writes the four-section Analysis/BRD/Technical Specification/Test Inventory from every unit's Module Findings.",
    instruction=(
        "Load the `java-8-to-11-re` skill and write its four-section document, following its OUTPUT "
        "CONTRACT (the five SECTION markers, as separators, in order) and its section contents exactly. "
        "Its DISCOVERY WORKFLOW has already been carried out, unit by unit, by separate runs: the Module "
        "Findings below are its results and your only evidence. You have no workspace tools — do not "
        "try to inspect files, and never claim to have read a file the findings do not cite. Carry every "
        "row of every unit's Java 11 Blockers table into the Analysis blocker table and the Technical "
        "Specification's dependency, removed-module and Frozen Zone sections; the plan's file manifest "
        "depends on them. Where a unit's findings say they were cut or a unit failed, say so in "
        "Assessment Scope and Confidence.\n\n## Module Findings\n{re_findings}"
    ),
    tools=[_skill("java-8-to-11-re")],
    output_key="analysis",
    include_contents="none",
)

# ── planner_agent ────────────────────────────────────────────────────────────
_PLAN_SKILL_ROSTER: list[tuple[str, str]] = [
    ("java-8-to-11-re-module", "Analysed the repository unit by unit (module, or part of one) into Module Findings"),
    ("java-8-to-11-re", "Combined the Module Findings into the confirmed BRD, Technical Specification and Test Inventory"),
    ("java-8-to-11-plan", "Produces this plan"),
    ("java-8-to-11-modify", "Applies each task's `.java` and build-file changes, inside the scope fence"),
    ("java-8-to-11-validate", "Packages the WAR at release 11 and checks the scope-fence invariants"),
    ("java-8-to-11-fix", "Repairs build and invariant failures inside the loop, inside the scope fence"),
    ("code-review", "Independent review of the result against this plan's manifest"),
    ("java-8-to-11-report", "Produces the final migration report"),
]

planner_agent = LlmAgent(
    name="java11_plan",
    model=_MODEL,
    description="Creates a Java 8 -> Java 11 migration plan that changes only Java sources and build files, leaving JSP and the WildFly deployment untouched.",
    instruction=(
        "Load and execute the `java-8-to-11-plan` skill to create the migration plan.\n\n"
        + skill_manifest.planner_block(_PLAN_SKILL_ROSTER)
        + "\n\n## Scope Fence (the plan must stay inside it)\n" + FENCE_RULES + "\n\n"
        "## Confirmed Business Requirements Document\n{brd}\n\n"
        "## Confirmed Technical Specification\n{technical_spec}\n\n"
        "## Existing Test Inventory\n{test_inventory}\n\n"
        "The Test Inventory is what question 4 is answered from — its Coverage Gaps section is the "
        "starting point for the plan's own, never a substitute for it."
    ),
    tools=[_skill("java-8-to-11-plan")],
    output_key="plan",
    after_agent_callback=make_plan_contract_callback(),
    include_contents="none",
)

# ── modifier_agent: runs once per plan task (main.py sets {current_task}) ────────
modifier_agent = LlmAgent(
    name="modifier_agent",
    model=_MODEL,
    description="Applies ONE task of the confirmed Java 8 -> 11 plan to the workspace's Java sources and build files.",
    instruction=(
        "Load and execute the `java-8-to-11-modify` skill and apply ONLY the work described under "
        "'## Your Task' below. Earlier tasks are already applied to the workspace and later ones run as "
        "separate passes — do not do their work and do not redo work already in place. Use the "
        "list_files, read_file, replace_in_file and write_file tools, preferring replace_in_file for "
        "edits to existing files.\n\n"
        "The target is exactly Java 11: after the run the build's compiler release "
        "(`maven.compiler.release` / `<release>` / `options.release` / toolchain) is 11.\n\n"
        + FENCE_RULES
        + "\n\n## Your Task\n{current_task}"
    ),
    tools=[_skill("java-8-to-11-modify"), *_writing_tools()],
    output_key="modify_result",
    include_contents="none",
)

validator_agent = LlmAgent(
    name="validator_agent",
    model=_MODEL,
    description="Runs the real build and test suite on the migration JDK and the deterministic scope-fence check, and reports pass/fail as JSON.",
    instruction=(
        "Load and execute the `java-8-to-11-validate` skill to build the workspace, check the Java 11 "
        "scope-fence invariants, and report the result."
    ),
    tools=[
        _skill("java-8-to-11-validate"),
        FunctionTool(fs_tools.run_java11_build),
        FunctionTool(fs_tools.run_command),
        FunctionTool(fs_tools.check_java11_invariants),
        FunctionTool(fs_tools.signal_build_success),
    ],
    output_key="build_result",
    include_contents="none",
    after_agent_callback=[
        # A verified resolution from the previous fix pass goes to the modifier's skill.
        make_lesson_verify_callback("build_result", "pending_lessons", skill_targets(_SKILLS_DIR, "java-8-to-11-modify", "java-8-to-11-fix"), "java-8-to-11"),
        make_skill_update_callback(
            validation_key="build_result",
            skill_md_path=_SKILLS_DIR / "java-8-to-11-validate" / "SKILL.md",
            section_header="Validation Pass",
        ),
    ],
)

fixer_agent = LlmAgent(
    name="fixer_agent",
    model=_MODEL,
    description="Fixes the build and scope-fence failures the validator reported, editing only Java sources and build files.",
    instruction=(
        "Load and execute the `java-8-to-11-fix` skill.\n\n"
        + FENCE_RULES
        + "\n\n## Build Report (errors to fix)\n{build_result}"
    ),
    tools=[_skill("java-8-to-11-fix"), *_writing_tools()],
    output_key="fix_result",
    include_contents="none",
    # The fixer states each resolution (its `## Lessons` block); it is published only
    # once the next validation shows the error gone (see shared/learned_fixes.py).
    after_agent_callback=make_lesson_capture_callback("fix_result", "build_result", "pending_lessons"),
)

build_loop = LoopAgent(
    name="build_loop",
    description="Iteratively builds, fence-checks and fixes the migrated workspace (configurable max iterations).",
    sub_agents=[validator_agent, fixer_agent],
    max_iterations=config.BUILD_LOOP_MAX_ITERATIONS,
)

CURATED_SKILLS: list[str] = [
    "java-8-to-11-re", "java-8-to-11-re-module", "java-8-to-11-plan", "java-8-to-11-modify",
    "java-8-to-11-validate", "java-8-to-11-fix", "java-8-to-11-report",
]

code_reviewer_agent = make_code_reviewer_agent(
    _MODEL,
    FunctionTool(fs_tools.list_files),
    FunctionTool(fs_tools.read_file),
    context_instruction=(
        "This is a Java 8 → Java 11 upgrade of a JSP + WildFly application. JSP files, web resources and "
        "WildFly descriptors are FROZEN — any change to one is a CRITICAL finding, as is a `jakarta.*` "
        "import, a Java level other than 11, a changed `<packaging>`/`<finalName>`, or Spring Boot. "
        "Untouched JSP/WildFly files are correct by design, never coverage gaps.\n\n"
        "## Confirmed Migration Plan\n{plan}\n\n## Final Build Result\n{build_result}"
    ),
)

reporter_agent = LlmAgent(
    name="reporter_agent",
    model=_MODEL,
    description="Summarises the Java 8 -> 11 run: what changed, what was deliberately left untouched, build status, and the WildFly runtime actions ops must take.",
    instruction=(
        "Load and execute the `java-8-to-11-report` skill to produce the final migration report. Fold "
        "the Independent Code Review's findings into a dedicated report section rather than ignoring "
        "them.\n\n"
        "## Build Environment (preflight, before the migration)\n{preflight_summary?}\n\n"
        "## Modify Result (one entry per plan task)\n{modify_result}\n\n"
        "## Final Build Result\n{build_result}\n\n"
        "## Independent Code Review\n{code_review}"
    ),
    tools=[_skill("java-8-to-11-report")],
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

# Runs after every task's modifier pass: build/fix once over the finished
# workspace, then review, report and curate. main.py's _run_workspace_code_step
# drives it and routes each agent's output by name.
code_finish_pipeline = SequentialAgent(
    name="java11_code_finish_pipeline",
    description="Builds and fixes the Java 11 workspace in a loop, reviews and reports the outcome, then curates the skill library.",
    sub_agents=[build_loop, code_reviewer_agent, reporter_agent, skill_curator_agent],
)
