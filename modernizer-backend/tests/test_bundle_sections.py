"""
Unit tests for main.py's companion-bundle text helpers: deriving the ordered
pattern bundle from session state, and splitting a reviewer-edited combined
BRD/plan back into the per-pattern slices the agents actually read.
"""
from main import _bundle_for, _split_combined_sections


class TestBundleFor:
    def test_no_companions_is_primary_only(self):
        state = {"pattern": "java-8-to-25", "companion_patterns_json": "[]"}

        assert _bundle_for(state) == ["java-8-to-25"]

    def test_companions_run_before_the_primary_in_priority_order(self):
        state = {
            "pattern": "java-8-to-25",
            "companion_patterns_json": '["solr-4-to-9", "oracle-19c-to-23ai"]',
        }

        # Fixed priority: oracle, solr, tibco — then the primary last.
        assert _bundle_for(state) == ["oracle-19c-to-23ai", "solr-4-to-9", "java-8-to-25"]

    def test_unknown_companion_is_ignored(self):
        state = {"pattern": "java-8-to-25", "companion_patterns_json": '["jsp-to-react-bff"]'}

        assert _bundle_for(state) == ["java-8-to-25"]


class TestSplitCombinedSections:
    BUNDLE = ["oracle-19c-to-23ai", "java-8-to-25"]
    COMBINED = (
        "## Java 8 → Java 25\n\n"
        "Bump the compiler release to 25.\n\n"
        "---\n\n"
        "## Oracle 19c → 23ai\n\n"
        "Replace the ojdbc8 driver.\n"
    )

    def test_splits_each_pattern_into_its_own_slice(self):
        sections = _split_combined_sections(self.COMBINED, self.BUNDLE)

        assert sections["java-8-to-25"] == "Bump the compiler release to 25."
        assert sections["oracle-19c-to-23ai"] == "Replace the ojdbc8 driver."

    def test_reviewer_edits_survive_the_split(self):
        edited = self.COMBINED.replace("release to 25", "release to 21 for now")

        sections = _split_combined_sections(edited, self.BUNDLE)

        assert sections["java-8-to-25"] == "Bump the compiler release to 21 for now."
        assert sections["oracle-19c-to-23ai"] == "Replace the ojdbc8 driver."

    def test_a_rewritten_heading_abandons_the_whole_split(self):
        mangled = self.COMBINED.replace("## Oracle 19c → 23ai", "## Oracle bits")

        sections = _split_combined_sections(mangled, self.BUNDLE)

        # All-or-nothing: a partial split would let the Java slice swallow the
        # Oracle plan below it and hand Oracle's manifest to the Java modifier.
        assert sections == {}

    def test_horizontal_rules_inside_a_section_are_preserved(self):
        combined = (
            "## Java 8 → Java 25\n\n"
            "Step one.\n\n"
            "---\n\n"
            "Step two.\n\n"
            "---\n\n"
            "## Oracle 19c → 23ai\n\n"
            "Driver swap.\n"
        )

        sections = _split_combined_sections(combined, self.BUNDLE)

        # Only the trailing separator is dropped; an internal --- stays put.
        assert sections["java-8-to-25"] == "Step one.\n\n---\n\nStep two."

    def test_no_headings_at_all_yields_nothing(self):
        sections = _split_combined_sections("Just a plain plan with no headings.", self.BUNDLE)

        assert sections == {}
