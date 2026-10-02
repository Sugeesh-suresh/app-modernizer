"""
Tests for the stack-discovery orchestration in main.py: parsing the dependency
mapper's machine-readable block, reconciling it against the deterministic
pre-scan, and turning the confirmed stacks into an RE fan-out bundle.

The reconciliation rules are where an LLM's output becomes a document people
download and rely on, so each one is pinned here rather than left to the prompt.
"""
import json

import pytest

import main
from agents.shared import stack_detector


PRESCAN = [
    {"pattern": "oracle-19c-to-23ai", "label": "Oracle 19c → 23ai",
     "evidence": ["pom.xml: matched `ojdbc8`"], "extraction_only": False},
    {"pattern": "solr-4-to-9", "label": "Solr 4x → Solr 9x",
     "evidence": ["pom.xml: matched `org.apache.solr`"], "extraction_only": False},
    {"pattern": "java-8-to-25", "label": "Java 8 → Java 25",
     "evidence": ["src/A.java: present"], "extraction_only": False},
]


def _mapper_reply(stacks: list[dict], rejected: list[dict] | None = None) -> str:
    return (
        "# Technology Stack Inventory\n\n"
        "Prose with a ${property.name} and a JNDI name java:jboss/datasources/X.\n\n"
        "```json\n"
        + json.dumps({"stacks": stacks, "rejected": rejected or []})
        + "\n```"
    )


class TestParseMapperJson:
    def test_reads_the_fenced_block_past_braces_in_the_prose(self):
        raw = _mapper_reply([{"pattern": "java-8-to-25", "label": "Java", "evidence": ["A: b"]}])

        assert _patterns(main._parse_mapper_json(raw)) == ["java-8-to-25"]

    def test_last_block_wins(self):
        """The contract puts the result block last; an earlier fenced example
        must not be mistaken for it."""
        raw = (
            '```json\n{"stacks": [{"pattern": "solr-4-to-9", "label": "x", "evidence": ["a: b"]}]}\n```\n'
            'and the real one:\n'
            '```json\n{"stacks": [{"pattern": "java-8-to-25", "label": "y", "evidence": ["c: d"]}]}\n```'
        )

        assert _patterns(main._parse_mapper_json(raw)) == ["java-8-to-25"]

    def test_unfenced_object_is_still_found(self):
        raw = 'Some prose.\n{"stacks": [{"pattern": "java-8-to-25", "label": "y", "evidence": ["c: d"]}]}'

        assert _patterns(main._parse_mapper_json(raw)) == ["java-8-to-25"]

    @pytest.mark.parametrize("raw", ["", "   ", "no json at all", "```json\nnot json\n```"])
    def test_unusable_replies_return_empty(self, raw):
        assert main._parse_mapper_json(raw) == {}


def _patterns(parsed: dict) -> list[str]:
    return [s["pattern"] for s in parsed.get("stacks", [])]


class TestMergeMapperResult:
    def test_confirmed_stack_keeps_both_citations_mapper_first(self):
        raw = _mapper_reply([{
            "pattern": "oracle-19c-to-23ai", "label": "Oracle Database",
            "evidence": ["pom.xml:41 ojdbc8 19.3.0.0 (compile scope)"],
        }])

        stacks, _ = main._merge_mapper_result(PRESCAN, raw)

        oracle = next(s for s in stacks if s["pattern"] == "oracle-19c-to-23ai")
        assert oracle["evidence"][0].startswith("pom.xml:41")
        assert "pom.xml: matched `ojdbc8`" in oracle["evidence"]

    def test_added_known_stack_is_reverse_engineered_and_flagged(self):
        raw = _mapper_reply([{
            "pattern": "wildfly", "label": "WildFly",
            "evidence": ["standalone.xml: urn:jboss:domain:14.0"],
        }])

        stacks, _ = main._merge_mapper_result(PRESCAN, raw)

        wildfly = next(s for s in stacks if s["pattern"] == "wildfly")
        assert wildfly["extraction_only"] is True

    def test_stack_without_evidence_is_dropped(self):
        raw = _mapper_reply([{"pattern": "wildfly", "label": "WildFly", "evidence": []}])

        stacks, notes = main._merge_mapper_result(PRESCAN, raw)

        assert "wildfly" not in {s["pattern"] for s in stacks}
        assert any("without evidence" in n for n in notes)

    def test_unknown_stack_is_reported_but_not_run(self):
        """An identifier with no RE skill must not become a fan-out leg — that
        would KeyError on PATTERN_RUNNERS mid-run."""
        raw = _mapper_reply([{
            "pattern": "kafka", "label": "Apache Kafka",
            "evidence": ["pom.xml: kafka-clients"],
        }])

        stacks, notes = main._merge_mapper_result(PRESCAN, raw)

        assert "kafka" not in {s["pattern"] for s in stacks}
        assert any("kafka" in n and "no RE skill" in n for n in notes)
        assert all(s["pattern"] in stack_detector.STACK_ORDER for s in stacks)

    def test_rejection_with_a_reason_removes_the_stack(self):
        raw = _mapper_reply([], [
            {"pattern": "solr-4-to-9", "reason": "only match is commented out at pom.xml:88"},
        ])

        stacks, notes = main._merge_mapper_result(PRESCAN, raw)

        assert "solr-4-to-9" not in {s["pattern"] for s in stacks}
        assert any("commented out" in n for n in notes)

    def test_rejection_without_a_reason_leaves_the_prescan_standing(self):
        raw = _mapper_reply([], [{"pattern": "java-8-to-25", "reason": ""}])

        stacks, notes = main._merge_mapper_result(PRESCAN, raw)

        assert "java-8-to-25" in {s["pattern"] for s in stacks}
        assert any("without a reason" in n for n in notes)

    def test_unparseable_reply_preserves_every_prescan_finding(self):
        """The failure that matters most: silently returning nothing here would
        produce an empty document that looks like a clean repository."""
        stacks, notes = main._merge_mapper_result(PRESCAN, "the model rambled and emitted no JSON")

        assert {s["pattern"] for s in stacks} == {s["pattern"] for s in PRESCAN}
        assert any("could not be parsed" in n for n in notes)

    def test_result_is_ordered_by_stack_order(self):
        raw = _mapper_reply([
            {"pattern": "wildfly", "label": "WildFly", "evidence": ["standalone.xml: found"]},
        ])

        stacks, _ = main._merge_mapper_result(PRESCAN, raw)

        found = [s["pattern"] for s in stacks]
        assert found == [p for p in stack_detector.STACK_ORDER if p in found]

    def test_malformed_entries_are_skipped_not_fatal(self):
        raw = (
            '```json\n{"stacks": ["a string", null, 42, '
            '{"pattern": "wildfly", "label": "W", "evidence": ["f: x"]}], '
            '"rejected": ["nonsense"]}\n```'
        )

        stacks, _ = main._merge_mapper_result(PRESCAN, raw)

        assert "wildfly" in {s["pattern"] for s in stacks}


