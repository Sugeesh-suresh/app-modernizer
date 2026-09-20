"""
Shared factories for the two cross-cutting agents every pattern's code
pipeline ends with:

  code_reviewer_agent -- runs right after the build/validate/fix loop, on
      the final (built or best-effort) code. An independent second pair
      of eyes on correctness/quality the mechanical build loop can't see
      (it only knows "does it compile", not "is it right"). It opens with
      the deterministic change audit (agents/shared/change_audit.py),
      which diffs the pristine baseline against the migrated workspace so
      the review is grounded in what actually changed -- including the
      two things reading the changed files alone can never show: a change
      that carries no migration signal, and a file left untouched that
      still looks legacy.

  skill_curator_agent -- runs LAST, after the code reviewer and the
      reporter, and refines that pattern's own skill files based on
      concrete evidence from this run (a real build error, a real review
      finding, a real ambiguity the generator had to resolve) so future
      runs of the same pattern start from a better skill library. Its
      write access is scoped to exactly the skills passed in
      `allowed_skills` — see agents/shared/skill_curator_tools.py.

Every pattern's agents.py calls these two factories with its own model
and tools/context, then appends both agents at the end of its
SequentialAgent (after reporter_agent). main.py's author-routing (see
_CODE_STREAM_AUTHORS and the code_reviewer_agent/skill_curator_agent
branches in _run_workspace_code_step) streams their output to the
`review-stream`/`code-review-ready` and `curator-stream`/
`skill-curator-ready` SSE events respectively.
"""
import pathlib

from google.adk.agents import LlmAgent
from google.adk.skills import load_skill_from_dir
from google.adk.tools import FunctionTool
from google.adk.tools.skill_toolset import SkillToolset

from .change_audit import audit_migration_changes
from .skill_curator_tools import make_skill_curator_tools

_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "skills"


def _load_skill(name: str) -> SkillToolset:
    return SkillToolset(skills=[load_skill_from_dir(_SKILLS_DIR / name)])


def make_code_reviewer_agent(model: str, list_files_tool, read_file_tool, context_instruction: str) -> LlmAgent:
    """*context_instruction* supplies the pattern-specific `{...}` template
    block (which session-state keys hold the confirmed plan and final
    build result for this pattern/strategy) — the boilerplate framing is
    shared here so every pattern doesn't repeat it."""
    return LlmAgent(
        name="code_reviewer_agent",
        model=model,
        description="Independent code-quality review of the final build/generated code, run after the build/validate/fix loop.",
        instruction=(
            "Load and execute the `code-review` skill. The build/validate/fix loop has already run "
            "and either confirmed the code builds or exhausted its retry budget — your review is about "
            "correctness and quality BEYOND \"does it compile\": logic gaps, edge cases, leftover "
            "placeholders/TODOs, inconsistencies with the confirmed plan, and anything mechanical "
            "build validation cannot see. Use the list_files/read_file tools to inspect the ACTUAL "
            "current code on disk — do not review from memory of what an earlier agent's summary said "
            "it wrote.\n\n"
            "Call `audit_migration_changes` FIRST, before any other tool. It diffs the pristine "
            "uploaded repository against the migrated workspace, so it is the only evidence you have "
            "for two things you must rule on and cannot see by reading changed files alone: whether "
            "every change is actually migration work, and whether the files left untouched were "
            "genuinely irrelevant. Adjudicate each of its candidates against the confirmed plan — it "
            "reports regex evidence, not verdicts.\n\n" + context_instruction
        ),
        tools=[_load_skill("code-review"), FunctionTool(audit_migration_changes), list_files_tool, read_file_tool],
        output_key="code_review",
        include_contents="none",
    )


def make_skill_curator_agent(model: str, allowed_skills: list[str], context_instruction: str) -> LlmAgent:
    """*context_instruction* supplies the pattern-specific `{...}` template
    block referencing this run's plan/generation/build/review results."""
    list_skill_files, read_skill_file, write_skill_file = make_skill_curator_tools(allowed_skills)
    skills_bullets = "\n".join(f"- {s}" for s in allowed_skills)
    return LlmAgent(
        name="skill_curator_agent",
        model=model,
        description="Refines this pattern's own skill files based on concrete evidence from this run, so future runs of this pattern benefit.",
        instruction=(
            "Load and execute the `skill-curator` skill. This is the LAST step of the pipeline, run "
            "after all code changes, the build/validate/fix loop, and the independent code review are "
            "already complete. Your write access is restricted to exactly these skills — every tool "
            f"call is rejected outside this set:\n{skills_bullets}\n\n" + context_instruction
        ),
        tools=[
            _load_skill("skill-curator"),
            FunctionTool(list_skill_files),
            FunctionTool(read_skill_file),
            FunctionTool(write_skill_file),
        ],
        output_key="skill_curator_summary",
        include_contents="none",
    )
