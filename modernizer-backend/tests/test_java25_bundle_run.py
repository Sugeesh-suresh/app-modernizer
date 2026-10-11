"""Java 8 -> 25 with companions (tests/fixtures/policy-legacy-java8: Spring 3, Hibernate 3, Ehcache 2,
JAX-WS, Oracle, Solr 4): the per-stage JDKs and their preflight, the code-phase order that keeps the
JDK 8 readiness stages ahead of the Java 11+ companions, the reviews' set-aside of the other
migrations' files, file deletion, and the legacy markers this repository exercises."""
import json
import shutil
import types
from pathlib import Path

import anyio
import pytest

from agents import config
from agents.java_8_to_25 import preflight as java25_preflight
from agents.shared import change_audit, java_preflight, plan_coverage, workspace_tools
from agents.shared.evidence import redact
from cli import mcp_server, pipeline
from cli.runstate import Run

FIXTURE = Path(__file__).parent / "fixtures" / "policy-legacy-java8"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MODERNIZER_WORKSPACE", raising=False)


def _tool(fn, **kwargs) -> str:
    return anyio.run(lambda: fn(**kwargs))


JDKS = [{"major": 8, "home": "/jdk8", "source": "MIGRATION_JAVA_HOMES[8]"},
        {"major": 21, "home": "/jdk21", "source": "PATH"}]


# ── JDK per stage ─────────────────────────────────────────────────────────────

def test_each_release_gets_its_own_jdk_or_the_nearest_newer_one():
    chosen = java25_preflight.assign([8, 17, 25], JDKS)
    assert chosen[8]["home"] == "/jdk8" and chosen[8]["exact"]
    assert chosen[17]["home"] == "/jdk21" and not chosen[17]["exact"]     # approximate: newer JDK
    assert 25 not in chosen                                              # nothing can build Java 25


def test_the_releases_a_run_builds_follow_its_strategy():
    assert java25_preflight.releases_for("incremental", True) == [8, 17, 25]
    assert java25_preflight.releases_for("incremental", False) == [8, 17, 25]
    assert java25_preflight.releases_for("bigbang", False) == [8, 25]


def test_a_build_runs_on_the_jdk_of_the_running_stage(monkeypatch):
    monkeypatch.setattr(java25_preflight, "available_jdks", lambda: JDKS + [
        {"major": 17, "home": "/jdk17", "source": "x"}, {"major": 25, "home": "/jdk25", "source": "y"}])
    homes = {stage: java25_preflight.stage_env(types.SimpleNamespace(state={"approved_stage": stage}))["JAVA_HOME"]
             for stage in ("1", "3", "5", "6", "8", "")}
    assert homes == {"1": "/jdk8", "3": "/jdk17", "5": "/jdk17", "6": "/jdk25", "8": "/jdk25", "": "/jdk25"}


def test_the_run_command_tool_passes_the_session_to_its_environment(tmp_path):
    seen = []

    def env(tool_context):
        seen.append(tool_context.state["approved_stage"])
        return None
    run = workspace_tools.make_run_command({"java"}, env_factory=env)
    run(types.SimpleNamespace(state={"workspace_dir": str(tmp_path), "approved_stage": "3"}), "java -version")
    assert seen == ["3"]
    legacy = workspace_tools.make_run_command({"java"}, env_factory=lambda: None)   # no-argument factories still work
    assert "ERROR" not in legacy(types.SimpleNamespace(state={"workspace_dir": str(tmp_path)}), "java -version")[:6]


def test_preflight_stops_when_no_jdk_can_build_a_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(java25_preflight, "available_jdks", lambda: JDKS)
    monkeypatch.setattr(config, "PREFLIGHT", "on")
    pf = java25_preflight.run(str(tmp_path), "incremental", True)                 # no pom: JDKs only
    assert not pf.ok and "No JDK 25 or newer" in pf.stop_reason
    monkeypatch.setattr(config, "PREFLIGHT", "warn")
    pf = java25_preflight.run(str(tmp_path), "incremental", True)
    assert pf.ok and "No JDK 25" in pf.problems[0] and "WARNINGS" in java25_preflight.summary(pf)
    spec = java_preflight.with_preflight("# Spec", "java-8-to-25", pf.to_json())
    assert spec.startswith("## Build Environment and Baseline Build") and "| 17 | JDK 21 |" in spec
    assert java_preflight.with_preflight(spec, "java-8-to-25", pf.to_json()) == spec       # once


# ── markers ───────────────────────────────────────────────────────────────────

def _hits(pattern: str, text: str) -> set[str]:
    """Every marker any line matches (the audit itself lists only the first few per file)."""
    return {h["marker"] for line in text.splitlines()
            for h in change_audit._scan([line], change_audit.LEGACY_MARKERS[pattern])}


