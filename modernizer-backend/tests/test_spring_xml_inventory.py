"""The Java 8 -> 25 inventory says what each Spring XML context defines, so a planner that cannot read the code
still knows the beans, scans, JNDI names and MVC set-up it has to carry over (agents/shared/migration_inventory.py)."""
from pathlib import Path

from agents.shared import migration_inventory as mi

FIXTURE = Path(__file__).parent / "fixtures" / "shop-jsp-jboss-war"


def test_each_spring_xml_context_is_summarised():
    doc = mi.to_document("java-8-to-25", str(FIXTURE))
    section = doc.split("## Spring XML Bean Definitions", 1)[1].split("\n## ", 1)[0]
    assert "applicationContext.xml" in section and "shop-servlet.xml" in section
    assert "JNDI java:jboss/datasources/ShopDS" in section
    assert "component-scan com.acme.shop.service,com.acme.shop.dao" in section
    assert "localeResolver → SessionLocaleResolver" in section and "InternalResourceViewResolver" in section
    assert "mvc:annotation-driven" in section and "tx:annotation-driven" in section
    assert "properties classpath:schema.sql" in section                     # the test context's script
    assert "properties /static/" not in section                              # mvc:resources is not a placeholder file


def test_a_repository_without_spring_xml_says_so(tmp_path):
    (tmp_path / "src/main/java").mkdir(parents=True)
    (tmp_path / "src/main/java/A.java").write_text("class A {}")
    (tmp_path / "pom.xml").write_text("<project/>")
    doc = mi.to_document("java-8-to-25", str(tmp_path))
    assert "no Spring XML context" in doc
