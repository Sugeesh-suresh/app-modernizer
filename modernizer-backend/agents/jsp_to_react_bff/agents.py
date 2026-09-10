"""
JSP -> React + BFF agent pipeline — an architectural transformation, not a
refactor/upgrade like the other 3 workspace-based patterns, so it has a
genuinely different shape:

    re_pipeline = SequentialAgent(jsp_re_agent, jsp_classifier_agent)
        jsp_re_agent         (tool-driven: list_files/read_file) -> jsp_facts
        jsp_classifier_agent (reasoning over jsp_facts)           -> analysis
                                (standard ANALYSIS/BRD/TECHNICAL_SPECIFICATION/
                                 TEST_INVENTORY sections -- the classifier's
                                 frontend-vs-backend decision is embedded in
                                 the Technical Specification)
    planner_agent   (reasoning over confirmed BRD/TechSpec)        -> plan
        (React page/component map + BFF API contract + file manifests
         for BOTH target trees + migration groups)
    code_pipeline = SequentialAgent(
        backend_generator_agent,   -- writes backend/  (Spring Boot 4 BFF, JAR)
        frontend_generator_agent,  -- writes frontend/ (React app)
        build_loop(validator_agent, fixer_agent),  -- mvn compile backend/ + npm run build frontend/
        reporter_agent,
    )

Unlike the other patterns, modifier here never edits the original JSP
source — it's read-only reference material. New files land in two fresh
subtrees of the same workspace (see agents/jsp_to_react_bff/tools.py's
`run_command(..., subdir=...)`).

Skills (Pattern 2 -- file-based). Several of these are intentionally
generic/reusable beyond this exact pipeline (see each skill's own
description for the reuse boundary):

  jsp-re                  -- generic: JSP repo reverse-engineering/extraction
  jsp-logic-classifier     -- generic: frontend-vs-backend logic placement decision
  jsp-to-react-bff-plan    -- this-pipeline-specific: BFF architecture + manifests
  react-frontend-generate  -- generic: React code generation from a page/component map
  spring-boot-bff-generate -- generic (any Spring Boot BFF target): JAR-packaged BFF generation
  jsp-to-react-bff-validate/-fix/-report -- this-pipeline-specific: dual-tree build loop
"""
import os
import pathlib

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.skills import load_skill_from_dir
from google.adk.tools import FunctionTool
from google.adk.tools.skill_toolset import SkillToolset

from .. import config
from ..shared.callbacks import make_skill_update_callback
from ..shared.review_and_curate import make_code_reviewer_agent, make_skill_curator_agent
from . import tools as fs_tools

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "skills"


def _skill(name: str) -> SkillToolset:
    return SkillToolset(skills=[load_skill_from_dir(_SKILLS_DIR / name)])


# ── re_pipeline: extract JSP facts, then classify frontend vs backend ──────────

jsp_re_agent = LlmAgent(
    name="jsp_re",
    model=_MODEL,
    description="Reverse-engineers a JSP repository via list_files/read_file: page inventory, embedded logic, session/state usage, navigation flow.",
    instruction="Load and execute the `jsp-re` skill, using the list_files and read_file tools to explore the workspace.",
    tools=[_skill("jsp-re"), FunctionTool(fs_tools.list_files), FunctionTool(fs_tools.read_file)],
    output_key="jsp_facts",
    include_contents="none",
)

jsp_classifier_agent = LlmAgent(
    name="jsp_classifier",
    model=_MODEL,
    description="Classifies every extracted logic unit as a frontend (React) or backend (BFF) concern, then produces Analysis/BRD/TechSpec/Test Inventory.",
    instruction=(
        "Load and execute the `jsp-logic-classifier` skill to classify the extracted logic, then "
        "produce the standard four-section output (Analysis / BRD / Technical Specification / "
        "Existing Test Inventory) — fold the frontend-vs-backend classification table into the "
        "Technical Specification section.\n\n"
        "## Extracted JSP Facts (from jsp_re_agent)\n{jsp_facts}"
    ),
    tools=[_skill("jsp-logic-classifier")],
    output_key="analysis",
    include_contents="none",
)

re_pipeline = SequentialAgent(
    name="jsp_re_pipeline",
    description="Extracts JSP repository facts, then classifies every logic unit as frontend or backend.",
    sub_agents=[jsp_re_agent, jsp_classifier_agent],
)

# ── planner_agent: BFF architecture + dual-tree file manifests ─────────────────

planner_agent = LlmAgent(
    name="jsp_plan",
    model=_MODEL,
    description="Designs the target React + Spring Boot 4 BFF architecture and file manifests for both trees, from the confirmed BRD and Technical Specification.",
    instruction=(
        "Load and execute the `jsp-to-react-bff-plan` skill to create the migration plan.\n\n"
        "## Confirmed Business Requirements Document\n{brd}\n\n"
        "## Confirmed Technical Specification (includes the frontend/backend classification)\n{technical_spec}"
    ),
    tools=[_skill("jsp-to-react-bff-plan")],
    output_key="plan",
    include_contents="none",
)

# ── code_pipeline: generate backend, then frontend, then validate both ─────────