def test_the_fixture_legacy_stack_is_recognised():
    pom = (FIXTURE / "pom.xml").read_text()
    assert {"Spring Framework 3/4", "Hibernate 3/4", "commons-lang 2", "JAX-WS RI 2.x (javax)"} <= _hits("java-8-to-25", pom)
    dao = (FIXTURE / "src/main/java/com/acme/policy/dao/PolicyDao.java").read_text()
    assert "HQL positional parameter" in _hits("java-8-to-25", dao)
    oracle = _hits("oracle-19c-to-23ai", (FIXTURE / "src/main/resources/db/schema.sql").read_text()
                   + (FIXTURE / "src/main/resources/applicationContext.xml").read_text()
                   + (FIXTURE / "src/main/resources/policy.properties").read_text())
    assert {"deprecated Oracle driver class", "SID connect string"} <= oracle and any("LONG" in m for m in oracle)


def test_markers_do_not_flag_the_migrated_stack():
    modern = ("<groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId>"
              "<version>4.1.1</version>\n<groupId>org.springframework.data</groupId><artifactId>spring-data-jpa"
              "</artifactId><version>3.5.0</version>\n<artifactId>jaxws-rt</artifactId><version>4.0.5</version>\n"
              "Long id = (Long) session.save(p);\nreturn \"from Policy p where p.status = :status\";")
    assert not _hits("java-8-to-25", modern)
    assert not {m for m in _hits("oracle-19c-to-23ai", modern) if "LONG" in m}


def test_redaction_keeps_a_url_that_has_no_credentials():
    assert redact("jdbc:oracle:thin:@dbhost:1521:POLDB") == "jdbc:oracle:thin:@dbhost:1521:POLDB"
    assert redact("jdbc:oracle:thin:scott/tiger@db:1521:X") == "jdbc:oracle:thin:<redacted>@db:1521:X"


# ── plan conformance ──────────────────────────────────────────────────────────

PLAN = """# Plan
## 1. What Changes
### File Change Manifest
| File | Change Type | What Changes |
|---|---|---|
| `pom.xml` | build | bump |
| `src/main/resources/application.properties` | new | added in Stage 4, deleted in Stage 7 |
## 3. Why This Is Safe
### Behaviour Inventory
| Behaviour | Kind | Where |
|---|---|---|
| `/api/policies` | endpoint | `PolicyController` |
"""


def test_only_the_manifest_section_is_the_approved_scope(tmp_path):
    base, ws = tmp_path / "b", tmp_path / "w"
    shutil.copytree(FIXTURE, base)
    shutil.copytree(FIXTURE, ws)
    (ws / "pom.xml").write_text("<project/>")
    (ws / "src/main/resources/db/schema.sql").write_text("-- clob")                 # another migration's file
    cov = plan_coverage.compare_plan_to_changes(PLAN, str(base), str(ws), sorted(change_audit.relevant_files(ws)),
                                                {"src/main/resources/db/schema.sql": "oracle-19c-to-23ai"})
    assert [p.path for p in plan_coverage.parse_plan_manifest(PLAN)] == ["pom.xml", "src/main/resources/application.properties"]
    assert not cov.unresolved and not cov.unplanned                                 # transient file, set-aside file
    assert "oracle-19c-to-23ai" in plan_coverage.to_markdown(cov)


def test_a_bundle_review_sets_aside_what_only_other_migrations_changed(tmp_path):
    state = {"pattern": "solr-4-to-9", "workspace_dir": str(tmp_path),
             "pass_changes": json.dumps({"java-8-to-25": ["pom.xml", "A.java"], "solr-4-to-9": ["pom.xml"],
                                         "oracle-19c-to-23ai": ["schema.sql"]})}
    assert change_audit.other_migrations_files(state) == {"A.java": "java-8-to-25", "schema.sql": "oracle-19c-to-23ai"}
    (tmp_path / "A.java").write_text("x")
    start = tmp_path / "start.json"
    start.write_text(json.dumps({}))                       # the running pass created A.java: it is its own
    assert "A.java" not in change_audit.other_migrations_files({**state, "pass_start_file": str(start)})


# ── deletion ──────────────────────────────────────────────────────────────────

def test_delete_file_removes_one_file_and_its_emptied_folders(tmp_path):
    ctx = types.SimpleNamespace(state={"workspace_dir": str(tmp_path)})
    (tmp_path / "src/main/webapp/WEB-INF").mkdir(parents=True)
    (tmp_path / "src/main/webapp/WEB-INF/web.xml").write_text("<web-app/>")
    (tmp_path / "src/main/keep.txt").write_text("k")
    assert workspace_tools.delete_file(ctx, "src/main/webapp").startswith("ERROR")          # never a directory
    assert workspace_tools.delete_file(ctx, "../outside.txt").startswith("ERROR")
    assert workspace_tools.delete_file(ctx, "src/main/webapp/WEB-INF/web.xml") == "Deleted src/main/webapp/WEB-INF/web.xml."
    assert not (tmp_path / "src/main/webapp").exists() and (tmp_path / "src/main/keep.txt").is_file()


