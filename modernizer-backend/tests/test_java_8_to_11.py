"""
The Java 8 -> Java 11 pattern: a JDK-only upgrade of a JSP + WildFly monolith.

The promise this pattern makes is that JSP views and the WildFly deployment
come out exactly as they went in, and that only `.java` sources and build files
change. These tests pin that promise at each layer that enforces it -- the
fence rules themselves, the guarded write tools the agents hold, the
validator's success gate, the end-of-run restore, the change audit and plan
conformance the reviewer reads -- and the wiring that runs the modifier once
per plan task.
"""
import asyncio
import json
import pathlib
import shutil
import types as pytypes

import pytest
from fastapi.testclient import TestClient

import main
from agents import APP_NAME, PATTERN_RUNNERS, TARGET_LANGS, USER_ID, session_service
from agents.java_8_to_11 import agents as j11_agents
from agents.java_8_to_11 import tools as j11_tools
from agents.shared import scope_fence, skill_manifest
from agents.shared.change_audit import audit_changes, to_markdown
from agents.shared.plan_contract import check as check_plan
from agents.shared.plan_coverage import compare_plan_to_changes

P = "java-8-to-11"
SKILLS = pathlib.Path(__file__).parent.parent / "agents" / "skills"

POM = """<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.acme</groupId>
  <artifactId>orders</artifactId>
  <version>1.0</version>
  <packaging>war</packaging>
  <properties>
    <maven.compiler.source>1.8</maven.compiler.source>
    <maven.compiler.target>1.8</maven.compiler.target>
  </properties>
  <build>
    <finalName>orders</finalName>
    <plugins>
      <plugin>
        <artifactId>maven-war-plugin</artifactId>
        <version>2.6</version>
        <configuration>
          <failOnMissingWebXml>false</failOnMissingWebXml>
        </configuration>
      </plugin>
      <plugin>
        <groupId>org.wildfly.plugins</groupId>
        <artifactId>wildfly-maven-plugin</artifactId>
        <version>1.2.1.Final</version>
      </plugin>
    </plugins>
  </build>
</project>
"""

POM_11 = POM.replace(
    "<maven.compiler.source>1.8</maven.compiler.source>\n    <maven.compiler.target>1.8</maven.compiler.target>",
    "<maven.compiler.release>11</maven.compiler.release>",
).replace("<version>2.6</version>", "<version>3.4.0</version>")

CODEC = """package com.acme;
import sun.misc.BASE64Encoder;
public class Codec {
    public String enc(byte[] b) { return new BASE64Encoder().encode(b); }
}
"""

CODEC_11 = """package com.acme;
import java.util.Base64;
public class Codec {
    public String enc(byte[] b) { return Base64.getMimeEncoder().encodeToString(b); }
}
"""

REPO = {
    "pom.xml": POM,
    "src/main/java/com/acme/Codec.java": CODEC,
    "src/main/java/com/acme/domain/Order.java": "package com.acme.domain;\npublic class Order {}\n",
    "src/main/webapp/index.jsp": "<%@ page import=\"sun.misc.BASE64Encoder\" %>\n<html></html>\n",
    "src/main/webapp/WEB-INF/web.xml": "<web-app/>\n",
    "src/main/webapp/WEB-INF/jboss-web.xml": "<jboss-web><context-root>/orders</context-root></jboss-web>\n",
    "src/main/resources/META-INF/persistence.xml": "<persistence/>\n",
    "src/main/resources/app.properties": "x=1\n",
    "wildfly/standalone.xml": "<server xmlns=\"urn:jboss:domain:8.0\"/>\n",
    "wildfly/orders-ds.xml": "<datasources/>\n",
}


