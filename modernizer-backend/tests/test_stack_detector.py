"""
Unit tests for agents/shared/stack_detector.py's deterministic (non-LLM)
detection of every technology stack in an uploaded repository — pass 1 of the
stack-discovery pattern's dependency mapper.
"""
from pathlib import Path

import pytest

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

        assert {s["pattern"] for s in stacks} == {"wildfly", "oracle", "solr", "tibco-ems", "jsp", "java"}

    def test_every_stack_carries_evidence_and_a_label(self, tmp_path):
        _legacy_repo(tmp_path)

        for stack in detect_stacks(str(tmp_path)):
            assert stack["evidence"], f"{stack['pattern']} reported with no evidence"
            assert stack["label"]
            # Every evidence line names the file it came from, or a reviewer
            # cannot check the finding.
            for line in stack["evidence"]:
                assert ":" in line

    def test_results_follow_kind_then_catalog_order(self, tmp_path):
        _legacy_repo(tmp_path)

        found = [s["pattern"] for s in detect_stacks(str(tmp_path))]

        assert found == [p for p in stack_detector.STACK_ORDER if p in found]

    def test_each_stack_names_its_kind_and_checklist(self, tmp_path):
        _legacy_repo(tmp_path)

        stacks = {s["pattern"]: s for s in detect_stacks(str(tmp_path))}

        assert (stacks["oracle"]["kind"], stacks["oracle"]["reference"]) == ("database", "oracle.md")
        assert (stacks["java"]["kind"], stacks["java"]["reference"]) == ("application", "java.md")
        assert stacks["wildfly"]["reference"] == ""        # documented by its own runner

    def test_detects_wildfly_from_server_config_alone(self, tmp_path):
        _write(tmp_path, "config/standalone.xml", '<server xmlns="urn:jboss:domain:14.0"/>')

        assert "wildfly" in {s["pattern"] for s in detect_stacks(str(tmp_path))}

    def test_detects_jsp_from_tag_files_with_no_pom(self, tmp_path):
        _write(tmp_path, "web/WEB-INF/tags/panel.tag", "<%@ attribute name='title' %>")

        assert "jsp" in {s["pattern"] for s in detect_stacks(str(tmp_path))}

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
        assert "`wildfly`" in table and "migration" not in table.lower()

    def test_evidence_backticks_are_not_nested(self, tmp_path):
        """detect_stacks already puts the matched text in backticks; wrapping the
        whole line again would break the code span in the rendered document."""
        _legacy_repo(tmp_path)

        table = to_markdown(detect_stacks(str(tmp_path)))

        assert "``" not in table

    def test_pipes_in_evidence_are_escaped(self):
        stacks = [{
            "pattern": "java", "label": "Java", "kind": "application",
            "evidence": ["build.gradle: matched `a|b`"],
        }]

        assert r"a\|b" in to_markdown(stacks)

    def test_empty_inventory_says_so_without_claiming_an_empty_repo(self):
        text = to_markdown([])

        assert "No stack was detected" in text
        assert "repository is empty" in text  # explicitly disclaimed