# ── the bundle run, end to end through the CLI pipeline ──────────────────────

JAVA_PLAN = """# Migration Plan: Java 8 → Java 25
## 1. What Changes
### File Change Manifest
| File | Change Type | Owning Stage | What Changes |
|---|---|---|---|
| `pom.xml` | build | 1, 3 | plugins; release 17 |
| `src/main/java/com/acme/policy/util/ExportSigner.java` | API rewrite | 3 | `java.util.Base64` |
| `src/main/resources/log4j.properties` | config | deleted in 4 | Boot logging |

## Stage 1: Modernize Build Systems (Maven/Gradle)
### Task 1.1: Test stack
- Files: `pom.xml`

## Stage 3: Java 8 → Java 17 LTS
### Task 3.1: Base64
- Files: `src/main/java/com/acme/policy/util/ExportSigner.java`

## Stage 4: Upgrade to Spring Boot 2.7 (WAR intact)
### Task 4.1: Boot logging
- Files: `src/main/resources/log4j.properties`
"""
COMPANION_PLANS = {
    "oracle-19c-to-23ai": "# Plan\n## 1. What Changes\n### File Change Manifest\n| File | Change |\n|---|---|\n"
                          "| `src/main/resources/db/schema.sql` | LONG → CLOB |\n",
    "solr-4-to-9": "# Plan\n## 1. What Changes\n### File Change Manifest\n| File | Change |\n|---|---|\n"
                   "| `solr/policies/conf/solrconfig.xml` | luceneMatchVersion 9 |\n",
}
EDITS = {   # (pattern, stage idx) -> what the stand-in modifier does
    ("java-8-to-25", 1): ("replace", "pom.xml", "<version>4.12</version>", "<version>4.13.2</version>"),
    ("java-8-to-25", 3): ("replace", "src/main/java/com/acme/policy/util/ExportSigner.java",
                          "import sun.misc.BASE64Encoder;\n", ""),
    ("oracle-19c-to-23ai", 0): ("replace", "src/main/resources/db/schema.sql", "terms         LONG", "terms         CLOB"),
    ("solr-4-to-9", 0): ("replace", "solr/policies/conf/solrconfig.xml", "4.10.4</lucene", "9.11</lucene"),
    ("java-8-to-25", 4): ("delete", "src/main/resources/log4j.properties"),
}


