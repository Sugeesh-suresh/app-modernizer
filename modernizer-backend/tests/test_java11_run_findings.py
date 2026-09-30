"""
Regression tests for the findings of real Java 8 -> 11 runs on large
monoliths, one class per finding:

F1  build "failed with 401": the migration set coordinates that do not exist
    (powermock-api-mockito 2.0.9, a 2.4.0-b… JAXB build) and the fixer added a
    repository instead of correcting them.
F2  Mockito 1 runner imports left in hundreds of test files.
F3  a `(URLClassLoader) ClassLoader.getSystemClassLoader()` left in place.
F4  planned files left unchanged by their task.
F5  a manifest path (`pom.xml`) that exists only under the upload's top folder.
"""
import asyncio
from pathlib import Path

import pytest

import main
from agents import APP_NAME, PATTERN_RUNNERS, USER_ID, session_service
from agents.java_8_to_11 import agents as j11_agents
from agents.java_8_to_11 import inventory, mechanical
from agents.shared import plan_paths, scope_fence

P = "java-8-to-11"
TOP = "acme-app-master"

PARENT = """<project><modelVersion>4.0.0</modelVersion>
  <groupId>com.acme</groupId><artifactId>acme-parent</artifactId><version>26.17.0-SNAPSHOT</version>
  <packaging>pom</packaging>
  <properties><maven.compiler.source>1.8</maven.compiler.source><maven.compiler.target>1.8</maven.compiler.target>
    <mockito.version>{mockito}</mockito.version><powermock.version>{powermock}</powermock.version></properties>
  <modules><module>app</module></modules>
  <dependencyManagement><dependencies>
    <dependency><groupId>org.mockito</groupId><artifactId>mockito-core</artifactId><version>${{mockito.version}}</version></dependency>
    <dependency><groupId>org.powermock</groupId><artifactId>{powermock_artifact}</artifactId><version>${{powermock.version}}</version></dependency>
    <dependency><groupId>com.acme</groupId><artifactId>acme-common</artifactId><version>26.17.0-SNAPSHOT</version></dependency>
  </dependencies></dependencyManagement>
</project>"""
APP_POM = """<project><modelVersion>4.0.0</modelVersion>
  <parent><groupId>com.acme</groupId><artifactId>acme-parent</artifactId><version>26.17.0-SNAPSHOT</version></parent>
  <artifactId>acme-app</artifactId><packaging>war</packaging>
  <dependencies>
    <dependency><groupId>org.mockito</groupId><artifactId>mockito-core</artifactId><scope>test</scope></dependency>
    <dependency><groupId>org.powermock</groupId><artifactId>{powermock_artifact}</artifactId><scope>test</scope></dependency>
  </dependencies>
</project>"""
CLASSPATH_UPDATER = """package com.acme.util;
import java.lang.reflect.Method;
import java.net.URL;
import java.net.URLClassLoader;
public class ClassPathUpdater {
    public static void add(URL url) throws Exception {
        URLClassLoader sys = (URLClassLoader) ClassLoader.getSystemClassLoader();
        Method m = URLClassLoader.class.getDeclaredMethod("addURL", URL.class);
        m.setAccessible(true);
        m.invoke(sys, url);
    }
}
"""
RUNNER_TEST = """package com.acme;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.runners.MockitoJUnitRunner;
@RunWith(MockitoJUnitRunner.class)
public class {name}Test {{ @Test public void ok() {{}} }}
"""
WHITEBOX_TEST = """package com.acme;
import org.mockito.internal.util.reflection.Whitebox;
public class LegacyTest {
  void t(org.mockito.invocation.InvocationOnMock inv) { String s = inv.getArgumentAt(0, String.class); }
}
"""


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def _repo(root: Path, mockito="1.10.19", powermock="1.7.4", powermock_artifact="powermock-api-mockito",
          tests: int = 3) -> Path:
    files = {
        f"{TOP}/pom.xml": PARENT.format(mockito=mockito, powermock=powermock, powermock_artifact=powermock_artifact),
        f"{TOP}/app/pom.xml": APP_POM.format(powermock_artifact=powermock_artifact),
        f"{TOP}/app/src/main/java/com/acme/util/ClassPathUpdater.java": CLASSPATH_UPDATER,
        f"{TOP}/app/src/test/java/com/acme/LegacyTest.java": WHITEBOX_TEST,
        f"{TOP}/app/src/main/webapp/index.jsp": "<html/>",
    }
    for i in range(tests):
        files[f"{TOP}/app/src/test/java/com/acme/S{i}Test.java"] = RUNNER_TEST.format(name=f"S{i}")
    return _write(root, files)