class TestStacksComeFromTheRepository:
    """Stacks are derived from manifests, imports, script includes and languages,
    not limited to a fixed list."""

    def _mixed(self, root: Path) -> None:
        _write(root, "pom.xml", "<project><packaging>war</packaging><dependencies>"
               "<dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId>"
               "<version>42.2.5</version></dependency></dependencies></project>")
        _write(root, "src/main/java/a/OrderController.java",
               "package a;\nimport org.springframework.stereotype.Controller;\n// import com.mongodb.X;\nclass O {}")
        _write(root, "src/main/webapp/index.jsp",
               '<%@ page %>\n<script src="js/lib/backbone-min.js"></script>\n<script src="js/lib/jquery-1.11.3.min.js"></script>')
        _write(root, "src/main/webapp/js/lib/backbone-min.js", "/* lib */")
        _write(root, "src/main/webapp/js/main.js",
               "define(['backbone', 'underscore', './views/a'], function (Backbone) { return 1; });")
        _write(root, "src/main/webapp/js/views/a.js", "define(['backbone'], function (B) {});")
        _write(root, "scripts/sync.py", "import os\nimport requests\n")
        _write(root, "scripts/report.py", "from requests import get\n")

    def test_jsp_backbone_java_postgres_and_python_are_each_a_stack(self, tmp_path):
        self._mixed(tmp_path)

        stacks = {s["pattern"]: s for s in detect_stacks(str(tmp_path))}

        assert list(stacks) == ["postgresql", "jsp", "backbone", "java", "python"]
        assert stacks["backbone"]["reference"] == "spa-frontend.md"
        evidence = " ".join(stacks["backbone"]["evidence"])
        assert "imports `backbone` (2 files)" in evidence          # RequireJS define([...])
        assert "loads `backbone` script" in evidence and "commits `backbone` library" in evidence
        assert stacks["python"]["label"] == "Python code" and stacks["python"]["reference"] == "general.md"
        assert "jquery" not in stacks          # inside the JSP/Backbone front end, not a stack of its own
        assert "mongodb" not in stacks         # only in a comment

    def test_react_and_a_node_service_from_package_json(self, tmp_path):
        _write(tmp_path, "web/package.json", '{"dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"}}')
        _write(tmp_path, "web/src/App.tsx", "import React from 'react';\nexport const App = () => null;")
        _write(tmp_path, "api/package.json", '{"dependencies": {"express": "4.18.2", "kafkajs": "2.2.4"}}')
        _write(tmp_path, "api/index.js", "const express = require('express');")

        stacks = {s["pattern"]: s for s in detect_stacks(str(tmp_path))}

        assert {"react", "nodejs", "kafka"} <= set(stacks)
        assert "web/package.json: declares `react` ^18.2.0" in stacks["react"]["evidence"]
        assert "typescript" not in stacks and "javascript" not in stacks    # accounted for

    def test_an_uncatalogued_language_still_becomes_a_stack(self, tmp_path):
        _write(tmp_path, "svc/main.go", "package main")
        _write(tmp_path, "svc/handler.go", "package main")
        _write(tmp_path, "go.mod", "module x\nrequire (\n  github.com/gin-gonic/gin v1.9.1\n)\n")

        stacks = {s["pattern"]: s for s in detect_stacks(str(tmp_path))}

        assert stacks["go"]["label"] == "Go code" and stacks["go"]["kind"] == "language"


class TestFingerprint:
    def test_manifests_imports_scripts_and_languages(self, tmp_path):
        from agents.shared import repo_fingerprint as rf
        TestStacksComeFromTheRepository()._mixed(tmp_path)

        fp = rf.fingerprint(str(tmp_path))

        assert fp["languages"]["JavaScript"]["files"] == 3 and fp["languages"]["Python"]["files"] == 2
        assert fp["manifests"][0]["dependencies"] == [
            {"name": "org.postgresql:postgresql", "version": "42.2.5", "scope": ""}]
        assert set(fp["imports"]["python"]) == {"requests"}                      # stdlib dropped (AST)
        assert set(fp["imports"]["java"]) == {"org.springframework.stereotype"}  # comment ignored
        assert set(fp["imports"]["javascript"]) == {"backbone", "underscore"}    # relative paths dropped
        assert set(fp["scripts"]) == {"backbone", "jquery"}
        assert fp["vendored"] == {"backbone": ["src/main/webapp/js/lib/backbone-min.js"]}
        md = rf.to_markdown(fp)
        assert "## Repository Fingerprint" in md and "`org.postgresql:postgresql` | 42.2.5" in md

    def test_python_strings_are_not_imports(self, tmp_path):
        from agents.shared import repo_fingerprint as rf
        _write(tmp_path, "a.py", 'DOC = "import django"\nimport flask\n')

        assert set(rf.fingerprint(str(tmp_path))["imports"]["python"]) == {"flask"}

    @pytest.mark.parametrize("name, manifest, expected", [
        ("requirements.txt", "Django==3.2  # web\nrequests>=2\n-r other.txt\n", ["django", "requests"]),
        ("pyproject.toml", '[project]\ndependencies = ["fastapi>=0.1"]\n', ["fastapi"]),
        ("build.gradle", "dependencies { implementation 'org.hibernate:hibernate-core:5.4.0' }", ["org.hibernate:hibernate-core"]),
        ("go.mod", "module m\nrequire github.com/gin-gonic/gin v1.9.1\n", ["github.com/gin-gonic/gin"]),
        ("App.csproj", '<Project><ItemGroup><PackageReference Include="Dapper" Version="2.0" /></ItemGroup></Project>', ["Dapper"]),
        ("Gemfile", "gem 'rails', '7.0'\n", ["rails"]),
        ("bower.json", '{"dependencies": {"backbone": "1.1.2"}}', ["backbone"]),
    ])
    def test_each_manifest_kind_is_parsed(self, tmp_path, name, manifest, expected):
        from agents.shared import repo_fingerprint as rf
        _write(tmp_path, name, manifest)

        deps = rf.fingerprint(str(tmp_path))["manifests"][0]["dependencies"]

        assert [d["name"] for d in deps] == expected
