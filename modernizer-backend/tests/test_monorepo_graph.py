"""
Tests for multi-module (monorepo) dependency-graph extraction.

The migration groups this produces are what the plan is sequenced from, so a
monorepo whose modules are not resolved is sequenced against a graph of
individual files with no build order in it at all. These tests pin the three
behaviours that matter: the reactor order is real, a single-module project is not
regressed into module granularity, and nothing is invented where the build system
cannot be read statically.
"""
from pathlib import Path

from agents.shared import dependency_graph as dg

NS = 'xmlns="http://maven.apache.org/POM/4.0.0"'


def _w(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _pom(artifact: str, parent: str = "", deps: tuple[str, ...] = (),
         modules: tuple[str, ...] = (), ns: bool = True) -> str:
    parent_el = (
        f"<parent><groupId>com.acme</groupId><artifactId>{parent}</artifactId></parent>"
        if parent else ""
    )
    mods = (
        "<modules>" + "".join(f"<module>{m}</module>" for m in modules) + "</modules>"
        if modules else ""
    )
    dep_els = "".join(f"<dependency><artifactId>{d}</artifactId></dependency>" for d in deps)
    return (
        f"<project {NS if ns else ''}><groupId>com.acme</groupId>"
        f"<artifactId>{artifact}</artifactId>{parent_el}{mods}"
        f"<dependencies>{dep_els}</dependencies></project>"
    )


def _reactor(root: Path) -> list[list[str]]:
    """Build waves as bare artifactIds, for readable assertions."""
    graph = dg.build_dependency_graph(str(root), "java-8-to-25")
    return [
        sorted(n.split("[")[1].rstrip("]") if "[" in n else n for n in group)
        for group in graph["groups"]
    ]


class TestMavenMultiModule:
    def test_reactor_waves_follow_inter_module_dependencies(self, tmp_path):
        _w(tmp_path, "pom.xml", _pom("acme", modules=("common", "data", "web")))
        _w(tmp_path, "common/pom.xml", _pom("acme-common", parent="acme"))
        _w(tmp_path, "data/pom.xml", _pom("acme-data", parent="acme", deps=("acme-common",)))
        _w(tmp_path, "web/pom.xml", _pom("acme-web", parent="acme", deps=("acme-data",)))

        assert _reactor(tmp_path) == [["acme"], ["acme-common"], ["acme-data"], ["acme-web"]]

    def test_independent_modules_share_a_wave(self, tmp_path):
        """They can be migrated in parallel; serialising them would be a false
        constraint on the plan."""
        _w(tmp_path, "pom.xml", _pom("acme", modules=("a", "b", "c")))
        _w(tmp_path, "a/pom.xml", _pom("acme-a", parent="acme"))
        _w(tmp_path, "b/pom.xml", _pom("acme-b", parent="acme", deps=("acme-a",)))
        _w(tmp_path, "c/pom.xml", _pom("acme-c", parent="acme", deps=("acme-a",)))

        assert _reactor(tmp_path) == [["acme"], ["acme-a"], ["acme-b", "acme-c"]]

    def test_external_dependencies_are_not_nodes(self, tmp_path):
        """spring-core is not in the repo, so it is not a thing to migrate."""
        _w(tmp_path, "pom.xml", _pom("acme", modules=("a",)))
        _w(tmp_path, "a/pom.xml", _pom("acme-a", parent="acme", deps=("spring-core", "jackson-databind")))

        graph = dg.build_dependency_graph(str(tmp_path), "java-8-to-25")

        assert len(graph["nodes"]) == 2
        assert not any("spring" in n for n in graph["nodes"])

    def test_nodes_carry_both_directory_and_artifact_id(self, tmp_path):
        """The directory is what an agent passes to run_command's subdir; the
        artifactId is what Maven's own output calls the module."""
        _w(tmp_path, "pom.xml", _pom("acme", modules=("svc",)))
        _w(tmp_path, "modules/svc/pom.xml", _pom("acme-svc", parent="acme"))

        nodes = dg.build_dependency_graph(str(tmp_path), "java-8-to-25")["nodes"]

        assert "modules/svc  [acme-svc]" in nodes

    def test_poms_without_a_namespace_still_parse(self, tmp_path):
        _w(tmp_path, "pom.xml", _pom("acme", modules=("a",), ns=False))
        _w(tmp_path, "a/pom.xml", _pom("acme-a", parent="acme", ns=False))

        assert len(dg.build_dependency_graph(str(tmp_path), "java-8-to-25")["nodes"]) == 2

    def test_a_malformed_pom_is_skipped_not_fatal(self, tmp_path):
        _w(tmp_path, "pom.xml", _pom("acme", modules=("a", "b")))
        _w(tmp_path, "a/pom.xml", "<<< not xml at all")
        _w(tmp_path, "b/pom.xml", _pom("acme-b", parent="acme"))

        graph = dg.build_dependency_graph(str(tmp_path), "java-8-to-25")

        assert sorted(n.split("[")[1].rstrip("]") for n in graph["nodes"]) == ["acme", "acme-b"]

    def test_dependency_cycle_does_not_hang_or_lose_modules(self, tmp_path):
        _w(tmp_path, "pom.xml", _pom("acme", modules=("a", "b")))
        _w(tmp_path, "a/pom.xml", _pom("acme-a", parent="acme", deps=("acme-b",)))
        _w(tmp_path, "b/pom.xml", _pom("acme-b", parent="acme", deps=("acme-a",)))

        graph = dg.build_dependency_graph(str(tmp_path), "java-8-to-25")

        assert len(graph["nodes"]) == 3
        assert sum(len(g) for g in graph["groups"]) == 3  # cycle members still placed


class TestGradleMultiProject:
    def test_subprojects_are_listed_from_settings(self, tmp_path):
        _w(tmp_path, "settings.gradle", "include ':app'\ninclude ':core'\ninclude ':data'\n")
        _w(tmp_path, "build.gradle", "plugins { id 'java' }")

        graph = dg.build_dependency_graph(str(tmp_path), "java-8-to-25")

        assert graph["nodes"] == ["app", "core", "data"]

    def test_no_edges_are_invented_for_gradle(self, tmp_path):
        """Resolving `implementation project(':a')` means evaluating Gradle.
        Listing the subprojects unordered is honest; a guessed order would read
        as a build constraint the plan then follows."""
        _w(tmp_path, "settings.gradle", "include ':app'\ninclude ':core'\n")

        graph = dg.build_dependency_graph(str(tmp_path), "java-8-to-25")

        assert graph["edges"] == []
        assert len(graph["groups"]) == 1

    def test_kotlin_dsl_settings_are_read(self, tmp_path):
        _w(tmp_path, "settings.gradle.kts", 'include(":app")\ninclude(":core")\n')

        assert dg.build_dependency_graph(str(tmp_path), "java-8-to-25")["nodes"] == ["app", "core"]


class TestSingleModuleIsNotRegressed:
    def test_one_pom_still_yields_a_per_file_graph(self, tmp_path):
        """Per-file sequencing is the more useful answer for a single module, so
        the module path must not swallow it."""
        _w(tmp_path, "pom.xml", _pom("solo"))
        _w(tmp_path, "src/A.java", "package a;\nclass A {}")
        _w(tmp_path, "src/B.java", "package a;\nimport a.A;\nclass B {}")

        nodes = dg.build_dependency_graph(str(tmp_path), "java-8-to-25")["nodes"]

        assert nodes == ["src/A.java", "src/B.java"]

    def test_no_build_file_at_all_still_yields_a_graph(self, tmp_path):
        _w(tmp_path, "src/A.java", "package a;\nclass A {}")

        assert dg.build_dependency_graph(str(tmp_path), "java-8-to-25")["nodes"] == ["src/A.java"]


class TestLargeSingleModuleRollup:
    def test_a_big_tree_rolls_up_to_packages(self, tmp_path):
        """Past the threshold the per-file graph costs two reads of every source
        file and renders as a wall of truncated groups."""
        _w(tmp_path, "pom.xml", _pom("big"))
        for i in range(dg._MODULE_GRAPH_FILE_THRESHOLD + 50):
            pkg = f"com.acme.p{i % 5}"
            imp = "import com.acme.p0.C0;\n" if i % 5 else ""
            _w(tmp_path, f"src/{pkg.replace('.', '/')}/C{i}.java", f"package {pkg};\n{imp}class C{i} {{}}")

        graph = dg.build_dependency_graph(str(tmp_path), "java-8-to-25")

        assert graph["nodes"] == [f"com.acme.p{i}" for i in range(5)]
        # p1..p4 import from p0, so p0 must be sequenced first.
        assert graph["groups"][0] == ["com.acme.p0"]

    def test_just_under_the_threshold_keeps_per_file_detail(self, tmp_path):
        _w(tmp_path, "pom.xml", _pom("small"))
        for i in range(10):
            _w(tmp_path, f"src/C{i}.java", f"package a;\nclass C{i} {{}}")

        nodes = dg.build_dependency_graph(str(tmp_path), "java-8-to-25")["nodes"]

        assert all(n.endswith(".java") for n in nodes)
