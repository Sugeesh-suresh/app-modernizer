"""
The six questions every migration plan must answer, checked deterministically
before a human is asked to approve it.

A plan is the only artefact a person signs off on, and the expensive failures
are the ones it silently omits: the behaviour nobody listed and so nobody
preserved, the rollback that turns out not to be clean, the claim that was
inferred from a file name rather than read. An LLM asked for eleven sections
reliably produces nine, and the two it drops are the ones it had least material
for -- which are exactly the two that mattered.

So the planner's own output is checked against this contract and, when a
section is missing, a warning block naming the gaps is appended to the plan the
reviewer sees. The plan is never blocked or rewritten: a thin section is
sometimes the honest answer for a small repository, and the reviewer is better
placed to judge that than a regex. The point is that the gap is visible at
approval time rather than discovered after the migration ran.

`make_plan_contract_callback` is the ADK after_agent_callback that does this;
`plan_contract.py` is deliberately free of ADK imports otherwise so the
contract can be checked in a test without a session.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.genai import types as genai_types


@dataclass(frozen=True)
class Question:
    number: int
    heading: str
    why: str
    #: (subsection heading, what it must contain). The heading may list
    #: `|`-separated alternatives where patterns legitimately name it differently.
    parts: tuple[tuple[str, str], ...]


#: The contract. Headings are matched loosely (case, punctuation and filler
#: words are ignored), because the plan is hand-editable in the review screen
#: and a reviewer's rewording must not trip the check.
QUESTIONS: tuple[Question, ...] = (
    Question(
        1, "What Changes",
        "the scope the approver is agreeing to",
        (
            ("Skill Composition", "which skills run, in what order, at which version and maturity"),
            ("Dependency & Version Delta", "a before/after table for the JDK, framework, ORM, drivers and plugins"),
            ("Sample Transformations", "two or three real before/after snippets"),
            ("File Change Manifest|File Manifest", "every file to be touched, with what changes in it"),
        ),
    ),
    Question(
        2, "What Stays the Same",
        "the most commonly missed section, and what makes review manageable",
        (
            ("Explicit Non-Changes", "the contracts this migration does not touch"),
            ("Out of Scope", "what analysis found and deliberately left alone"),
        ),
    ),
    Question(
        3, "Why This Is Safe",
        "the risk argument, with its evidence",
        (
            ("Risk Tier", "the tier AND the factor that drove it"),
            ("Behaviour Inventory", "every endpoint, SQL path, producer/consumer and scheduled job to preserve"),
            ("Blast Radius", "what outside this repo the change can reach"),
        ),
    ),
    Question(
        4, "How We'll Prove It Worked",
        "the evidence that behaviour survived",
        (
            ("Evidence Plan", "which test or comparator proves each behaviour is preserved"),
            ("Coverage Gaps", "the behaviours with nothing proving them, stated up front"),
            ("Validation Contract", "the exit criteria this run is held to"),
        ),
    ),
    Question(
        5, "What Happens If It Fails",
        "what the approver needs before approving, not after",
        (
            ("Rollback Plan", "whether rollback is clean, and what it costs if not"),
            ("Escalation Triggers", "the conditions under which the agent stops and hands to a person"),
        ),
    ),
    Question(
        6, "What the Planner Doesn't Know",
        "the section that builds the most trust",
        (
            ("Confidence Register", "each material claim marked verified or inferred"),
            ("Assumptions", "what the plan relies on that is not proven"),
            ("Open Questions", "behaviour the planner could not determine from the code"),
        ),
    ),
)

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(?P<text>.+?)\s*#*\s*$", re.MULTILINE)
_FILLER = re.compile(r"\b(?:the|a|an|and|or|of|for|in|to|this|its|we|we'll|will|is|are|be)\b")


def _normalise(text: str) -> str:
    """Loose comparison key: case, punctuation, filler words and numbering all
    collapse, so "## 2. What Stays The Same" matches "What stays the same"."""
    text = text.casefold()
    text = re.sub(r"^\s*\d+[.)]?\s*", "", text)
    text = re.sub(r"[^a-z0-9\s']", " ", text)
    text = _FILLER.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class ContractResult:
    missing_questions: list[Question] = field(default_factory=list)
    missing_parts: list[tuple[Question, str, str]] = field(default_factory=list)
    headings_found: int = 0

    @property
    def complete(self) -> bool:
        return not self.missing_questions and not self.missing_parts


def check(plan: str) -> ContractResult:
    """Which of the six questions, and which of their parts, the plan does not answer."""
    result = ContractResult()
    if not plan or not plan.strip():
        result.missing_questions = list(QUESTIONS)
        return result

    headings = [_normalise(m.group("text")) for m in _HEADING.finditer(plan)]
    result.headings_found = len(headings)
    blob = " ⏎ ".join(headings)

    def present(label: str) -> bool:
        key = _normalise(label)
        return any(key in heading or heading in key for heading in headings) or key in blob

    for question in QUESTIONS:
        if not present(question.heading):
            result.missing_questions.append(question)
            continue
        for part, expected in question.parts:
            # A part may list `|`-separated alternatives: a pattern that generates
            # two trees calls its manifests "Backend/Frontend File Manifest".
            if not any(present(alt) for alt in part.split("|")):
                result.missing_parts.append((question, part.split("|")[0], expected))
    return result


def to_markdown(result: ContractResult) -> str:
    """The warning block appended to a plan that does not meet the contract."""
    if result.complete:
        return ""
    lines = [
        "", "---", "",
        "## ⚠ Plan Completeness Check (automated)",
        "",
        "This plan was checked against the six questions a migration plan has to answer before "
        "anyone can meaningfully approve it. The gaps below are **not** blocking — a thin section "
        "is sometimes the honest answer for a small repository — but each one is something the "
        "reviewer is being asked to approve without. Fill them in here in the review screen, or "
        "accept them deliberately.",
        "",
    ]
    if result.missing_questions:
        lines.append("**Missing entirely:**")
        lines.append("")
        for question in result.missing_questions:
            lines.append(f"- **{question.number}. {question.heading}** — {question.why}")
            for part, expected in question.parts:
                lines.append(f"    - `{part}`: {expected}")
        lines.append("")
    if result.missing_parts:
        lines.append("**Present but incomplete:**")
        lines.append("")
        for question, part, expected in result.missing_parts:
            lines.append(f"- **{question.number}. {question.heading}** is missing `{part}` — {expected}")
        lines.append("")
    return "\n".join(lines)


def make_plan_contract_callback(plan_key: str = "plan"):
    """after_agent_callback for a planner agent: append the completeness warning
    to the plan in session state, so the gaps are visible in the review screen.

    Never rewrites or blocks the plan — it only adds the warning block, and does
    nothing at all when the plan already meets the contract.
    """

    def _check_plan(callback_context: CallbackContext) -> Optional[genai_types.Content]:
        state = callback_context.state
        plan = (state or {}).get(plan_key, "") or ""
        if not plan.strip():
            return None
        warning = to_markdown(check(plan))
        if not warning or "## ⚠ Plan Completeness Check" in plan:
            return None
        state[plan_key] = plan + "\n" + warning
        return None

    return _check_plan
