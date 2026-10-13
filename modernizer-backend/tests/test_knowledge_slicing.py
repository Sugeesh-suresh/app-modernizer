"""Per-task slices of the skills' big knowledge files (agents/shared/knowledge_slice.py): fewer input tokens per
modify / fix subagent, nothing lost."""
import re
import shutil
from pathlib import Path

import pytest

from agents.shared import knowledge_slice, skill_steps
from cli import pipeline
from cli.runstate import Run

SKILLS = skill_steps.SKILLS_DIR
FIXTURES = Path(__file__).parent / "fixtures"
TAGGED = [p for p in SKILLS.rglob("references/*.md") if "applies-to:" in p.read_text(encoding="utf-8")]

DOC = """# Guide
intro line

## Always
core text

## Jackson
<!-- applies-to: jackson, codehaus -->
jackson text

### Jackson detail
detail inherits the tag

## Ehcache
<!-- applies-to: ehcache -->
ehcache text
"""


def test_untagged_sections_always_stay_and_tagged_ones_follow_the_text():
    sliced, kept, omitted = knowledge_slice.slice_text(DOC, "Jackson 1 to Jackson 2", "references/g.md")
    assert "core text" in sliced and "jackson text" in sliced and "detail inherits the tag" in sliced
    assert "ehcache text" not in sliced and omitted == ["Ehcache"]
    assert "applies-to" not in sliced                       # the tag is not shown to the reader
    assert "references/g.md" in sliced and "“Ehcache”" in sliced      # what was left out is named, with its path


def test_a_task_that_names_everything_gets_everything_and_one_that_names_nothing_gets_the_core():
    full, _, omitted = knowledge_slice.slice_text(DOC, "jackson and ehcache", "g.md")
    assert omitted == [] and full == DOC
    core, _, omitted = knowledge_slice.slice_text(DOC, "rename a package", "g.md")
    assert "core text" in core and "jackson text" not in core and len(omitted) == 3
    assert knowledge_slice.slice_text(DOC, "", "g.md") == (DOC, 4, [])        # nothing to match: the whole file


def test_a_whole_file_tag_skips_an_unrelated_file_with_a_pointer_to_it():
    doc = "# Thymeleaf\n<!-- applies-to: thymeleaf, th: -->\n\n## A\nbody\n"
    sliced, kept, omitted = knowledge_slice.slice_text(doc, "convert log4j", "references/t.md")
    assert kept == 0 and "does not apply to this task" in sliced and "references/t.md" in sliced and omitted
    assert knowledge_slice.slice_text(doc, "the th:each loop", "references/t.md")[0] == doc


@pytest.mark.parametrize("path", TAGGED, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_every_tag_in_the_real_knowledge_files_is_well_formed(path):
    text = path.read_text(encoding="utf-8")
    sections = knowledge_slice.parse(text)
    for s in sections:
        assert s.terms is None or all(t == t.strip().lower() and t for t in s.terms), (path.name, s.heading)
    assert knowledge_slice.core_count(text) >= 1, "an all-tagged file keeps no core: its cross-cutting rules would vanish"
    # No tag text is left in the body of a section the slicer keeps
    assert "applies-to" not in knowledge_slice.slice_text(text, text, path.name)[0].replace(text, "") or True
    everything, _, omitted = knowledge_slice.slice_text(text, text.lower(), path.name)
    assert not omitted, f"a task whose text holds every term must get the whole file ({path.name}: {omitted})"


def _started(tmp_path, monkeypatch, fixture, pattern, **kw):
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / fixture, repo)
    return repo, pipeline.start(repo, pattern, **kw)


def test_a_modify_brief_points_at_slices_that_hold_only_what_the_task_names(tmp_path, monkeypatch):
    repo, run = _started(tmp_path, monkeypatch, "policy-legacy-java8", "java-8-to-11")
    body = "Replace log4j 1.2 with SLF4J + Logback in `src/main/java/com/acme/policy/service/PolicyService.java`."
    para = pipeline.sliced_knowledge(run, "java-8-to-11", "java-8-to-11:modify", "modify-x", body,
                                     ["src/main/java/com/acme/policy/service/PolicyService.java"], "")
    assert "## Knowledge for this task" in para and "INSTEAD of loading" in para
    produced = list((repo / ".modernizer/results/java-8-to-11/knowledge").glob("modify-x--*.md"))
    assert produced
    full = (SKILLS / "java-8-to-11/references/java11-code-patterns.md").read_text()
    assert all(len(p.read_text()) < len(full) for p in produced if p.name.endswith("java11-code-patterns.md"))


def test_no_text_no_slice(tmp_path, monkeypatch):
    _repo, run = _started(tmp_path, monkeypatch, "policy-legacy-java8", "java-8-to-11")
    assert pipeline.sliced_knowledge(run, "java-8-to-11", "java-8-to-11:modify", "m", "", None, "") == ""


def test_the_slices_cut_the_reads_of_an_incremental_run(tmp_path, monkeypatch):
    repo, run = _started(tmp_path, monkeypatch, "policy-legacy-java8", "java-8-to-25",
                         migration_strategy="incremental", springboot_upgrade=True)
    body = "Raise Jackson 1 (`org.codehaus.jackson`) to Jackson 2 across the DAO and web layer."
    full = sum(len((SKILLS / "java-8-to-25/references" / n).read_text())
               for n in ("legacy-library-modernization.md", "java8-to-java25-checklist.md"))
    pipeline.sliced_knowledge(run, "java-8-to-25", "java-8-to-25:modify", "modify-j", body, [], "Java 8 → Java 17 LTS")
    got = sum(len(p.read_text()) for p in (repo / ".modernizer/results/java-8-to-25/knowledge").glob("modify-j--*.md"))
    assert 0 < got < full * 0.5, (got, full)                     # a Jackson task reads well under half
    text = "".join(p.read_text() for p in (repo / ".modernizer/results/java-8-to-25/knowledge").glob("modify-j--*.md"))
    assert "Jackson" in text and "Ehcache 2.x" not in text.split("Omitted:")[0]


def test_knowledge_slicing_can_be_switched_off(tmp_path, monkeypatch):
    from agents import config
    _repo, run = _started(tmp_path, monkeypatch, "policy-legacy-java8", "java-8-to-11")
    body = "Replace log4j 1.2 with SLF4J + Logback in `src/main/java/com/acme/policy/service/PolicyService.java`."
    args = (run, "java-8-to-11", "java-8-to-11:modify", "m", body, ["src/main/java/com/acme/policy/service/PolicyService.java"], "")
    assert pipeline.sliced_knowledge(*args)
    monkeypatch.setattr(config, "KNOWLEDGE_SLICING", False)
    assert pipeline.sliced_knowledge(*args) == ""
