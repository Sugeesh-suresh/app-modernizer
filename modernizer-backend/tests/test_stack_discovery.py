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
    {"pattern": "oracle", "label": "Oracle Database", "kind": "database", "reference": "oracle.md",
     "evidence": ["pom.xml: matched `ojdbc8`"]},
    {"pattern": "solr", "label": "Apache Solr", "kind": "search", "reference": "solr.md",
     "evidence": ["pom.xml: matched `org.apache.solr`"]},
    {"pattern": "java", "label": "Java application", "kind": "application", "reference": "java.md",
     "evidence": ["src/A.java: present"]},
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
            "pattern": "oracle", "label": "Oracle Database",
            "evidence": ["pom.xml:41 ojdbc8 19.3.0.0 (compile scope)"],
        }])

        stacks, _ = main._merge_mapper_result(PRESCAN, raw)

        oracle = next(s for s in stacks if s["pattern"] == "oracle")
        assert oracle["evidence"][0].startswith("pom.xml:41")
        assert "pom.xml: matched `ojdbc8`" in oracle["evidence"]

    def test_a_migration_pattern_id_is_read_as_its_stack(self):
        raw = _mapper_reply([{"pattern": "oracle-19c-to-23ai", "label": "Oracle 19c → 23ai",
                              "evidence": ["pom.xml:41 ojdbc8"]}])

        stacks, _ = main._merge_mapper_result(PRESCAN, raw)

        assert [s["pattern"] for s in stacks].count("oracle") == 1
        assert all("23ai" not in s["label"] for s in stacks)

    def test_an_older_prescan_with_migration_ids_gets_stack_ids_and_labels(self):
        old = [{"pattern": "java-8-to-25", "label": "Java 8 → Java 25", "evidence": ["src/A.java: present"],
                "extraction_only": False}]

        stacks, _ = main._merge_mapper_result(old, "no json")

        assert stacks == [{"pattern": "java", "label": "Java application", "kind": "application",
                           "reference": "java.md", "evidence": ["src/A.java: present"]}]

    def test_any_stack_the_mapper_cites_is_documented(self):
        """Stacks come from the repository, not a fixed list: an id nothing in the
        catalog knows is still a stack, with the mapper's label and kind and the
        general checklist."""
        raw = _mapper_reply([
            {"pattern": "Spring Batch", "label": "Spring Batch jobs", "kind": "service",
             "evidence": ["pom.xml: spring-batch-core"]},
            {"pattern": "kafka", "label": "Kafka", "kind": "messaging", "evidence": ["pom.xml: kafka-clients"]},
        ])

        stacks, _ = main._merge_mapper_result(PRESCAN, raw)

        by_id = {s["pattern"]: s for s in stacks}
        assert by_id["spring-batch"] == {"pattern": "spring-batch", "label": "Spring Batch jobs",
                                         "kind": "service", "reference": "general.md",
                                         "evidence": ["pom.xml: spring-batch-core"]}
        assert by_id["kafka"]["label"] == "Apache Kafka" and by_id["kafka"]["reference"] == "messaging.md"

    def test_a_stack_citing_only_files_that_do_not_exist_is_dropped(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        raw = _mapper_reply([
            {"pattern": "struts", "label": "Struts", "kind": "web-tier", "evidence": ["src/struts.xml: <struts>"]},
            {"pattern": "maven", "label": "Maven build", "kind": "other", "evidence": ["pom.xml:1 <project>"]},
        ])

        stacks, notes = main._merge_mapper_result(PRESCAN, raw, str(tmp_path))

        assert "struts" not in {s["pattern"] for s in stacks}
        assert "maven" in {s["pattern"] for s in stacks}
        assert any("struts" in n and "exist" in n for n in notes)

    def test_stack_without_evidence_is_dropped(self):
        raw = _mapper_reply([{"pattern": "wildfly", "label": "WildFly", "evidence": []}])

        stacks, notes = main._merge_mapper_result(PRESCAN, raw)

        assert "wildfly" not in {s["pattern"] for s in stacks}
        assert any("without evidence" in n for n in notes)

    def test_rejection_with_a_reason_removes_the_stack(self):
        raw = _mapper_reply([], [
            {"pattern": "solr-4-to-9", "reason": "only match is commented out at pom.xml:88"},
        ])

        stacks, notes = main._merge_mapper_result(PRESCAN, raw)

        assert "solr" not in {s["pattern"] for s in stacks}
        assert any("commented out" in n for n in notes)

    def test_rejection_without_a_reason_leaves_the_prescan_standing(self):
        raw = _mapper_reply([], [{"pattern": "java", "reason": ""}])

        stacks, notes = main._merge_mapper_result(PRESCAN, raw)

        assert "java" in {s["pattern"] for s in stacks}
        assert any("without a reason" in n for n in notes)

    def test_unparseable_reply_preserves_every_prescan_finding(self):
        """The failure that matters most: silently returning nothing here would
        produce an empty document that looks like a clean repository."""
        stacks, notes = main._merge_mapper_result(PRESCAN, "the model rambled and emitted no JSON")

        assert {s["pattern"] for s in stacks} == {s["pattern"] for s in PRESCAN}
        assert any("could not be parsed" in n for n in notes)

    def test_result_is_ordered_by_kind(self):
        raw = _mapper_reply([
            {"pattern": "wildfly", "label": "WildFly", "evidence": ["standalone.xml: found"]},
            {"pattern": "backbone", "label": "Backbone", "evidence": ["js/app.js: define(['backbone'])"]},
        ])

        stacks, _ = main._merge_mapper_result(PRESCAN, raw)

        assert [s["pattern"] for s in stacks] == ["wildfly", "oracle", "solr", "backbone", "java"]

    def test_malformed_entries_are_skipped_not_fatal(self):
        raw = (
            '```json\n{"stacks": ["a string", null, 42, '
            '{"pattern": "wildfly", "label": "W", "evidence": ["f: x"]}], '
            '"rejected": ["nonsense"]}\n```'
        )

        stacks, _ = main._merge_mapper_result(PRESCAN, raw)

        assert "wildfly" in {s["pattern"] for s in stacks}


class TestBundleFor:
    def test_discovery_bundle_is_the_confirmed_stacks_in_document_order(self):
        recs = [{"pattern": p} for p in ("wildfly", "oracle", "backbone", "java", "python")]
        state = {
            "pattern": "stack-discovery",
            "companion_recommendations_json": json.dumps(recs),
            "companion_patterns_json": json.dumps(["python", "java", "wildfly", "backbone"]),
        }

        assert main._bundle_for(state) == ["wildfly", "backbone", "java", "python"]

    def test_discovery_never_appends_its_own_pattern(self):
        state = {"pattern": "stack-discovery", "companion_recommendations_json": json.dumps([{"pattern": "java"}]),
                 "companion_patterns_json": json.dumps(["java"])}

        assert main._bundle_for(state) == ["java"]

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
    def test_stack_discovery_has_a_mapper_and_one_discovery_agent(self):
        from agents import PATTERN_RUNNERS

        assert set(PATTERN_RUNNERS["stack-discovery"]) == {
            "mapper", "discover", "discover_unit", "discover_merge", "po_brd", "ea_spec", "rules"}

    def test_dedicated_runners_exist(self):
        from agents import PATTERN_RUNNERS

        for runner_pattern, step in stack_detector.DEDICATED_RUNNERS.values():
            assert step in PATTERN_RUNNERS[runner_pattern]

    def test_every_catalog_checklist_exists(self):
        from pathlib import Path
        refs = Path(main.__file__).parent / "agents" / "skills" / "stack-discovery-re" / "references"
        for spec in stack_detector.CATALOG:
            if spec.pattern not in stack_detector.DEDICATED_RUNNERS:
                assert (refs / spec.reference).is_file(), spec
        for kind in stack_detector.KIND_ORDER + ("other",):
            assert (refs / stack_detector.reference_for("unknown-id", kind)).is_file(), kind

    def test_every_stack_has_a_label_for_its_document_heading(self):
        for pattern in stack_detector.STACK_ORDER:
            assert main._label(pattern, True) != pattern, f"{pattern} has no readable label"
        assert main._label("struts", True, {"struts": "Apache Struts"}) == "Apache Struts"


@pytest.mark.parametrize("raw, expected", [
    ("# Inv\n- a\n\n## Machine-Readable Result\n\n```json\n{\"stacks\": []}\n```", "# Inv\n- a"),
    ("Example:\n```json\n{\"x\": 1}\n```\nMore prose.\n```json\n{\"stacks\": []}\n```",
     "Example:\n```json\n{\"x\": 1}\n```\nMore prose."),
    ("Only prose, no block.", "Only prose, no block."),
    ("```json\n{\"stacks\": []}\n```\nprose after the block", "```json\n{\"stacks\": []}\n```\nprose after the block"),
])
def test_only_the_trailing_result_block_is_cut_from_the_prose(raw, expected):
    assert main._without_result_block(raw) == expected


class TestEndToEndFindings:
    """Defects found by the end-to-end run through the real UI."""

    def test_evidence_the_mapper_restates_is_not_listed_twice(self):
        raw = _mapper_reply([{"pattern": "oracle", "label": "Oracle Database",
                              "evidence": ["pom.xml: matched ojdbc8", "pom.xml — matched `ojdbc8`"]}])

        stacks, _ = main._merge_mapper_result(PRESCAN, raw)

        assert next(s for s in stacks if s["pattern"] == "oracle")["evidence"] == ["pom.xml: matched ojdbc8"]

    def test_the_inventory_table_uses_no_raw_html(self):
        table = stack_detector.to_markdown([{"pattern": "java", "label": "Java application", "kind": "application",
                                             "evidence": ["a.java: present", "b.java: present"]}])
        assert "<br>" not in table and "`a.java` — present; `b.java` — present" in table

    def test_the_mappers_headings_nest_under_the_inventory(self, monkeypatch):
        import asyncio
        from agents import APP_NAME, USER_ID, session_service
        state = main._initial_state("stack-discovery", "/tmp/none", "/tmp/none", "[]", "bigbang", False, False,
                                    json.dumps(PRESCAN))
        sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id

        async def mapper(session_id, step, pattern, message, sse_event_type):
            await main._update_state(session_id, {"stack_inventory": "# Technology Stack Inventory\n## Shape\nx\n"
                                                  + _mapper_reply([])})

        monkeypatch.setattr(main, "_run_step", mapper)
        asyncio.run(main._run_stack_mapping(sid))
        inventory = asyncio.run(main._get_state(sid))["stack_inventory_markdown"]
        assert "\n### Technology Stack Inventory\n#### Shape" in inventory
        assert not [l for l in inventory.splitlines() if l.startswith("# ")]
