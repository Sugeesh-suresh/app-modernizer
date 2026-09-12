"""
Deterministic parsing of a confirmed plan into per-stage tasks.

A modifier agent that works through a whole stage in one run accumulates every
file it reads and writes in that run's context — on a large repository that
both overflows the model's window and degrades quality long before it does.
So the plan is written as tasks (`### Task <id>: <title>` blocks inside a
`## Stage <n>: <title>` section), and main.py runs the modifier once per task,
each with a fresh context holding only that task's files.

Parsing is deliberately forgiving: the plan is user-editable in the review
screen, so anything unparseable falls back to "run the whole stage in one
pass", which is the behaviour this module replaced.
"""
import re
from dataclasses import dataclass, field

_STAGE_HEADING = re.compile(r"^##\s+Stage\s+\d+\s*:\s*(?P<title>.+?)\s*$", re.MULTILINE)
_TASK_HEADING = re.compile(r"^###\s+Task\s+(?P<id>[\w.\-]+)\s*:\s*(?P<title>.+?)\s*$", re.MULTILINE)
_FILES_LINE = re.compile(r"^\s*[-*]?\s*Files\s*:\s*(?P<files>.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_BACKTICKED = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class PlanTask:
    """One unit of modifier work: its own heading, body and file list."""
    id: str
    title: str
    body: str
    files: list[str] = field(default_factory=list)


def _normalise(text: str) -> str:
    """Loose comparison key for headings.

    Stage titles are full of arrows ("Java 8 → Java 17 LTS"), and a reviewer
    editing the plan may type "->" or "-" instead, so arrows, dashes and runs
    of whitespace all collapse to a single space.
    """
    return re.sub(r"[\s\-–—>→⟶➜]+", " ", text).strip().casefold()


def stage_section(plan: str, stage_title: str) -> str:
    """The slice of *plan* under the `## Stage <n>: <stage_title>` heading.

    Matched on the title rather than the number, because a stage's number
    depends on which stages a given run includes. Returns "" when the plan has
    no such heading.
    """
    if not plan or not stage_title:
        return ""
    wanted = _normalise(stage_title)
    matches = list(_STAGE_HEADING.finditer(plan))
    for i, match in enumerate(matches):
        if _normalise(match.group("title")) != wanted:
            continue
        start = match.end()
        # A stage section ends at the next "## " heading of any kind (stage or phase).
        next_heading = re.compile(r"^##\s+\S", re.MULTILINE).search(plan, start)
        return plan[start:next_heading.start()].strip() if next_heading else plan[start:].strip()
    return ""


def parse_tasks(section: str) -> list[PlanTask]:
    """Every `### Task <id>: <title>` block in *section*, in document order.

    Returns [] when the section has no task blocks, which tells the caller to
    fall back to running the whole section as a single pass.
    """
    if not section:
        return []
    headings = list(_TASK_HEADING.finditer(section))
    tasks: list[PlanTask] = []
    for i, heading in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(section)
        body = section[heading.start():end].strip()
        tasks.append(PlanTask(
            id=heading.group("id"),
            title=heading.group("title"),
            body=body,
            files=_files_in(body),
        ))
    return tasks


def _files_in(body: str) -> list[str]:
    """Paths listed on the task's `Files:` line(s), backticked or comma-separated."""
    paths: list[str] = []
    for match in _FILES_LINE.finditer(body):
        listed = match.group("files")
        found = _BACKTICKED.findall(listed)
        if not found:
            found = [part.strip() for part in listed.split(",")]
        for path in found:
            cleaned = path.strip().strip("`").strip()
            if cleaned and cleaned.lower() not in {"none", "n/a"} and cleaned not in paths:
                paths.append(cleaned)
    return paths


def stage_units(plan: str, stage_title: str) -> tuple[list[PlanTask], bool]:
    """The units of work for a stage, and whether they came from real task blocks.

    Falls back to one whole-stage unit (the stage section, or the entire plan
    if even the stage heading is missing) so a hand-edited plan still runs.
    """
    section = stage_section(plan, stage_title)
    tasks = parse_tasks(section)
    if tasks:
        return tasks, True
    body = section or plan
    return [PlanTask(id="all", title=stage_title, body=body, files=[])], False
