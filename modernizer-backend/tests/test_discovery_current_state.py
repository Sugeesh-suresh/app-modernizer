"""
Stack discovery documents describe the repository as it is: no migration,
upgrade or advisory language survives, and every fact does.
"""
import pytest

from agents.shared import current_state as cs
from agents.shared import dependency_graph, stack_detector


def test_headings_about_migration_or_advice_are_removed_with_their_body():
    text = ("## Overview\nThe app sends mail.\n## Migration Risks\n- risky\n### Detail\nmore\n"
            "## Next Steps\n1. do it\n## Configuration\n- `smtp.host` in `mail.properties`\n")
    out, removed = cs.scrub(text)
    assert out == "## Overview\nThe app sends mail.\n## Configuration\n- `smtp.host` in `mail.properties`\n"
    assert removed == ["## Migration Risks", "## Next Steps"]


def test_only_the_offending_sentence_of_a_paragraph_is_removed():
    out, _ = cs.scrub("The DAO reads `ORDERS`. It should be replaced with JPA. Rows are paged by 50.")
    assert out == "The DAO reads `ORDERS`. Rows are paged by 50."


def test_list_items_with_their_continuations_and_children_are_removed():
    text = ("- Uses JDBC directly\n- Uses `sun.misc.BASE64Encoder`, which is removed in Java 9\n"
            "  and must be remediated\n  - child note\n- Pools via DBCP\n")
    out, removed = cs.scrub(text)
    assert out == "- Uses JDBC directly\n- Pools via DBCP\n"
    assert len(removed) == 1


def test_table_rows_and_migration_tables_are_removed_but_headers_kept():
    rows = "| Lib | Version |\n|---|---|\n| ojdbc8 | 19.3 |\n| log4j | 1.2.17 (end of life) |\n"
    assert cs.scrub(rows)[0] == "| Lib | Version |\n|---|---|\n| ojdbc8 | 19.3 |\n"
    table = "| Item | Migration Impact |\n|---|---|\n| a | b |\nAfter.\n"
    assert cs.scrub(table)[0] == "After.\n"
    emptied = "| Queue | Target |\n|---|---|\n| q | Pub/Sub topic |\nAfter.\n"
    assert cs.scrub(emptied)[0] == "After.\n"


@pytest.mark.parametrize("fact", [
    "Schema is created by Flyway migration scripts in `db/migration`.",
    "The `UpgradeService` class handles `/account/upgrade` requests.",
    "```text\nmigrate everything to Java 25\n```",
    "The compiler is configured with `<source>1.8</source>` in `pom.xml`.",
    "The app recommends products from the `RECOMMENDATIONS` table.",
    "<!-- SECTION: BRD -->",
])
def test_facts_identifiers_and_code_are_kept(fact):
    assert cs.scrub(fact)[0] == fact


@pytest.mark.parametrize("advice", [
    "Moving to Java 25 is recommended.",
    "Oracle 19c → 23ai changes the JSON type.",
    "Solr 9 removes the Trie fields.",
    "Consider replacing EMS with a cloud broker.",
    "The target platform is Spring Boot.",
    "This dependency is deprecated.",
    "Modernisation would simplify deployment.",
])
def test_advice_is_detected(advice):
    assert cs.is_migration_language(advice)


def test_the_section_markers_survive_a_removed_heading():
    text = "## Recommendations\n- x\n<!-- SECTION: BRD -->\n# BRD\nscope\n"
    assert cs.scrub(text)[0] == "<!-- SECTION: BRD -->\n# BRD\nscope\n"


def test_scrub_is_idempotent():
    text = "## A\nFacts. Should be migrated soon.\n- a\n- upgrade b\n"
    once = cs.scrub(text)[0]
    assert cs.scrub(once) == (once, [])


def test_pattern_ids_become_stack_ids():
    assert cs.neutral_ids("`oracle-19c-to-23ai` and java-8-to-25, not my-java-8-to-25x") == \
        "`oracle` and java, not my-java-8-to-25x"


def test_stack_labels_and_inventory_name_stacks_not_migrations():
    # A stack's own name is never scrubbed once that stack has been detected.
    for stack_id, label in stack_detector.STACK_LABELS.items():
        assert not cs.is_migration_language(label, cs.targets_in_repo(f"stacks: {stack_id}")), label
    table = stack_detector.to_markdown([{"pattern": "solr", "label": "Apache Solr", "kind": "search",
                                         "evidence": ["a: b"]}])
    assert "`solr`" in table and "migration" not in table.lower()
    assert all(not s.pattern[0].isdigit() and "-to-" not in s.pattern for s in stack_detector.CATALOG)


def test_discovery_dependency_graph_is_a_build_order():
    graph = {"nodes": ["a", "b"], "edges": [["b", "a"]], "groups": [["a"], ["b"]]}
    section = dependency_graph.to_markdown_section(graph, "java-8-to-25", discovery=True)
    assert section.startswith("## Dependency Graph & Build Order") and "migrat" not in section.lower()
    assert "Migration Groups" in dependency_graph.to_markdown_section(graph, "java-8-to-25")


def test_a_target_technology_the_repository_uses_is_kept():
    """A service that really reads BigQuery must be able to say "Google Cloud"."""
    facts = "pds-javaflux/pom.xml (maven): com.google.cloud:google-cloud-bigquery, com.ibm.db2:jcc@11.5.8.0"
    keep = cs.targets_in_repo(facts)
    assert keep == frozenset({"google cloud"})
    text = "Items are exported to Google Cloud BigQuery (EV-java-0003). Moving to Java 25 would help."
    assert cs.scrub(text, keep)[0] == "Items are exported to Google Cloud BigQuery (EV-java-0003)."
    assert cs.scrub(text)[0] == ""                                   # without the repository's facts: removed
    assert cs.targets_in_repo("x/pom.xml (maven): org.apache.solr:solr-solrj@9.4.0; properties: java.version=25") \
        == frozenset({"solr 9", "java 25"})
    assert cs.targets_in_repo("pom.xml (maven): org.apache.solr:solr-solrj@4.10.4") == frozenset()


def test_a_stack_detected_only_from_configuration_keeps_its_name():
    keep = cs.targets_in_repo("app/application.properties (no manifest)\nstacks: oracle gcs java")
    assert "google cloud" in keep
    assert cs.scrub("## Google Cloud Storage\nExports are written to `gs://pds-exports`.", keep)[0].startswith(
        "## Google Cloud Storage")