# ---------------------------------------------------------------------------
# F1 — coordinates that do not exist, and repositories added to "fix" them
# ---------------------------------------------------------------------------

class TestF1Coordinates:
    def test_powermock_2_under_the_old_artifact_id_is_reported_with_the_fix(self, tmp_path):
        base = _repo(tmp_path / "base")
        ws = _repo(tmp_path / "ws", mockito="2.28.2", powermock="2.0.9")          # version bumped, name not
        problems = scope_fence.coordinate_problems(str(base), str(ws))
        hit = [p for p in problems if "powermock-api-mockito:2.0.9" in p]
        assert hit and all("powermock-api-mockito2" in p for p in hit)
        # Reported where it is declared: the parent's dependencyManagement and the module using it.
        assert {h.split(" — ")[0] for h in hit} == {f"`{TOP}/pom.xml`", f"`{TOP}/app/pom.xml`"}

    def test_the_correct_rename_passes(self, tmp_path):
        base = _repo(tmp_path / "base")
        ws = _repo(tmp_path / "ws", mockito="2.28.2", powermock="2.0.9", powermock_artifact="powermock-api-mockito2")
        assert scope_fence.coordinate_problems(str(base), str(ws)) == []

    def test_a_pre_release_version_set_by_the_migration_is_reported(self, tmp_path):
        base = _repo(tmp_path / "base")
        ws = _repo(tmp_path / "ws")
        pom = ws / TOP / "app/pom.xml"
        pom.write_text(pom.read_text().replace("</dependencies>", (
            "<dependency><groupId>org.glassfish.jaxb</groupId><artifactId>txw2</artifactId>"
            "<version>2.4.0-b180608.0325</version></dependency></dependencies>")))
        problems = scope_fence.coordinate_problems(str(base), str(ws))
        assert any("txw2:2.4.0-b180608.0325" in p and "pre-release" in p for p in problems)

    def test_mockito_all_2_is_reported_and_existing_snapshots_are_not(self, tmp_path):
        base = _repo(tmp_path / "base")
        ws = _repo(tmp_path / "ws")
        pom = ws / TOP / "app/pom.xml"
        pom.write_text(pom.read_text().replace("</dependencies>", (
            "<dependency><groupId>org.mockito</groupId><artifactId>mockito-all</artifactId>"
            "<version>2.0.2-beta</version></dependency></dependencies>")))
        problems = scope_fence.coordinate_problems(str(base), str(ws))
        assert any("mockito-all:2.0.2-beta" in p and "mockito-core" in p for p in problems)
        assert not any("26.17.0-SNAPSHOT" in p for p in problems)                  # uploaded as is

    def test_the_whole_workspace_check_fails_on_them(self, tmp_path):
        base = _repo(tmp_path / "base")
        ws = _repo(tmp_path / "ws", mockito="2.28.2", powermock="2.0.9")
        problems, _ = scope_fence.verify_invariants(P, str(base), str(ws))
        assert any("does not exist" in p for p in problems)

    @pytest.mark.parametrize("tag", ["repository", "pluginRepository", "mirror", "server"])
    def test_adding_a_repository_is_refused_at_write_time(self, tag):
        before = "<project><artifactId>a</artifactId></project>"
        after = f"<project><artifactId>a</artifactId><repositories><{tag}><id>x</id></{tag}></repositories></project>"
        problems = scope_fence.check_edit(P, "acme/pom.xml", before, after)
        assert any(f"`<{tag}>` was added" in p for p in problems)


# ---------------------------------------------------------------------------
# F2 / F3 — what the inventory tells the planner
# ---------------------------------------------------------------------------