backend_generator_agent = LlmAgent(
    name="backend_generator_agent",
    model=_MODEL,
    description="Generates the Spring Boot 4 BFF backend (standalone JAR) into workspace subdir backend/, per the confirmed plan's backend file manifest.",
    instruction=(
        "Load and execute the `spring-boot-bff-generate` skill to generate the BFF backend under the "
        "workspace subdirectory `backend/`, reading the original JSP source (read-only reference) via "
        "list_files/read_file and writing new files via write_file.\n\n"
        "## Confirmed Migration Plan\n{plan}"
    ),
    tools=[
        _skill("spring-boot-bff-generate"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
        FunctionTool(fs_tools.write_file),
    ],
    output_key="backend_generate_result",
    include_contents="none",
)

frontend_generator_agent = LlmAgent(
    name="frontend_generator_agent",
    model=_MODEL,
    description="Generates the React frontend into workspace subdir frontend/, per the confirmed plan's frontend file manifest.",
    instruction=(
        "Load and execute the `react-frontend-generate` skill to generate the React app under the "
        "workspace subdirectory `frontend/`, reading the original JSP source (read-only reference) via "
        "list_files/read_file and writing new files via write_file. The BFF's API contract is in the "
        "plan below — call it exactly as specified, do not invent different endpoint shapes.\n\n"
        "## Confirmed Migration Plan\n{plan}\n\n"
        "## Backend Generation Result (for the actual BFF endpoints just generated)\n{backend_generate_result}"
    ),
    tools=[
        _skill("react-frontend-generate"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
        FunctionTool(fs_tools.write_file),
    ],
    output_key="frontend_generate_result",
    include_contents="none",
)

validator_agent = LlmAgent(
    name="validator_agent",
    model=_MODEL,
    description="Runs real builds for both trees -- mvn/gradle compile in backend/, npm run build in frontend/ -- and reports combined pass/fail as JSON.",
    instruction="Load and execute the `jsp-to-react-bff-validate` skill to build both trees and report the result.",
    tools=[
        _skill("jsp-to-react-bff-validate"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.run_command),
        FunctionTool(fs_tools.signal_build_success),
    ],
    output_key="build_result",
    include_contents="none",
    after_agent_callback=make_skill_update_callback(
        validation_key="build_result",
        skill_md_path=_SKILLS_DIR / "jsp-to-react-bff-validate" / "SKILL.md",
        section_header="Validation Pass",
    ),
)

fixer_agent = LlmAgent(
    name="fixer_agent",
    model=_MODEL,
    description="Reads the files implicated by validator_agent's report (in either tree) and fixes them in place.",
    instruction=(
        "Load and execute the `jsp-to-react-bff-fix` skill.\n\n"
        "## Build Report (errors to fix, tagged by tree)\n{build_result}"
    ),
    tools=[
        _skill("jsp-to-react-bff-fix"),
        FunctionTool(fs_tools.list_files),
        FunctionTool(fs_tools.read_file),
        FunctionTool(fs_tools.write_file),
    ],
    output_key="fix_result",
    include_contents="none",
    after_agent_callback=make_skill_update_callback(
        validation_key="build_result",
        skill_md_path=_SKILLS_DIR / "jsp-to-react-bff-fix" / "SKILL.md",
        section_header="Fix Pass",
    ),
)

build_loop = LoopAgent(
    name="build_loop",
    description="Iteratively builds and fixes both the backend/ and frontend/ trees (configurable max iterations).",
    sub_agents=[validator_agent, fixer_agent],
    max_iterations=config.BUILD_LOOP_MAX_ITERATIONS,
)

code_reviewer_agent = make_code_reviewer_agent(
    _MODEL,
    FunctionTool(fs_tools.list_files),
    FunctionTool(fs_tools.read_file),
    context_instruction=(
        "Review BOTH the backend/ and frontend/ trees — pay particular attention to consistency "
        "*between* them (does the frontend's API client actually match what the backend controllers "
        "expose?), since that is the failure mode a same-tree build/compile check cannot catch at all.\n\n"
        "## Confirmed Migration Plan\n{plan}\n\n## Final Build Result (both trees)\n{build_result}"
    ),
)

reporter_agent = LlmAgent(
    name="reporter_agent",
    model=_MODEL,
    description="Summarises the architectural migration -- what moved to React vs the BFF, final build status for both trees, and any remaining issues.",
    instruction=(
        "Load and execute the `jsp-to-react-bff-report` skill to produce the final migration report. "
        "Fold the Independent Code Review's findings into a dedicated report section rather than "
        "ignoring them.\n\n"
        "## Backend Generation Result\n{backend_generate_result}\n\n"
        "## Frontend Generation Result\n{frontend_generate_result}\n\n"
        "## Final Build Result (both trees)\n{build_result}\n\n"
        "## Independent Code Review\n{code_review}"
    ),
    tools=[_skill("jsp-to-react-bff-report")],
    output_key="final_report",
    include_contents="none",
)

skill_curator_agent = make_skill_curator_agent(
    _MODEL,
    allowed_skills=[
        "jsp-re", "jsp-logic-classifier", "jsp-to-react-bff-plan",
        "react-frontend-generate", "spring-boot-bff-generate",
        "jsp-to-react-bff-validate", "jsp-to-react-bff-fix", "jsp-to-react-bff-report",
    ],
    context_instruction=(
        "## Confirmed Migration Plan\n{plan}\n\n## Backend Generation Result\n{backend_generate_result}\n\n"
        "## Frontend Generation Result\n{frontend_generate_result}\n\n"
        "## Final Build Result (both trees)\n{build_result}\n\n## Independent Code Review\n{code_review}"
    ),
)

code_pipeline = SequentialAgent(
    name="jsp_code_pipeline",
    description="Generates the BFF backend then the React frontend, builds/fixes both in a loop, reviews and reports the outcome, then curates the skill library.",
    sub_agents=[
        backend_generator_agent, frontend_generator_agent, build_loop,
        code_reviewer_agent, reporter_agent, skill_curator_agent,
    ],
)
