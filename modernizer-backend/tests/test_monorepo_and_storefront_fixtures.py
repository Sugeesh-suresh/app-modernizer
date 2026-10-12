"""The two applications the migration pipeline was driven end to end on (Gemini CLI path): what the
deterministic steps must find in them before any model is involved.

- orders-jsp-oracle-monorepo: parent pom + two module poms (Spring 4 REST WAR on Oracle, JSP WAR calling it with
  jQuery AJAX, XMLHttpRequest, fetch and a server-side RestTemplate);
- storefront-thymeleaf-solr4-oracle: Spring Boot 1.5 + Thymeleaf templates, JPA on Oracle, SolrJ 4 search APIs.
"""
from pathlib import Path

from agents.java_8_to_11.preflight import maven_roots
from agents.shared import companion_detector, migration_inventory

FIXTURES = Path(__file__).parent / "fixtures"
ORDERS = FIXTURES / "orders-jsp-oracle-monorepo"
STORE = FIXTURES / "storefront-thymeleaf-solr4-oracle"


def _companions(repo: Path) -> set[str]:
    return {r["pattern"] for r in companion_detector.detect_companions(str(repo), "java-8-to-25")}


def test_the_monorepo_is_built_from_its_parent_pom_once():
    assert maven_roots(ORDERS) == [ORDERS]              # the aggregator, not each module on its own


def test_oracle_is_the_monorepos_only_companion():
    assert _companions(ORDERS) == {"oracle-19c-to-23ai"}


def test_the_storefront_needs_both_oracle_and_solr():
    assert _companions(STORE) == {"oracle-19c-to-23ai", "solr-4-to-9"}


def test_the_inventories_see_both_modules_and_the_legacy_apis():
    java = migration_inventory.to_document("java-8-to-25", str(ORDERS), 400)
    for path in ("order-services/pom.xml", "order-web/pom.xml", "OrderServicesClient.java", "OrderDao.java"):
        assert path in java, path
    oracle = migration_inventory.to_document("oracle-19c-to-23ai", str(ORDERS), 400)
    assert "V2__order_pkg.sql" in oracle and "LONG" in oracle          # the PL/SQL package and the LONG column
    solr = migration_inventory.to_document("solr-4-to-9", str(STORE), 400)
    for token in ("SolrJ 4 server classes", "SolrConfig.java", "schema.xml", "solrconfig.xml"):
        assert token in solr, token


HIBERNATE = FIXTURES / "orders-jsp-hibernate-monorepo"


def test_the_java11_inventory_sees_the_hibernate_variants_frameworks():
    """orders-jsp-hibernate-monorepo: the monorepo with a Hibernate 4.3 data layer (orm.hibernate4,
    HQL `?` parameters, Criteria), used for the Java 8 -> 11 run that keeps the JSP WARs as they are."""
    from agents.java_8_to_11 import inventory
    doc = inventory.to_document(inventory.build(str(HIBERNATE)))
    assert "org.hibernate:hibernate-core | 4.3.11.Final" in doc and "must move" in doc
    assert maven_roots(HIBERNATE) == [HIBERNATE]