class TestBundleFor:
    def test_discovery_bundle_is_the_confirmed_stacks_in_stack_order(self):
        state = {
            "pattern": "stack-discovery",
            "companion_patterns_json": json.dumps(["java-8-to-25", "wildfly", "oracle-19c-to-23ai"]),
        }

        assert main._bundle_for(state) == ["wildfly", "oracle-19c-to-23ai", "java-8-to-25"]

    def test_discovery_never_appends_its_own_pattern(self):
        """stack-discovery has a `mapper` runner and no `re` runner, so putting it
        in the bundle would send the fan-out looking for one that isn't there."""
        state = {"pattern": "stack-discovery", "companion_patterns_json": json.dumps(["java-8-to-25"])}

        assert "stack-discovery" not in main._bundle_for(state)

    def test_discovery_with_nothing_confirmed_is_empty(self):
        state = {"pattern": "stack-discovery", "companion_patterns_json": "[]"}

        assert main._bundle_for(state) == []

    def test_migration_bundle_still_ends_with_its_primary(self):
        state = {
            "pattern": "java-8-to-25",
            "companion_patterns_json": json.dumps(["solr-4-to-9", "oracle-19c-to-23ai"]),
        }

        assert main._bundle_for(state) == ["oracle-19c-to-23ai", "solr-4-to-9", "java-8-to-25"]


class TestRunnerWiring:
    def test_every_detectable_stack_has_an_re_runner(self):
        """The fan-out indexes PATTERN_RUNNERS[stack]["re"] directly, so a
        detectable stack with no runner is a mid-run KeyError."""
        from agents import PATTERN_RUNNERS

        for pattern in stack_detector.STACK_ORDER:
            assert "re" in PATTERN_RUNNERS[pattern], f"{pattern} has no RE runner"

    def test_stack_discovery_has_a_mapper_and_no_plan_or_code(self):
        from agents import PATTERN_RUNNERS

        assert set(PATTERN_RUNNERS["stack-discovery"]) == {"mapper"} | {
            f"discover_{p}" for p in stack_detector.STACK_ORDER if p not in stack_detector.EXTRACTION_ONLY_PATTERNS}
        assert not {k for k in PATTERN_RUNNERS["stack-discovery"] if k.startswith(("plan", "code"))}

    def test_extraction_only_stacks_have_no_plan_or_code_runner(self):
        from agents import PATTERN_RUNNERS

        for pattern in stack_detector.EXTRACTION_ONLY_PATTERNS:
            assert set(PATTERN_RUNNERS[pattern]) == {"re"}

    def test_every_stack_has_a_label_for_its_document_heading(self):
        """_split_combined_sections locates a reviewer's edits by searching for
        the `## <label>` heading, so a stack falling back to its raw pattern id
        would still work but read badly in the document."""
        for pattern in stack_detector.STACK_ORDER:
            assert main._label(pattern) != pattern, f"{pattern} has no readable label"
