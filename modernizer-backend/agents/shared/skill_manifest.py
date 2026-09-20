"""
Deterministic Skill Composition table for the plan the human approves.

The plan says which skills govern the run and in what order, because that is
what tells an approver which instructions produced the plan and will execute
it. The planner LLM cannot see the roster or the order -- it only ever loads
its own skill -- so the application computes the table and injects it into the
planner's prompt as text to reproduce verbatim. A roster the model cannot see
is a roster it cannot invent.

Deliberately no version or maturity column. Those would have to be
hand-maintained fields in each SKILL.md, and a number any person can set to
"stable" without evidence reads as an assurance while carrying none -- worse
for an approver than no signal at all. If a real maturity signal is wanted
later it has to be derived from something earned, such as recorded runs on real
repositories, not from a field someone edits.
"""
import pathlib
from dataclasses import dataclass

_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "skills"


@dataclass(frozen=True)
class SkillRef:
    """One skill in a pattern's pipeline, with the role it plays in this run."""
    name: str
    role: str
    missing: bool = False


def resolve(entries: list[tuple[str, str]]) -> list[SkillRef]:
    """`[(skill name, role), ...]` in execution order → resolved SkillRefs.

    A skill whose SKILL.md is not on disk is flagged rather than dropped: the
    plan would otherwise promise a stage nothing can execute.
    """
    return [
        SkillRef(name, role, missing=not (_SKILLS_DIR / name / "SKILL.md").is_file())
        for name, role in entries
    ]


def to_markdown(entries: list[tuple[str, str]]) -> str:
    """The Skill Composition section, ready to drop into a plan verbatim."""
    refs = resolve(entries)
    if not refs:
        return ""
    lines = ["| # | Skill | What it governs in this run |", "|---|---|---|"]
    for i, ref in enumerate(refs, 1):
        name = f"`{ref.name}`" + (" — **not found on disk**" if ref.missing else "")
        lines.append(f"| {i} | {name} | {ref.role} |")

    missing = [r for r in refs if r.missing]
    if missing:
        lines += [
            "",
            "**Skills not found on disk:** "
            + ", ".join(f"`{r.name}`" for r in missing)
            + ". The plan cannot rely on them; report this before approving.",
        ]
    return "\n".join(lines)


def planner_block(entries: list[tuple[str, str]]) -> str:
    """The injected prompt block. The planner reproduces the table verbatim —
    it cannot see the roster or the order, so anything it writes instead would
    be invented."""
    table = to_markdown(entries)
    if not table:
        return ""
    return (
        "## Skill Composition (reproduce this table in the plan)\n"
        "These are the skills that can govern this run, in execution order. You cannot see them "
        "anywhere else, so copy the rows exactly as given: never reorder them and never add a "
        "skill that is not listed. The one edit you may make is to DROP a row whose role says it "
        "does not apply to this run (a strategy you were not asked for, or a toggle that is off), "
        "renumbering what is left.\n\n" + table
    )
