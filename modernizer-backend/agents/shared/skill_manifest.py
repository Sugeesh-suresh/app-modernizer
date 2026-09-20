"""
Deterministic Skill Composition table for the plan the human approves.

The plan has to say which skills govern the run, in what order and at which
version, because a skill still at 0.x has not been proven on real repositories
and the approver needs to see that before signing off. None of that is
knowable to the planner LLM -- it can read a skill's instructions but not the
roster, the order, or the version -- so the application computes the table and
injects it into the planner's prompt as text to reproduce verbatim. A version
the model cannot see is a version it cannot invent.

Versions and maturity live in each SKILL.md's frontmatter (`version:` and
`maturity:`), which ADK parses and exposes on `skill.frontmatter`. They are
hand-maintained: bump a skill's version when its instructions change materially,
and move it off `experimental` only once it has actually been proven on real
repositories.
"""
import pathlib
import re
from dataclasses import dataclass

_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "skills"

_FRONTMATTER = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)

#: Maturity values, worst first — the planner surfaces the weakest link.
MATURITY_NOTE = {
    "experimental": "not yet proven on real repositories — review this stage's output closely",
    "beta": "proven on some repositories; edge cases still expected",
    "stable": "proven in production use",
}


@dataclass(frozen=True)
class SkillRef:
    """One skill in a pattern's pipeline, with the role it plays in this run."""
    name: str
    role: str
    version: str = ""
    maturity: str = ""
    missing: bool = False


def _read_frontmatter(name: str) -> dict[str, str]:
    path = _SKILLS_DIR / name / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    match = _FRONTMATTER.match(text)
    if not match:
        return {}
    out: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def resolve(entries: list[tuple[str, str]]) -> list[SkillRef]:
    """`[(skill name, role), ...]` in execution order → resolved SkillRefs."""
    refs: list[SkillRef] = []
    for name, role in entries:
        fm = _read_frontmatter(name)
        if not fm:
            refs.append(SkillRef(name, role, missing=True))
            continue
        refs.append(SkillRef(
            name, role,
            version=fm.get("version", "") or "unversioned",
            maturity=(fm.get("maturity", "") or "unknown").lower(),
        ))
    return refs


def to_markdown(entries: list[tuple[str, str]]) -> str:
    """The Skill Composition section, ready to drop into a plan verbatim."""
    refs = resolve(entries)
    if not refs:
        return ""
    lines = [
        "| # | Skill | Version | Maturity | What it governs in this run |",
        "|---|---|---|---|---|",
    ]
    for i, ref in enumerate(refs, 1):
        if ref.missing:
            lines.append(f"| {i} | `{ref.name}` | **not found** | — | {ref.role} |")
            continue
        lines.append(
            f"| {i} | `{ref.name}` | {ref.version} | {ref.maturity} | {ref.role} |"
        )

    unproven = [r for r in refs if not r.missing and r.maturity != "stable"]
    missing = [r for r in refs if r.missing]
    lines.append("")
    if missing:
        lines.append(
            "**Skills not found on disk:** "
            + ", ".join(f"`{r.name}`" for r in missing)
            + ". The plan cannot rely on them; report this before approving."
        )
    if unproven:
        notes = sorted({MATURITY_NOTE.get(r.maturity, "maturity not recorded") for r in unproven})
        lines.append(
            f"**{len(unproven)} of {len(refs)} skills are not yet `stable`** "
            f"({', '.join(f'`{r.name}` {r.version}' for r in unproven)}) — "
            + "; ".join(notes)
            + ". Weigh this when approving: the stages those skills govern carry more risk "
            "than their technical difficulty alone suggests."
        )
    else:
        lines.append("All skills governing this run are at `stable` maturity.")
    return "\n".join(lines)


def planner_block(entries: list[tuple[str, str]]) -> str:
    """The injected prompt block. The planner reproduces the table verbatim —
    it has no other way to know these versions, so anything it writes instead
    would be invented."""
    table = to_markdown(entries)
    if not table:
        return ""
    return (
        "## Skill Composition (reproduce this table in the plan)\n"
        "These are the skills that can govern this run, in execution order, with the versions read "
        "from disk at runtime. You cannot see them anywhere else, so copy the rows exactly as given: "
        "never edit a version or a maturity value, never reorder, and never add a skill that is not "
        "listed. The one edit you may make is to DROP a row whose role says it does not apply to "
        "this run (a strategy you were not asked for, or a toggle that is off), renumbering what is "
        "left. Reproduce the note beneath the table, recounting it for the rows you kept.\n\n" + table
    )