def _write(root: pathlib.Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture
def trees(tmp_path):
    baseline, workspace = tmp_path / "baseline", tmp_path / "workspace"
    _write(baseline, REPO)
    _write(workspace, REPO)
    return baseline, workspace


def _ctx(baseline, workspace):
    return pytypes.SimpleNamespace(
        state={"workspace_dir": str(workspace), "baseline_dir": str(baseline), "pattern": P},
        actions=pytypes.SimpleNamespace(escalate=False, skip_summarization=False),
    )


# ---------------------------------------------------------------------------
# The fence rules
# ---------------------------------------------------------------------------

class TestFenceClassification:
    @pytest.mark.parametrize("path", [
        "src/main/webapp/index.jsp",
        "web/src/main/webapp/css/site.css",          # a web root in a sub-module
        "src/main/webapp/WEB-INF/web.xml",
        "legacy/WebContent/header.jspf",
        "src/main/resources/tags/button.tag",
        "src/main/resources/META-INF/persistence.xml",
        "src/main/resources/META-INF/services/com.acme.Spi",
        "config/jboss-deployment-structure.xml",
        "wildfly/standalone-full.xml",
        "wildfly/configuration/orders-ds.xml",
        "bin/standalone.conf",
        "Dockerfile",
        "scripts/setup.cli",
    ])
    def test_jsp_and_wildfly_files_are_frozen(self, path):
        assert scope_fence.frozen_reason(P, path)
        ok, reason = scope_fence.writable(P, path)
        assert not ok and "frozen" in reason

    @pytest.mark.parametrize("path", [
        "src/main/java/com/acme/domain/Order.java",   # a package called `domain` is not domain.xml
        "src/main/java/com/acme/standalone/Tool.java",
        "orders-core/src/test/java/com/acme/CodecTest.java",
    ])
    def test_java_sources_are_writable_whatever_their_package_is_called(self, path):
        assert scope_fence.frozen_reason(P, path) is None
        assert scope_fence.writable(P, path) == (True, "")

    @pytest.mark.parametrize("path", [
        "pom.xml", "orders-web/pom.xml", "build.gradle", "settings.gradle.kts",
        "gradle.properties", "gradle/wrapper/gradle-wrapper.properties",
        ".mvn/wrapper/maven-wrapper.properties", "./pom.xml",
    ])
    def test_build_files_are_writable(self, path):
        assert scope_fence.writable(P, path)[0]

    @pytest.mark.parametrize("path", [
        "src/main/resources/app.properties",
        "src/main/resources/applicationContext.xml",
        "README.md",
        "Jenkinsfile",
    ])
    def test_everything_else_is_outside_scope_but_not_frozen(self, path):
        ok, reason = scope_fence.writable(P, path)
        assert not ok and "outside this migration's scope" in reason

    def test_other_patterns_have_no_fence(self):
        assert scope_fence.fence_for("java-8-to-25") is None
        assert scope_fence.frozen_reason("java-8-to-25", "src/main/webapp/index.jsp") is None
        assert scope_fence.writable("java-8-to-25", "src/main/webapp/index.jsp") == (True, "")
        assert scope_fence.check_edit("java-8-to-25", "pom.xml", POM, POM.replace("war", "jar")) == []


class TestEditInvariants:
    def test_the_java_11_build_edit_itself_is_allowed(self):
        assert scope_fence.check_edit(P, "pom.xml", POM, POM_11) == []

    @pytest.mark.parametrize("mutate, expected", [
        (lambda s: s.replace("<packaging>war</packaging>", "<packaging>jar</packaging>"), "<packaging>"),
        (lambda s: s.replace("<finalName>orders</finalName>", "<finalName>orders-11</finalName>"), "<finalName>"),
        (lambda s: s.replace("<version>1.2.1.Final</version>", "<version>2.0.0.Final</version>"), "WildFly/JBoss"),
        (lambda s: s.replace("<failOnMissingWebXml>false", "<failOnMissingWebXml>true"), "maven-war-plugin"),
        (lambda s: s.replace("<maven.compiler.release>11<", "<maven.compiler.release>17<"), "past 11"),
        (lambda s: s.replace("<plugins>", "<plugins><plugin><groupId>org.springframework.boot</groupId>"
                                          "<artifactId>spring-boot-maven-plugin</artifactId></plugin>"),
         "Spring Boot"),
    ])
    def test_pom_edits_that_break_the_deployment_are_refused(self, mutate, expected):
        problems = scope_fence.check_edit(P, "pom.xml", POM, mutate(POM_11))
        assert any(expected in p for p in problems), problems

    def test_a_pre_existing_level_past_11_is_not_blamed_on_the_edit(self):
        before = POM.replace("<version>1.0</version>", "<version>1.0</version><x><release>17</release></x>")
        assert scope_fence.check_edit(P, "pom.xml", before, before.replace("2.6", "3.4.0")) == []

    def test_jakarta_import_is_refused_in_java(self):
        after = CODEC.replace("import sun.misc.BASE64Encoder;", "import jakarta.servlet.http.HttpServlet;")
        problems = scope_fence.check_edit(P, "src/main/java/com/acme/Codec.java", CODEC, after)
        assert problems and "jakarta.servlet.http.HttpServlet" in problems[0]

    def test_gradle_war_plugin_must_stay(self):
        before = "plugins {\n    id 'war'\n}\nsourceCompatibility = 1.8\n"
        after = "plugins {\n    id 'java'\n}\nsourceCompatibility = 11\n"
        assert any("war" in p for p in scope_fence.check_edit(P, "build.gradle", before, after))
        ok = before.replace("1.8", "11")
        assert scope_fence.check_edit(P, "build.gradle", before, ok) == []

    def test_declared_levels_are_read_from_every_common_spelling(self):
        assert scope_fence.declared_java_levels("pom.xml", "<source>1.8</source><release>11</release>") == [
            ("source", 8), ("release", 11),
        ]
        gradle = "sourceCompatibility = JavaVersion.VERSION_1_8\njava { toolchain { languageVersion = JavaLanguageVersion.of(11) } }"
        assert [lvl for _, lvl in scope_fence.declared_java_levels("build.gradle", gradle)] == [8, 11]
        setter = "tasks.withType(JavaCompile) { options.release.set(11) }\njava.toolchain.languageVersion.set(JavaLanguageVersion.of(11))"
        assert [lvl for _, lvl in scope_fence.declared_java_levels("build.gradle.kts", setter)] == [11, 11]


# ---------------------------------------------------------------------------
# The guarded tools the modifier and fixer hold
# ---------------------------------------------------------------------------

class TestGuardedTools:
    def test_writing_a_jsp_is_refused_and_the_file_is_untouched(self, trees):
        baseline, workspace = trees
        result = j11_tools.write_file(_ctx(baseline, workspace), "src/main/webapp/index.jsp", "<html/>")
        assert result.startswith("ERROR: refused") and "JSP" in result
        assert (workspace / "src/main/webapp/index.jsp").read_text() == REPO["src/main/webapp/index.jsp"]

    @pytest.mark.parametrize("path", [
        "src/main/webapp/WEB-INF/jboss-web.xml", "wildfly/standalone.xml", "src/main/webapp/new.jsp",
    ])
    def test_replacing_in_or_creating_wildfly_and_web_files_is_refused(self, trees, path):
        baseline, workspace = trees
        ctx = _ctx(baseline, workspace)
        if (workspace / path).exists():
            text = (workspace / path).read_text()
            result = j11_tools.replace_in_file(ctx, path, text[:10], "changed!!!")
        else:
            result = j11_tools.write_file(ctx, path, "<x/>")
        assert result.startswith("ERROR: refused")
        assert ((workspace / path).read_text() if (workspace / path).exists() else None) == REPO.get(path)

    def test_resources_outside_scope_are_refused(self, trees):
        baseline, workspace = trees
        result = j11_tools.replace_in_file(_ctx(baseline, workspace), "src/main/resources/app.properties", "x=1", "x=2")
        assert result.startswith("ERROR: refused") and "outside this migration's scope" in result

    def test_the_compiler_level_edit_goes_through(self, trees):
        baseline, workspace = trees
        result = j11_tools.replace_in_file(
            _ctx(baseline, workspace), "pom.xml",
            "<maven.compiler.source>1.8</maven.compiler.source>\n    <maven.compiler.target>1.8</maven.compiler.target>",
            "<maven.compiler.release>11</maven.compiler.release>",
        )
        assert result.startswith("Replaced 1")
        assert "<maven.compiler.release>11<" in (workspace / "pom.xml").read_text()

    def test_a_packaging_change_is_refused_through_replace(self, trees):
        baseline, workspace = trees
        result = j11_tools.replace_in_file(_ctx(baseline, workspace), "pom.xml", "<packaging>war</packaging>",
                                           "<packaging>jar</packaging>")
        assert result.startswith("ERROR: refused") and "<packaging>" in result
        assert "<packaging>war</packaging>" in (workspace / "pom.xml").read_text()

    def test_the_removed_api_fix_goes_through(self, trees):
        baseline, workspace = trees
        result = j11_tools.write_file(_ctx(baseline, workspace), "src/main/java/com/acme/Codec.java", CODEC_11)
        assert result.startswith("Wrote")

    def test_a_new_java_file_with_jakarta_is_refused(self, trees):
        baseline, workspace = trees
        result = j11_tools.write_file(_ctx(baseline, workspace), "src/main/java/com/acme/New.java",
                                      "package com.acme;\nimport jakarta.inject.Inject;\nclass New {}\n")
        assert result.startswith("ERROR: refused") and "jakarta" in result
        assert not (workspace / "src/main/java/com/acme/New.java").exists()

    def test_shared_tool_errors_still_come_through_unchanged(self, trees):
        baseline, workspace = trees
        result = j11_tools.replace_in_file(_ctx(baseline, workspace), "pom.xml", "not in the file", "x")
        assert result.startswith("ERROR: old_text was not found")


class TestValidatorGate:
    def test_success_is_not_signalled_while_the_level_is_still_8(self, trees):
        baseline, workspace = trees
        ctx = _ctx(baseline, workspace)
        result = j11_tools.signal_build_success(ctx)
        assert result.startswith("ERROR: build success NOT signalled")
        assert ctx.actions.escalate is False

    def test_success_is_signalled_once_the_invariants_hold(self, trees):
        baseline, workspace = trees
        (workspace / "pom.xml").write_text(POM_11)
        ctx = _ctx(baseline, workspace)
        assert "OVERALL: PASS" in j11_tools.check_java11_invariants(ctx)
        assert not j11_tools.signal_build_success(ctx).startswith("ERROR")
        assert ctx.actions.escalate is True

    def test_a_frozen_file_changed_behind_the_tools_fails_the_gate(self, trees):
        baseline, workspace = trees
        (workspace / "pom.xml").write_text(POM_11)
        (workspace / "src/main/webapp/WEB-INF/web.xml").write_text("<web-app version='4.0'/>")
        ctx = _ctx(baseline, workspace)
        report = j11_tools.check_java11_invariants(ctx)
        assert "OVERALL: FAIL" in report and "web.xml" in report
        assert j11_tools.signal_build_success(ctx).startswith("ERROR")

    def test_a_module_left_on_8_fails(self, trees):
        baseline, workspace = trees
        (workspace / "pom.xml").write_text(POM_11)
        _write(workspace, {"orders-batch/pom.xml": "<project><properties><java.version>1.8</java.version></properties></project>"})
        problems, _ = scope_fence.verify_invariants(P, str(baseline), str(workspace))
        assert any("orders-batch/pom.xml" in p and "java.version=8" in p for p in problems)


class TestRestore:
    def test_frozen_changes_are_undone_and_nothing_else_is(self, trees):
        baseline, workspace = trees
        (workspace / "src/main/webapp/index.jsp").write_text("<html>edited</html>")
        (workspace / "wildfly/orders-ds.xml").unlink()
        _write(workspace, {"src/main/webapp/extra.jsp": "<p/>"})
        (workspace / "src/main/java/com/acme/Codec.java").write_text(CODEC_11)

        undone = dict(scope_fence.restore_frozen(P, str(baseline), str(workspace)))

        assert undone == {
            "src/main/webapp/index.jsp": "restored",
            "wildfly/orders-ds.xml": "restored",
            "src/main/webapp/extra.jsp": "removed",
        }
        assert (workspace / "src/main/webapp/index.jsp").read_text() == REPO["src/main/webapp/index.jsp"]
        assert (workspace / "wildfly/orders-ds.xml").exists()
        assert not (workspace / "src/main/webapp/extra.jsp").exists()
        assert (workspace / "src/main/java/com/acme/Codec.java").read_text() == CODEC_11
        assert scope_fence.frozen_changes(P, str(baseline), str(workspace)) == []

    def test_restore_is_a_no_op_for_other_patterns(self, trees):
        baseline, workspace = trees
        (workspace / "src/main/webapp/index.jsp").write_text("<html>edited</html>")
        assert scope_fence.restore_frozen("java-8-to-25", str(baseline), str(workspace)) == []
        assert (workspace / "src/main/webapp/index.jsp").read_text() == "<html>edited</html>"


# ---------------------------------------------------------------------------
# What the independent reviewer sees
# ---------------------------------------------------------------------------

class TestReviewEvidence:
    def test_a_frozen_file_change_is_a_regression_and_untouched_jsp_is_not_a_gap(self, trees):
        baseline, workspace = trees
        (workspace / "pom.xml").write_text(POM_11)
        (workspace / "src/main/java/com/acme/Codec.java").write_text(CODEC_11)
        (workspace / "src/main/webapp/WEB-INF/jboss-web.xml").write_text("<jboss-web/>")

        audit = audit_changes(str(baseline), str(workspace), P)

        regressions = {e["path"]: e for e in audit.regressions}
        assert "src/main/webapp/WEB-INF/jboss-web.xml" in regressions
        assert regressions["src/main/webapp/WEB-INF/jboss-web.xml"]["forbidden_added"][0]["marker"] == "frozen file changed"
        # index.jsp still imports sun.misc.BASE64Encoder, but it is frozen: never a coverage gap.
        assert all(r["path"] != "src/main/webapp/index.jsp" for r in audit.residual_legacy)
        assert audit.unchanged_frozen >= 5
        explained = {e["path"] for e in audit.explained}
        assert {"pom.xml", "src/main/java/com/acme/Codec.java"} <= explained
        assert "SCOPE FENCE" in to_markdown(audit)

    def test_overshooting_java_11_is_flagged_forbidden(self, trees):
        baseline, workspace = trees
        (workspace / "pom.xml").write_text(POM_11.replace("<maven.compiler.release>11<", "<maven.compiler.release>17<"))
        audit = audit_changes(str(baseline), str(workspace), P)
        assert any(h["marker"] == "Java level past 11" for e in audit.regressions for h in e["forbidden_added"])

    def test_frozen_zone_rows_marked_unchanged_are_held_to_it(self, trees):
        baseline, workspace = trees
        (workspace / "src/main/webapp/index.jsp").write_text("<html>edited</html>")
        plan = (
            "### File Change Manifest\n\n| File | Change Type | What Changes |\n|---|---|---|\n"
            "| `pom.xml` | build | release 11 |\n\n"
            "### Frozen Zone\n\n| Path or glob | Kind | Files | Status |\n|---|---|---|---|\n"
            "| `src/main/webapp/` | web root | 3 | frozen — unchanged |\n"
        )
        paths = sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*") if p.is_file())
        coverage = compare_plan_to_changes(plan, str(baseline), str(workspace), paths)
        assert [actual for _, actual in coverage.contradicted] == ["src/main/webapp/index.jsp"]


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

class TestWiring:
    def test_runners_and_target_language(self):
        assert set(PATTERN_RUNNERS[P]) == {
            "re", "re_module", "re_merge", "re_synthesize", "plan", "code_modify", "code_finish",
        }
        assert TARGET_LANGS[P] == "java"

    def test_writing_agents_hold_only_the_fenced_tools(self):
        for agent in (j11_agents.modifier_agent, j11_agents.fixer_agent):
            funcs = {getattr(t, "func", None) for t in agent.tools}
            assert j11_tools.write_file in funcs and j11_tools.replace_in_file in funcs
            from agents.shared import workspace_tools
            assert workspace_tools.write_file not in funcs
            assert workspace_tools.replace_in_file not in funcs

    def test_the_validator_signals_through_the_gated_tool(self):
        funcs = {getattr(t, "func", None) for t in j11_agents.validator_agent.tools}
        assert j11_tools.signal_build_success in funcs
        assert j11_tools.check_java11_invariants in funcs

    def test_the_finish_pipeline_uses_the_names_main_routes_on(self):
        names = [a.name for a in j11_agents.code_finish_pipeline.sub_agents]
        assert names == ["build_loop", "code_reviewer_agent", "reporter_agent", "skill_curator_agent"]
        assert [a.name for a in j11_agents.build_loop.sub_agents] == ["validator_agent", "fixer_agent"]
        assert j11_agents.modifier_agent.name == "modifier_agent"

    def test_every_rostered_skill_exists_on_disk(self):
        refs = skill_manifest.resolve(j11_agents._PLAN_SKILL_ROSTER)
        assert not [r.name for r in refs if r.missing]
        for name in j11_agents.CURATED_SKILLS:
            assert (SKILLS / name / "SKILL.md").is_file()

    def test_re_skill_emits_the_parser_markers(self):
        text = (SKILLS / "java-8-to-11-re" / "SKILL.md").read_text()
        for marker in ("ANALYSIS", "BRD", "TECHNICAL_SPECIFICATION", "TEST_INVENTORY", "END"):
            assert f"<!-- SECTION: {marker} -->" in text

    def test_plan_skill_names_the_stage_title_main_splits_on(self):
        text = (SKILLS / "java-8-to-11-plan" / "SKILL.md").read_text()
        assert f"## Stage 1: {j11_agents.STAGE_TITLE}" in text

    def test_plan_skill_template_satisfies_the_six_question_contract(self):
        text = (SKILLS / "java-8-to-11-plan" / "SKILL.md").read_text()
        template = text.split("## Output shape", 1)[1].split("```", 2)[1]
        assert check_plan(template).complete, check_plan(template)

    def test_upload_rejects_the_java_25_options(self):
        with TestClient(main.app) as client:
            for field in ({"springboot_upgrade": "true"}, {"junit_upgrade": "true"},
                          {"migration_strategy": "incremental"}):
                res = client.post(
                    "/api/upload",
                    data={"pattern": P, **field},
                    files={"file": ("repo.zip", b"PK\x05\x06" + b"\x00" * 18, "application/zip")},
                )
                assert res.status_code == 400, field
                assert "JDK-only" in res.json()["detail"]


# ---------------------------------------------------------------------------
# The per-task code step
# ---------------------------------------------------------------------------

PLAN = f"""# Migration Plan

## 1. What Changes

## Stage 1: {j11_agents.STAGE_TITLE}

### Task 1.1: Build to release 11
- Files: `pom.xml`
- Change: release 11

### Task 1.2: Replace sun.misc Base64
- Files: `src/main/java/com/acme/Codec.java`
- Change: java.util.Base64

## 2. What Stays the Same
"""


class _FakeModifier:
    def __init__(self):
        self.tasks: list[str] = []

    async def run_async(self, session_id, user_id, new_message):
        state = await main._get_state(session_id)
        self.tasks.append(state["current_task"])
        await main._update_state(session_id, {"modify_result": f"## Modify Result\ndid {len(self.tasks)}"})
        return
        yield  # pragma: no cover — makes this an async generator


def _java11_session(plan: str) -> str:
    state = main._initial_state(P, "/tmp/ws-j11", "/tmp/base-j11", "[]", "bigbang", False, False)
    state["plan"] = plan
    session = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state))
    main._sse_queues[session.id] = asyncio.Queue()
    return session.id