def test_companions_run_between_the_java_17_stage_and_the_spring_boot_stages(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PREFLIGHT", "off")
    repo = tmp_path / "policy"
    shutil.copytree(FIXTURE, repo)
    run = pipeline.start(repo, "java-8-to-25", migration_strategy="incremental", springboot_upgrade=True)
    assert {r["pattern"] for r in run.state["recommendations"]} == {"oracle-19c-to-23ai", "solr-4-to-9"}
    pipeline.next_step(Run.load(repo))
    pipeline.confirm(Run.load(repo), "companions", ["oracle-19c-to-23ai", "solr-4-to-9"])

    order, audits, deleted_by_oracle = [], {}, None
    for _ in range(120):
        step, _ = pipeline.next_step(Run.load(repo))
        sid = step["id"]
        if step["kind"] == "done":
            break
        if sid == "plan-review":
            pipeline.confirm(Run.load(repo), "plan")
            continue
        r = Run.load(repo)
        code = r.state.get("code") or {}
        if sid.startswith("plan-"):
            pattern = sid[len("plan-"):]
            text = JAVA_PLAN if pattern == "java-8-to-25" else COMPANION_PLANS[pattern]
        elif sid.startswith("modify-"):
            stage = code["stages"][code["si"]]
            order.append(f"{code['pattern']}:{stage['idx']}")
            edit = EDITS.get((code["pattern"], stage["idx"]))
            if edit and edit[0] == "replace":
                assert _tool(mcp_server.ws_replace_in_file, path=edit[1], old_text=edit[2], new_text=edit[3],
                             workspace=str(repo)).startswith("Replaced")
            elif edit:
                assert _tool(mcp_server.ws_delete_file, path=edit[1], workspace=str(repo)).startswith("Deleted")
            if code["pattern"] == "oracle-19c-to-23ai":
                deleted_by_oracle = _tool(mcp_server.ws_delete_file, path="pom.xml", workspace=str(repo))
            text = "## Modify Result\ndone"
        elif sid.startswith("validate-"):
            assert _tool(mcp_server.ws_signal_build_success, workspace=str(repo)).startswith("Build success")
            text = json.dumps({"passed": True, "errors": [], "summary": "ok"})
        elif sid.startswith("review-"):
            audits[code["pattern"]] = _tool(mcp_server.ws_audit_changes, workspace=str(repo))
            text = "# Review"
        else:
            text = "# Output"
        assert _tool(mcp_server.save_output, step_id=sid, content=text, workspace=str(repo)).startswith("Saved")
        pipeline.complete_step(Run.load(repo), sid)
    else:
        pytest.fail("the run did not finish")

    # The readiness stages and the Java 17 stage first, then the companions, then the Boot stages.
    assert order == ["java-8-to-25:1", "java-8-to-25:3", "oracle-19c-to-23ai:0", "solr-4-to-9:0", "java-8-to-25:4"]
    assert not (repo / "src/main/resources/log4j.properties").exists()
    assert deleted_by_oracle.startswith("ERROR") and (repo / "pom.xml").is_file()   # only Java 8 -> 25 deletes
    # Each review sets aside what only the other migrations changed.
    assert "`src/main/java/com/acme/policy/util/ExportSigner.java` (java-8-to-25)" in audits["oracle-19c-to-23ai"]
    assert "`src/main/resources/db/schema.sql` (oracle-19c-to-23ai)" in audits["java-8-to-25"]
    assert "`solr/policies/conf/solrconfig.xml` (solr-4-to-9)" in audits["java-8-to-25"]
    java_changed = Run.load(repo).state["pass_changes"]["java-8-to-25"]
    assert {"pom.xml", "src/main/resources/log4j.properties"} <= set(java_changed)


def test_a_plan_that_leaves_out_a_legacy_file_is_flagged_before_approval():
    from agents.shared import plan_contract
    spec = ("## Legacy Stack Blockers\n\n| File | Lines | Finding | First match | Note |\n|---|---|---|---|---|\n"
            "| `pom.xml` | 25 | legacy Oracle JDBC driver | `ojdbc6` | |\n"
            "| `src/main/resources/db/schema.sql` | 7 | LONG / LONG RAW column | `LONG` | |\n"
            "| `src/main/resources/policy.properties` | 1 | SID connect string | `url` | |\n\n## Repo Facts\n")
    thin = "## 1. What Changes\n### File Change Manifest\n| File | Change |\n|---|---|\n| `pom.xml` | ojdbc11 |\n" \
           "| `src/main/resources/*.properties` | service URL |\n"
    gaps = plan_contract.manifest_gaps(thin, spec)
    assert gaps == [("src/main/resources/db/schema.sql", ["LONG / LONG RAW column"])]    # globs count as covered
    assert "schema.sql" in plan_contract.to_markdown(plan_contract.check(thin), gaps)


def test_the_web_pipeline_runs_companions_after_the_java_17_stage(tmp_path, monkeypatch):
    import asyncio
    import main
    (tmp_path / "pom.xml").write_text("<project/>")
    states = {"outer": {"workspace_dir": str(tmp_path), "baseline_dir": str(tmp_path), "pattern": "java-8-to-25",
                        "migration_strategy": "incremental", "springboot_upgrade": "true"}}
    calls = []

    async def get_state(sid):
        return states.setdefault(sid, {})

    async def update_state(sid, delta):
        states.setdefault(sid, {}).update(delta)

    async def create(pattern, *args):
        states[pattern] = {"pattern": pattern}
        return pattern

    async def java(sid, push_session_id=None, between=None):
        calls.append("java:stages 1-3")
        (tmp_path / "pom.xml").write_text("<project>17</project>")
        await between()
        calls.append("java:stages 4-8")
        calls.append(("java review sets aside", main.change_audit.other_migrations_files(states[sid])))

    async def companion(sid, pattern, code_key, push_session_id=None):
        calls.append(pattern)
        (tmp_path / f"{pattern}.txt").write_text("x")

    async def push(*a, **k):
        return None
    monkeypatch.setattr(main, "_get_state", get_state)
    monkeypatch.setattr(main, "_update_state", update_state)
    monkeypatch.setattr(main, "_create_pattern_session", create)
    monkeypatch.setattr(main, "_run_java8_incremental_code_step", java)
    monkeypatch.setattr(main, "_run_workspace_code_step", companion)
    monkeypatch.setattr(main, "_push", push)
    asyncio.run(main._run_bundle_code_generation("outer", ["oracle-19c-to-23ai", "solr-4-to-9", "java-8-to-25"]))
    assert calls[:4] == ["java:stages 1-3", "oracle-19c-to-23ai", "solr-4-to-9", "java:stages 4-8"]
    assert calls[4] == ("java review sets aside", {"oracle-19c-to-23ai.txt": "oracle-19c-to-23ai",
                                                     "solr-4-to-9.txt": "solr-4-to-9"})