class TestF2F3Inventory:
    def _inventory(self, tmp_path):
        return inventory.build(str(_repo(tmp_path)))

    def test_the_system_class_loader_cast_is_a_required_change(self, tmp_path):
        inv = self._inventory(tmp_path)
        rows = inv.blockers["system class loader cast to URLClassLoader"]
        assert [(f, lines) for f, lines, _ in rows] == [
            (f"{TOP}/app/src/main/java/com/acme/util/ClassPathUpdater.java", [7, 8])]
        cat = next(c for c in inventory.CATEGORIES if c.name == "system class loader cast to URLClassLoader")
        assert cat.change is True
        doc = inventory.to_document(inv)
        blockers = doc.split("Java 11 Blockers", 1)[1].split("## Behavioural Risks", 1)[0]
        assert "ClassPathUpdater.java" in blockers

    def test_removed_mockito_1_api_is_a_required_change_and_the_runner_is_not(self, tmp_path):
        inv = self._inventory(tmp_path)
        removed = inv.blockers["Mockito 1 API removed in 2.x (test sources)"]
        assert [f for f, _, _ in removed] == [f"{TOP}/app/src/test/java/com/acme/LegacyTest.java"]
        runner = inv.blockers["Mockito 1 runner import (rewritten mechanically by the run)"]
        assert len(runner) == 3
        assert next(c for c in inventory.CATEGORIES if c.name.startswith("Mockito 1 runner")).change is False

    def test_a_cast_of_some_other_loader_stays_a_risk(self, tmp_path):
        _write(tmp_path, {"A.java": "class A { Object x(ClassLoader cl) { return ((URLClassLoader) cl).getURLs(); } }"})
        inv = inventory.build(str(tmp_path))
        assert inv.blockers.get("other cast to URLClassLoader")
        assert not inv.blockers.get("system class loader cast to URLClassLoader")


# ---------------------------------------------------------------------------
# F2 — the mechanical runner rewrite
# ---------------------------------------------------------------------------

class TestF2MechanicalRewrite:
    def test_rewrites_every_runner_once_the_build_is_on_mockito_2(self, tmp_path):
        ws = _repo(tmp_path, mockito="2.28.2", powermock="2.0.9", powermock_artifact="powermock-api-mockito2", tests=5)
        changed, why = mechanical.rewrite_mockito_runner(str(ws))
        assert why == "" and len(changed) == 5
        text = (ws / TOP / "app/src/test/java/com/acme/S0Test.java").read_text()
        assert "import org.mockito.junit.MockitoJUnitRunner;" in text and "org.mockito.runners" not in text

    def test_does_nothing_while_the_build_is_on_mockito_1(self, tmp_path):
        ws = _repo(tmp_path)
        changed, why = mechanical.rewrite_mockito_runner(str(ws))
        assert changed == [] and "below 2.1" in why
        assert "org.mockito.runners" in (ws / TOP / "app/src/test/java/com/acme/S0Test.java").read_text()

    def test_a_file_importing_both_runners_ends_with_one_import(self, tmp_path):
        ws = _repo(tmp_path, mockito="2.28.2", tests=0)
        _write(ws, {f"{TOP}/app/src/test/java/B.java":
                    "import org.mockito.runners.MockitoJUnitRunner;\nimport org.mockito.junit.MockitoJUnitRunner;\nclass B {}\n"})
        mechanical.rewrite_mockito_runner(str(ws))
        assert (ws / TOP / "app/src/test/java/B.java").read_text().count("import org.mockito.junit.MockitoJUnitRunner;") == 1


# ---------------------------------------------------------------------------
# F5 — plan paths reconciled with the repository
# ---------------------------------------------------------------------------

PLAN_SHORT = f"""# Migration Plan

## 1. What Changes
### File Change Manifest
| File | Change Type | What Changes |
|---|---|---|
| `pom.xml` | build | release 11 |
| `app/src/main/java/com/acme/util/ClassPathUpdater.java` | removed JDK API | cast |
| `app/src/main/java/com/acme/Nowhere.java` | removed JDK API | invented |

Each module's `pom.xml` inherits the release.

## Stage 1: {j11_agents.STAGE_TITLE}
### Task 1.1: Build
- Files: `pom.xml`
- Change: release 11
"""


class TestF5PlanPaths:
    def test_short_paths_are_resolved_in_the_manifest_and_tasks_only(self, tmp_path):
        ws = _repo(tmp_path)
        plan, fixed, missing = plan_paths.reconcile(PLAN_SHORT, str(ws))
        assert fixed == {"pom.xml": f"{TOP}/pom.xml",
                         "app/src/main/java/com/acme/util/ClassPathUpdater.java":
                             f"{TOP}/app/src/main/java/com/acme/util/ClassPathUpdater.java"}
        assert f"| `{TOP}/pom.xml` | build |" in plan and f"- Files: `{TOP}/pom.xml`" in plan
        assert "Each module's `pom.xml` inherits the release." in plan                   # prose untouched
        assert missing == ["app/src/main/java/com/acme/Nowhere.java"]
        assert plan.startswith("> ⚠️ **Paths not found in the repository**")

    def test_the_planner_output_is_reconciled_in_the_workflow(self, monkeypatch, tmp_path):
        ws = _repo(tmp_path)

        async def fake_run_step(session_id, step_key, pattern, message, sse_event_type):
            await main._update_state(session_id, {"plan": PLAN_SHORT})

        monkeypatch.setattr(main, "_run_step", fake_run_step)
        state = main._initial_state(P, str(ws), str(ws), "[]", "bigbang", False, False)
        sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
        main._sse_queues[sid] = asyncio.Queue()
        asyncio.run(main._run_bundle_plan(sid, [P]))
        plan = asyncio.run(main._get_state(sid))["plan"]
        assert f"- Files: `{TOP}/pom.xml`" in plan and "Nowhere.java" in plan.split("\n\n", 1)[0]


