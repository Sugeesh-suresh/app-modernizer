"""
A task's share of a skill's knowledge file.

A migration skill keeps its knowledge in a few large files (the Java 8 -> 25 library guide is 30,000
characters: Spring, Hibernate, Jackson, Ehcache, log4j, Guava ...). Every modify and fix subagent is told to
read them — and an incremental run has dozens of subagents, each with a fresh context, each needing one or two
of those sections. Reading the whole file every time is most of a run's input tokens.

The file stays the single source of truth. Its sections are tagged where they apply:

    ### Jackson 1 (`org.codehaus.jackson`) → Jackson 2
    <!-- applies-to: jackson, codehaus -->

and `slice()` returns a copy holding the sections that apply to ONE task: a section with no tag always stays;
a tagged one stays when any of its terms appears (case-insensitive) in the text it is matched against — the
task's text and the original contents of its files, or a failing build's output. A tag on a heading covers the
subsections below it unless they carry their own. What is left out is never hidden: the copy ends with the
omitted headings and the path of the full file, and the subagent loads it when its task needs more. A task with
nothing to match against gets the whole file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
_TAG = re.compile(r"^\s*<!--\s*applies-to:\s*(.+?)\s*-->\s*$", re.IGNORECASE)


@dataclass
class Section:
    level: int
    heading: str
    lines: list[str] = field(default_factory=list)
    terms: list[str] | None = None            # None: untagged (inherits, else always included)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def parse(text: str) -> list[Section]:
    """The file as sections: a preamble (level 0) and one per `##` / `###` heading, in order. The body of a
    section ends at the next heading of any level, so a `##` section is its own introduction only."""
    sections = [Section(0, "")]
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            sections.append(Section(len(m.group(1)), m.group(2), [line]))
            continue
        tag = _TAG.match(line)
        if tag and sections[-1].terms is None and not sections[-1].level and \
                all(not l.strip() or l.startswith("# ") for l in sections[-1].lines):
            # before the first heading: the tag is the whole FILE's (read it only when its subject appears)
            sections[-1].terms = [t.strip().lower() for t in tag.group(1).split(",") if t.strip()]
            continue
        if tag and sections[-1].terms is None and len(sections[-1].lines) == 1 and sections[-1].level:
            sections[-1].terms = [t.strip().lower() for t in tag.group(1).split(",") if t.strip()]
            continue                           # the tag itself is not shown to the reader
        sections[-1].lines.append(line)
    parent_terms: dict[int, list[str] | None] = {}
    for s in sections:                          # a subsection inherits its parent's tag unless it has its own
        if not s.level:
            continue
        if s.terms is None and s.level == 3:
            s.terms = parent_terms.get(2)
        parent_terms[s.level] = s.terms
        if s.level == 2:
            parent_terms.pop(3, None)
    return sections


def applies(section: Section, haystack: str) -> bool:
    return section.terms is None or any(term in haystack for term in section.terms)


def slice_text(text: str, match_text: str, source: str) -> tuple[str, int, list[str]]:
    """(the sliced copy, sections kept, omitted headings) of `text` for a task whose matching text is
    `match_text`. `source` is the full file's path, named in the copy. The whole file when there is nothing
    to match against or nothing would be left out."""
    sections = parse(text)
    tagged = [s for s in sections if s.level and s.terms]
    haystack = (match_text or "").lower()
    if sections[0].terms and haystack.strip() and not applies(sections[0], haystack):
        first = next((s.heading for s in sections if s.level), "this file")
        return (f"> **`{source}` does not apply to this task** — its subject (" + ", ".join(sections[0].terms[:6])
                + f") appears nowhere in your task or its files. If your task does touch it, read `{source}` "
                "itself.\n", 0, [f"the whole file ({first} …)"])
    if not haystack.strip() or not tagged:
        return text, len([s for s in sections if s.level]), []
    kept, omitted = [], []
    for s in sections:
        if not s.level or applies(s, haystack):
            kept.append(s)
        else:
            omitted.append(s.heading)
    if not omitted:
        return text, len(kept) - 1, []
    body = "\n".join(s.text for s in kept).strip()
    note = (f"> **Sliced copy of `{source}` for this task** — {len(kept) - 1} of {len([s for s in sections if s.level])} "
            "sections: the ones whose subject appears in your task or its files. The full file is the source of truth: "
            f"if your task touches something not covered here, read the omitted section from `{source}` before "
            "changing it.\n>\n> Omitted: " + "; ".join(f"“{h}”" for h in omitted) + "\n")
    return note + "\n" + body + "\n", len(kept) - 1, omitted


def core_count(text: str) -> int:
    """How many sections `text` always keeps (the untagged ones)."""
    return len([s for s in parse(text) if s.level and not s.terms])


def tagged(text: str) -> bool:
    """Whether `text` has any applies-to tag (file-level or per section)."""
    return any(s.terms for s in parse(text))
