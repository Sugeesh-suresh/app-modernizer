"""
Unit tests for agents/shared/dependency_graph.py's deterministic (non-LLM)
dependency extraction and migration-group sequencing.
"""
from pathlib import Path

from agents.shared.dependency_graph import build_dependency_graph, to_markdown_section, to_text


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestJavaGraph:
    def test_independent_files_form_one_group(self, tmp_path):
        _write(tmp_path, "src/main/java/com/acme/A.java", "package com.acme;\nclass A {}\n")
        _write(tmp_path, "src/main/java/com/acme/B.java", "package com.acme;\nclass B {}\n")

        graph = build_dependency_graph(str(tmp_path), "java-8-to-25")

        assert set(graph["nodes"]) == {
            "src/main/java/com/acme/A.java",
            "src/main/java/com/acme/B.java",
        }
        assert graph["edges"] == []
        assert len(graph["groups"]) == 1
        assert set(graph["groups"][0]) == set(graph["nodes"])

    def test_dependant_file_is_sequenced_after_its_dependency(self, tmp_path):
        _write(tmp_path, "src/main/java/com/acme/Base.java", "package com.acme;\nclass Base {}\n")
        _write(
            tmp_path,
            "src/main/java/com/acme/Derived.java",
            "package com.acme;\nimport com.acme.Base;\nclass Derived extends Base {}\n",
        )

        graph = build_dependency_graph(str(tmp_path), "java-8-to-25")

        base = "src/main/java/com/acme/Base.java"
        derived = "src/main/java/com/acme/Derived.java"
        assert (derived, base) in graph["edges"]
        assert len(graph["groups"]) == 2
        assert graph["groups"][0] == [base]
        assert graph["groups"][1] == [derived]

    def test_empty_workspace_returns_empty_graph(self, tmp_path):
        graph = build_dependency_graph(str(tmp_path), "java-8-to-25")
        assert graph == {"nodes": [], "edges": [], "groups": []}

    def test_missing_workspace_dir_returns_empty_graph(self, tmp_path):
        graph = build_dependency_graph(str(tmp_path / "does-not-exist"), "java-8-to-25")
        assert graph == {"nodes": [], "edges": [], "groups": []}


class TestJspGraph:
    def test_static_include_creates_an_edge(self, tmp_path):
        _write(tmp_path, "header.jspf", "<h1>Header</h1>\n")
        _write(tmp_path, "index.jsp", '<%@ include file="header.jspf" %>\n<p>Body</p>\n')

        graph = build_dependency_graph(str(tmp_path), "jsp-to-react-bff")

        assert ("index.jsp", "header.jspf") in graph["edges"]
        assert graph["groups"][0] == ["header.jspf"]
        assert graph["groups"][1] == ["index.jsp"]

    def test_pages_sharing_a_taglib_land_in_a_shared_group(self, tmp_path):
        _write(tmp_path, "a.jsp", '<%@ taglib uri="http://acme.com/widgets" prefix="w" %>\n')
        _write(tmp_path, "b.jsp", '<%@ taglib uri="http://acme.com/widgets" prefix="w" %>\n')

        graph = build_dependency_graph(str(tmp_path), "jsp-to-react-bff")

        assert "taglib:http://acme.com/widgets" in graph["nodes"]
        assert ("a.jsp", "taglib:http://acme.com/widgets") in graph["edges"]
        assert ("b.jsp", "taglib:http://acme.com/widgets") in graph["edges"]


class TestTextRendering:
    def test_renders_groups_in_order_with_dependencies(self, tmp_path):
        _write(tmp_path, "src/main/java/com/acme/Base.java", "package com.acme;\nclass Base {}\n")
        _write(
            tmp_path,
            "src/main/java/com/acme/Derived.java",
            "package com.acme;\nimport com.acme.Base;\nclass Derived extends Base {}\n",
        )
        graph = build_dependency_graph(str(tmp_path), "java-8-to-25")

        text = to_text(graph)

        base = "src/main/java/com/acme/Base.java"
        derived = "src/main/java/com/acme/Derived.java"
        assert text.index("Group 1") < text.index(base) < text.index("Group 2") < text.index(derived)
        assert f"→ {base}  (Group 1)" in text

    def test_large_group_is_truncated(self, tmp_path):
        for i in range(4):
            _write(tmp_path, f"src/main/java/com/acme/C{i}.java", f"package com.acme;\nclass C{i} {{}}\n")
        graph = build_dependency_graph(str(tmp_path), "java-8-to-25")

        text = to_text(graph, max_nodes_per_group=2)

        assert "…and 2 more" in text

    def test_empty_graph_renders_a_placeholder(self):
        text = to_text({"nodes": [], "edges": [], "groups": []})
        assert "No structural dependencies" in text

    def test_markdown_section_embeds_a_plain_text_block_not_mermaid(self, tmp_path):
        _write(tmp_path, "src/main/java/com/acme/A.java", "package com.acme;\nclass A {}\n")
        graph = build_dependency_graph(str(tmp_path), "java-8-to-25")

        section = to_markdown_section(graph, "java-8-to-25")

        assert "```text" in section
        assert "mermaid" not in section.lower()