# ---------------------------------------------------------------------------
# F4 — a task that leaves its files unchanged is sent back once
# ---------------------------------------------------------------------------

PLAN_TASK = f"""# Plan

## Stage 1: {j11_agents.STAGE_TITLE}
### Task 1.1: Plugins in two module POMs
- Files: `{TOP}/pom.xml`, `{TOP}/app/pom.xml`
- Change: maven-war-plugin 3.4.0
"""


class _Modifier:
    """Edits only the files it is told to on each pass."""
    def __init__(self, passes: list[list[str]], ws: Path, result: str = ""):
        self.passes, self.ws, self.result, self.prompts = passes, ws, result, []

    async def run_async(self, session_id, user_id, new_message):
        self.prompts.append((await main._get_state(session_id))["current_task"])
        for rel in (self.passes.pop(0) if self.passes else []):
            path = self.ws / rel
            path.write_text(path.read_text() + "\n<!-- edited -->")
        await main._update_state(session_id, {"modify_result": self.result or "## Modify Result\n- Files changed: …"})
        return
        yield  # pragma: no cover


class TestF4UnchangedTaskFiles:
    def _run(self, monkeypatch, tmp_path, modifier_passes, result=""):
        ws = _repo(tmp_path, mockito="2.28.2", powermock="2.0.9", powermock_artifact="powermock-api-mockito2")
        fake = _Modifier(modifier_passes, ws, result)
        monkeypatch.setitem(PATTERN_RUNNERS[P], "code_modify", fake)

        async def finish(*a, **k):
            return None
        monkeypatch.setattr(main, "_run_workspace_code_step", finish)
        state = main._initial_state(P, str(ws), str(ws), "[]", "bigbang", False, False)
        state["plan"] = PLAN_TASK
        sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
        main._sse_queues[sid] = asyncio.Queue()
        asyncio.run(main._run_java11_code_step(sid))
        return fake, asyncio.run(main._get_state(sid))["modify_result"]

    def test_a_skipped_file_is_sent_back_and_then_done(self, monkeypatch, tmp_path):
        fake, result = self._run(monkeypatch, tmp_path, [[f"{TOP}/pom.xml"], [f"{TOP}/app/pom.xml"]])
        assert len(fake.prompts) == 2
        assert "## Not done yet" in fake.prompts[1] and f"`{TOP}/app/pom.xml`" in fake.prompts[1]
        assert f"`{TOP}/pom.xml`" not in fake.prompts[1].split("## Not done yet")[1]
        assert "NOT APPLIED" not in result

    def test_still_unchanged_after_the_retry_is_reported(self, monkeypatch, tmp_path):
        _, result = self._run(monkeypatch, tmp_path, [[f"{TOP}/pom.xml"], []])
        assert "**⚠ NOT APPLIED**" in result and f"`{TOP}/app/pom.xml`" in result.split("NOT APPLIED")[1]

    def test_a_file_explained_under_files_skipped_is_not_sent_back(self, monkeypatch, tmp_path):
        result = ("## Modify Result\n- Files changed: 1 — pom.xml\n"
                  f"- Files skipped (no change needed): 1 — `{TOP}/app/pom.xml` inherits the plugin version\n"
                  "- Refused by the fence: none")
        fake, out = self._run(monkeypatch, tmp_path, [[f"{TOP}/pom.xml"]], result=result)
        assert len(fake.prompts) == 1 and "NOT APPLIED" not in out

    def test_the_runner_rewrite_runs_after_the_tasks_and_is_reported(self, monkeypatch, tmp_path):
        _, result = self._run(monkeypatch, tmp_path, [[f"{TOP}/pom.xml", f"{TOP}/app/pom.xml"]])
        assert "### Mechanical rewrite: Mockito runner import" in result and "in 3 file(s)" in result
