"""
Migration skills: one skill per migration, one step file per pipeline step.

A migration (Oracle 19c -> 23ai, Solr 4 -> 9, Java 8 -> 25, ...) is ONE skill
folder that owns everything the migration knows:

    agents/skills/<migration>/
      SKILL.md                  what the migration is, its workflow and the rules every step follows
      references/steps/<step>.md  one step's instructions (re, plan, modify, validate, fix, report, ...)
      references/*.md           the migration's knowledge, shared by every step

The pipeline — not the skill — decides which step runs, enforces the human
gates and the validate/fix loop. An agent is given the migration's skill and
told which step file is its own (`instruction`), so it loads the overview and
that one step, and the knowledge files its step names.

A step is named `"<migration>:<step>"` (e.g. `"oracle-19c-to-23ai:plan"`); a
skill that is not split into steps (`code-review`, `react-frontend-generate`)
is named by itself. Every place that names a skill — the ADK agents, the
Gemini CLI pipeline, the plan's skill roster, the learned-fix targets, the
skill curator — goes through this module, so a step cannot be named two ways.
"""
from __future__ import annotations

import pathlib

SKILLS_DIR = pathlib.Path(__file__).resolve().parent.parent / "skills"
STEPS_DIR = "references/steps"


def ref(skill: str, step: str | None = None) -> str:
    return f"{skill}:{step}" if step else skill


def parse(name: str) -> tuple[str, str | None]:
    """`"oracle-19c-to-23ai:plan"` -> ("oracle-19c-to-23ai", "plan"); `"code-review"` -> ("code-review", None)."""
    skill, _, step = name.partition(":")
    return skill, (step or None)


def skill_of(name: str) -> str:
    return parse(name)[0]


def step_resource(name: str) -> str:
    """The step file as `load_skill_resource` names it (`references/steps/plan.md`), or "" for a whole skill."""
    _, step = parse(name)
    return f"{STEPS_DIR}/{step}.md" if step else ""


def file(name: str, skills_dir: pathlib.Path | None = None) -> pathlib.Path:
    """The file that holds a step's instructions (its step file), or a whole skill's SKILL.md."""
    root = (skills_dir or SKILLS_DIR) / skill_of(name)
    resource = step_resource(name)
    return root / resource if resource else root / "SKILL.md"


def exists(name: str) -> bool:
    return file(name).is_file() and (SKILLS_DIR / skill_of(name) / "SKILL.md").is_file()


def label(name: str) -> str:
    """How a step reads in a document: `` `oracle-19c-to-23ai` › plan ``."""
    skill, step = parse(name)
    return f"`{skill}` › {step}" if step else f"`{skill}`"


def skills(*names: str) -> list[str]:
    """The distinct skill folders behind these steps, in order."""
    return list(dict.fromkeys(skill_of(n) for n in names))


def instruction(name: str, *also: str) -> str:
    """The ADK agent's directive: load the migration's skill, then its own step file (and any
    other step it must follow alongside, e.g. a Spring Boot stage)."""
    skill, step = parse(name)
    if not step:
        text = f"Load and execute the `{skill}` skill"
    else:
        text = (f"Load the `{skill}` skill (`load_skill`) — its SKILL.md gives the migration's workflow and the rules "
                f"every step follows — then load your step's instructions with `load_skill_resource` "
                f"(`{step_resource(name)}`) and execute them, loading the knowledge files that step names")
    extra = [a for a in also if a != name]
    if extra:
        text += ". Also load and follow " + " and ".join(_also(a) for a in extra)
    return text


def load_only(name: str) -> str:
    """Load a step's instructions without executing them (an agent that only needs its format)."""
    skill, step = parse(name)
    return (f"Load the `{skill}` skill (`load_skill`) and its step file `{step_resource(name)}` "
            "(`load_skill_resource`)") if step else f"Load the `{skill}` skill"


def _also(name: str) -> str:
    skill, step = parse(name)
    return f"the `{skill}` skill's `{step_resource(name)}`" if step else f"the `{skill}` skill"


def cli_instruction(name: str, *also: str) -> str:
    """The same directive for a Gemini CLI subagent (`activate_skill`, then read the step file)."""
    skill, step = parse(name)
    if not step:
        text = f"Activate the `{skill}` skill and execute it"
    else:
        text = (f"Activate the `{skill}` skill (its SKILL.md gives the migration's workflow and the rules every step "
                f"follows), then read its step file `{step_resource(name)}` in the skill's folder and execute it, "
                "reading the knowledge files that step names")
    extra = [a for a in also if a != name]
    if extra:
        text += ". Also activate and follow " + " and ".join(
            (f"the `{parse(a)[0]}` skill's `{step_resource(a)}`" if parse(a)[1] else f"the `{a}` skill")
            for a in extra)
    return text


def cli_load_only(name: str) -> str:
    """Gemini CLI: activate the skill and read a step file without executing it (only its format is needed)."""
    skill, step = parse(name)
    return (f"Activate the `{skill}` skill and read its step file `{step_resource(name)}`" if step
            else f"Activate the `{skill}` skill")


def toolset(*names: str):
    """One ADK SkillToolset holding every skill these steps belong to — one toolset per agent, since
    two would declare `list_skills` / `load_skill` twice (which Gemini rejects)."""
    from google.adk.skills import load_skill_from_dir
    from google.adk.tools.skill_toolset import SkillToolset
    return SkillToolset(skills=[load_skill_from_dir(SKILLS_DIR / s) for s in skills(*names)])