class TestCodeStep:
    def _run(self, monkeypatch, plan):
        fake = _FakeModifier()
        finished: list[str] = []

        async def fake_finish(session_id, pattern, code_key, push_session_id=None):
            finished.append(code_key)

        monkeypatch.setitem(PATTERN_RUNNERS[P], "code_modify", fake)
        monkeypatch.setattr(main, "_run_workspace_code_step", fake_finish)
        sid = _java11_session(plan)
        asyncio.run(main._run_java11_code_step(sid))
        return fake, finished, asyncio.run(main._get_state(sid)), sid

    def test_one_modifier_run_per_task_then_one_finish(self, monkeypatch):
        fake, finished, state, sid = self._run(monkeypatch, PLAN)

        assert len(fake.tasks) == 2
        assert "Task 1.1: Build to release 11" in fake.tasks[0] and "Codec.java" not in fake.tasks[0]
        assert "Task 1.2: Replace sun.misc Base64" in fake.tasks[1] and "pom.xml" not in fake.tasks[1]
        assert finished == ["code_finish"]
        assert "### Task 1.1" in state["modify_result"] and "did 2" in state["modify_result"]

        events = []
        queue = main._sse_queues[sid]
        while not queue.empty():
            events += [json.loads(l[6:]) for l in queue.get_nowait().splitlines() if l.startswith("data: ")]
        assert [e["task_index"] for e in events if e["type"] == "task-start"] == [1, 2]

    def test_a_plan_without_the_stage_heading_still_runs_as_one_unit(self, monkeypatch):
        fake, finished, _, _ = self._run(monkeypatch, "# Plan\n\nSet release 11 in `pom.xml`.\n")
        assert len(fake.tasks) == 1 and "Set release 11" in fake.tasks[0]
        assert finished == ["code_finish"]

    def test_the_bundle_runner_dispatches_java_11_to_its_own_step(self, monkeypatch):
        called: list[str] = []

        async def fake_step(session_id, push_session_id=None):
            called.append(session_id)

        monkeypatch.setattr(main, "_run_java11_code_step", fake_step)
        sid = _java11_session(PLAN)
        asyncio.run(main._run_bundle_code_generation(sid, [P]))
        assert called == [sid]

    def test_enforce_scope_fence_restores_and_notes_it_in_the_report(self, tmp_path):
        baseline, workspace = tmp_path / "b", tmp_path / "w"
        _write(baseline, REPO)
        shutil.copytree(baseline, workspace)
        (workspace / "src/main/webapp/index.jsp").write_text("<html>edited</html>")

        state = main._initial_state(P, str(workspace), str(baseline), "[]", "bigbang", False, False)
        state["final_report"] = "# Report"
        session = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state))
        main._sse_queues[session.id] = asyncio.Queue()

        asyncio.run(main._enforce_scope_fence(session.id))

        assert (workspace / "src/main/webapp/index.jsp").read_text() == REPO["src/main/webapp/index.jsp"]
        report = asyncio.run(main._get_state(session.id))["final_report"]
        assert report.startswith("# Report") and "`src/main/webapp/index.jsp` — restored" in report
