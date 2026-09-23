"""
Unit tests for agents/shared/stack_detector.py's deterministic (non-LLM)
detection of every technology stack in an uploaded repository — pass 1 of the
stack-discovery pattern's dependency mapper.
"""
from pathlib import Path

from agents.shared import stack_detector
from agents.shared.stack_detector import detect_stacks, to_markdown


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _legacy_repo(root: Path) -> None:
    """The scenario this pattern exists for: Java + JSP + WildFly + Oracle +
    Solr + TIBCO all in one repository."""
    _write(
        root, "pom.xml",
        """<project>
          <packaging>war</packaging>
          <properties><maven.compiler.source>1.8</maven.compiler.source></properties>
          <dependencies>
            <dependency><groupId>com.oracle.database.jdbc</groupId><artifactId>ojdbc8</artifactId></dependency>
            <dependency><groupId>org.apache.solr</groupId><artifactId>solr-solrj</artifactId></dependency>
            <dependency><groupId>com.tibco</groupId><artifactId>tibjms</artifactId></dependency>
          </dependencies>
          <build><plugins>
            <plugin><artifactId>wildfly-maven-plugin</artifactId></plugin>
          </plugins></build>
        </project>""",
    )
    _write(
        root, "src/main/webapp/WEB-INF/jboss-deployment-structure.xml",
        '<jboss-deployment-structure xmlns="urn:jboss:deployment-structure:1.2"/>',
    )
    _write(root, "src/main/webapp/login.jsp", '<%@ page contentType="text/html" %>')
    _write(root, "src/main/java/com/acme/Dao.java", "import oracle.jdbc.OracleDriver;\nclass Dao {}")


class TestDetectStacks:
    def test_finds_every_stack_in_a_mixed_legacy_repo(self, tmp_path):
        _legacy_repo(tmp_path)

        stacks = detect_stacks(str(tmp_path))

        assert {s["pattern"] for s in stacks} == {
            "wildfly", "oracle-19c-to-23ai", "solr-4-to-9",
            "tibco-ems-to-pubsub", "jsp-to-react-bff", "java-8-to-25",
        }

    def test_every_stack_carries_evidence_and_a_label(self, tmp_path):
        _legacy_repo(tmp_path)

        for stack in detect_stacks(str(tmp_path)):
            assert stack["evidence"], f"{stack['pattern']} reported with no evidence"
            assert stack["label"]
            # Every evidence line names the file it came from, or a reviewer
            # cannot check the finding.
            for line in stack["evidence"]:
                assert ":" in line

    def test_results_follow_stack_order(self, tmp_path):
        _legacy_repo(tmp_path)

        found = [s["pattern"] for s in detect_stacks(str(tmp_path))]

        assert found == [p for p in stack_detector.STACK_ORDER if p in found]

    def test_wildfly_is_flagged_extraction_only(self, tmp_path):
        _legacy_repo(tmp_path)

        stacks = {s["pattern"]: s for s in detect_stacks(str(tmp_path))}

        assert stacks["wildfly"]["extraction_only"] is True
        assert stacks["java-8-to-25"]["extraction_only"] is False

    def test_detects_wildfly_from_server_config_alone(self, tmp_path):
        _write(tmp_path, "config/standalone.xml", '<server xmlns="urn:jboss:domain:14.0"/>')

        assert "wildfly" in {s["pattern"] for s in detect_stacks(str(tmp_path))}

    def test_detects_jsp_from_tag_files_with_no_pom(self, tmp_path):
        _write(tmp_path, "web/WEB-INF/tags/panel.tag", "<%@ attribute name='title' %>")

        assert "jsp-to-react-bff" in {s["pattern"] for s in detect_stacks(str(tmp_path))}

    def test_bare_jboss_mentions_do_not_trigger_wildfly(self, tmp_path):
        """org.jboss.logging arrives transitively in plenty of applications that
        never run on WildFly, so it must not be evidence on its own."""
        _write(
            tmp_path, "pom.xml",
            "<project><dependencies><dependency>"
            "<groupId>org.jboss.logging</groupId><artifactId>jboss-logging</artifactId>"
            "</dependency></dependencies></project>",
        )

        assert "wildfly" not in {s["pattern"] for s in detect_stacks(str(tmp_path))}

    def test_empty_repo_yields_nothing(self, tmp_path):
        _write(tmp_path, "README.md", "# nothing to see")

        assert detect_stacks(str(tmp_path)) == []

    def test_missing_workspace_yields_nothing(self, tmp_path):
        assert detect_stacks(str(tmp_path / "does-not-exist")) == []

    def test_build_output_is_not_scanned(self, tmp_path):
        """A driver inside target/ is a build artifact of something else, not
        evidence that this repository uses it."""
        _write(tmp_path, "target/classes/com/acme/Dao.java", "import oracle.jdbc.OracleDriver;")

        assert detect_stacks(str(tmp_path)) == []


class TestToMarkdown:
    def test_renders_a_row_per_stack_with_evidence(self, tmp_path):
        _legacy_repo(tmp_path)
        stacks = detect_stacks(str(tmp_path))

        table = to_markdown(stacks)

        assert "## Detected Technology Stacks" in table
        for stack in stacks:
            assert stack["label"] in table
        assert "extraction only" in table  # wildfly's caveat reaches the document

    def test_evidence_backticks_are_not_nested(self, tmp_path):
        """detect_stacks already puts the matched text in backticks; wrapping the
        whole line again would break the code span in the rendered document."""
        _legacy_repo(tmp_path)

        table = to_markdown(detect_stacks(str(tmp_path)))

        assert "``" not in table

    def test_pipes_in_evidence_are_escaped(self):
        stacks = [{
            "pattern": "java-8-to-25", "label": "Java",
            "evidence": ["build.gradle: matched `a|b`"], "extraction_only": False,
        }]

        assert r"a\|b" in to_markdown(stacks)

    def test_empty_inventory_says_so_without_claiming_an_empty_repo(self):
        text = to_markdown([])

        assert "No known stack was detected" in text
        assert "repository is empty" in text  # explicitly disclaimed
