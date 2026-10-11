"""
Safety-focused unit tests for agents/shared/skill_curator_tools.py — the
one tool set in this app with write access to the skill library itself.
These tests exist specifically to prove the scoping/sandbox guarantees
hold: a curator agent restricted to skill A cannot read or write skill B,
cannot escape a skill's own directory, and cannot write non-markdown files
or create new files that didn't already exist.
"""
from agents.shared.skill_curator_tools import make_skill_curator_tools


class TestScoping:
    def test_can_read_and_write_an_allowed_skill(self):
        list_files, read_file, write_file = make_skill_curator_tools(["java-8-to-25:report"])

        listing = list_files("java-8-to-25")      # a step grants the migration's whole skill folder
        assert "SKILL.md" in listing and "references/steps/report.md" in listing

        original = read_file("java-8-to-25", "references/steps/report.md")
        assert "ERROR" not in original[:6]
        assert len(original) > 0

        result = write_file("java-8-to-25", "references/steps/report.md", original)  # round-trip, no real change
        assert result.startswith("Wrote")
        assert read_file("java-8-to-25", "references/steps/report.md") == original

    def test_cannot_touch_a_skill_outside_the_allowlist(self):
        list_files, read_file, write_file = make_skill_curator_tools(["java-8-to-25:report"])

        assert list_files("solr-4-to-9").startswith("ERROR")
        assert read_file("solr-4-to-9", "SKILL.md").startswith("ERROR")
        assert write_file("solr-4-to-9", "SKILL.md", "malicious content").startswith("ERROR")

    def test_cannot_escape_the_skill_directory_via_path_traversal(self):
        _, read_file, write_file = make_skill_curator_tools(["java-8-to-25:report"])

        assert read_file("java-8-to-25", "../../../main.py").startswith("ERROR")
        assert write_file("java-8-to-25", "../../__init__.py", "import os").startswith("ERROR")

    def test_cannot_write_a_non_markdown_file(self):
        _, _, write_file = make_skill_curator_tools(["java-8-to-25:report"])
        result = write_file("java-8-to-25:report", "SKILL.py", "print('hi')")
        assert result.startswith("ERROR")

    def test_cannot_create_a_new_file_that_did_not_already_exist(self):
        _, _, write_file = make_skill_curator_tools(["java-8-to-25:report"])
        result = write_file("java-8-to-25:report", "references/brand-new-file.md", "# New")
        assert result.startswith("ERROR")

    def test_unknown_skill_name_is_rejected(self):
        list_files, _, _ = make_skill_curator_tools(["java-8-to-25:report"])
        assert list_files("not-a-real-skill").startswith("ERROR")
