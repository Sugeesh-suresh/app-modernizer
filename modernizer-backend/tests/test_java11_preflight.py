"""
Java 8 -> 11: the environment preflight before planning, the compile-first
evidence it hands the planner, and the validator's build tool (tests run,
pre-existing failures excluded, download failures told apart).
"""
import asyncio
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from agents import APP_NAME, USER_ID, config, session_service
from agents.java_8_to_11 import preflight, tools
from agents.shared import java_env

P = "java-8-to-11"

COMPILE_OUT = """[INFO] Building acme-app 1.0-SNAPSHOT
[ERROR] COMPILATION ERROR :
[ERROR] /ws/top/app/src/main/java/com/acme/Codec.java:[2,22] package javax.xml.bind does not exist
[ERROR] /ws/top/app/src/main/java/com/acme/Codec.java:[3,66] cannot find symbol
  symbol:   variable DatatypeConverter
[ERROR] Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin:3.8.1:compile (default-compile) on project acme-app: Compilation failure: Compilation failure:
[ERROR] /ws/top/app/src/main/java/com/acme/Codec.java:[2,22] package javax.xml.bind does not exist
[ERROR] /ws/top/app/src/main/java/com/acme/Codec.java:[3,66] cannot find symbol
[ERROR]   symbol:   variable DatatypeConverter
[ERROR]   location: class com.acme.Codec
[ERROR] -> [Help 1]
[INFO] acme-web ........................................... SKIPPED
[ERROR] To see the full stack trace of the errors, re-run Maven with the -e switch.
[ERROR] After correcting the problems, you can resume the build with the command
[ERROR]   mvn <args> -rf :acme-app
"""
RESOLVE_OUT = """[ERROR] Failed to execute goal on project acme-app: Could not resolve dependencies for project com.acme:acme-app:war:1.0-SNAPSHOT
[ERROR] dependency: org.powermock:powermock-api-mockito:jar:2.0.9 (test)
[ERROR] \torg.powermock:powermock-api-mockito:jar:2.0.9 was not found in https://nexus.example/public during a previous attempt.
[ERROR] -> [Help 1]
"""
UNAUTHORIZED_OUT = """[ERROR] Failed to execute goal on project acme-app: Could not resolve dependencies for project com.acme:acme-app:jar:1.0
[ERROR] Failed to read artifact descriptor for com.acme.internal:auth-client:jar:4.2.0
[ERROR] Could not transfer artifact com.acme.internal:auth-client:pom:4.2.0 from/to corp (https://nexus.example/repo): status code: 401, reason phrase: Unauthorized (401)
"""


# ---------------------------------------------------------------------------
# Reading Maven output
# ---------------------------------------------------------------------------

class TestClassify:
    def test_compile_errors_are_folded_deduplicated_and_relative(self):
        res = java_env.classify(COMPILE_OUT, 1, Path("/ws/top"))
        assert res.compile == [
            "app/src/main/java/com/acme/Codec.java:2 — package javax.xml.bind does not exist",
            "app/src/main/java/com/acme/Codec.java:3 — cannot find symbol (symbol: variable DatatypeConverter)"
            " (location: class com.acme.Codec)",
        ]
        assert res.other == [] and res.environment == []                      # help footer is noise
        assert res.skipped == ["acme-web"]

    def test_a_missing_artifact_names_the_artifact_not_the_project(self):
        res = java_env.classify(RESOLVE_OUT, 1)
        assert len(res.environment) == 1 and "powermock-api-mockito:jar:2.0.9" in res.environment[0]
        assert res.coordinates == ["org.powermock:powermock-api-mockito:2.0.9"]

    def test_unauthorized_is_an_environment_error(self):
        res = java_env.classify(UNAUTHORIZED_OUT, 1)
        assert res.environment and "com.acme.internal:auth-client:4.2.0" in res.coordinates
        assert not res.ok

    @pytest.mark.parametrize("text, major", [
        ('openjdk version "1.8.0_392"', 8), ('openjdk version "11.0.22" 2024-01-16', 11),
        ("Java version: 11.0.22, vendor: Eclipse Adoptium", 11), ("Java version: 1.8.0_392", 8),
        ('java version "21"', 21), ("nothing", None),
    ])
    def test_java_major(self, text, major):
        assert java_env.java_major(text) == major

    def test_surefire_reports(self, tmp_path):
        d = tmp_path / "app/target/surefire-reports"
        d.mkdir(parents=True)
        (d / "TEST-com.acme.SvcTest.xml").write_text(
            '<testsuite><testcase classname="com.acme.SvcTest" name="ok"/>'
            '<testcase classname="com.acme.SvcTest" name="bad"><failure message="expected:&lt;1&gt; but was:&lt;2&gt;" '
            'type="java.lang.AssertionError">trace</failure></testcase>'
            '<testcase classname="com.acme.SvcTest" name="boom"><error type="java.lang.ClassCastException"/></testcase>'
            '</testsuite>')
        report = java_env.surefire_report(tmp_path)
        assert [r[0] for r in report] == ["com.acme.SvcTest#bad", "com.acme.SvcTest#boom"]
        assert report[0][1] == "java.lang.AssertionError: expected:<1> but was:<2>"

    def test_build_env_puts_the_migration_jdk_first(self, monkeypatch):
        monkeypatch.setattr(config, "MIGRATION_JAVA_HOME", "/opt/jdk-11")
        env = java_env.build_env()
        assert env["JAVA_HOME"] == "/opt/jdk-11" and env["PATH"].startswith(str(Path("/opt/jdk-11/bin")))

    def test_maven_settings_are_added_once(self, monkeypatch):
        monkeypatch.setattr(config, "MAVEN_SETTINGS", "/etc/m2/settings.xml")
        assert java_env.maven_settings_args(["package"]) == ["-s", "/etc/m2/settings.xml"]
        assert java_env.maven_settings_args(["-s", "x.xml", "package"]) == []


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def _repo(root: Path) -> Path:
    (root / "top/app").mkdir(parents=True)
    (root / "top/pom.xml").write_text("<project><artifactId>p</artifactId><modules><module>app</module></modules></project>")
    (root / "top/app/pom.xml").write_text("<project><artifactId>a</artifactId></project>")
    return root


def _tc(maven_java=11, problems=()):
    return java_env.Toolchain(os="Windows 10", java="openjdk 11.0.22", java_major=11, maven="Apache Maven 3.9.6",
                              maven_version="3.9.6", maven_java_major=maven_java, problems=list(problems))


class TestPreflight:
    def test_maven_roots_are_the_aggregators(self, tmp_path):
        assert [r.relative_to(tmp_path).as_posix() for r in preflight.maven_roots(_repo(tmp_path))] == ["top"]

    def test_a_wrong_jdk_stops_before_any_build(self, tmp_path, monkeypatch):
        builds = []
        monkeypatch.setattr(java_env, "probe", lambda *a, **k: _tc(8, ["Maven runs on Java 8, not Java 11."]))
        monkeypatch.setattr(java_env, "run_maven", lambda *a, **k: builds.append(a) or (0, ""))
        pf = preflight.run(str(_repo(tmp_path)))
        assert not pf.ok and "Java 8" in pf.stop_reason and builds == []

    def test_an_uploaded_dependency_that_cannot_download_stops_the_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr(java_env, "probe", lambda *a, **k: _tc())
        monkeypatch.setattr(java_env, "run_maven", lambda *a, **k: (1, UNAUTHORIZED_OUT))
        pf = preflight.run(str(_repo(tmp_path)))
        assert not pf.ok
        assert "com.acme.internal:auth-client:4.2.0" in pf.stop_reason and "settings.xml" in pf.stop_reason

    def test_compile_errors_are_the_work_list_not_a_stop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(java_env, "probe", lambda *a, **k: _tc())
        monkeypatch.setattr(java_env, "run_maven", lambda *a, **k: (1, COMPILE_OUT.replace("/ws/top", str(tmp_path / "top"))))
        pf = preflight.run(str(_repo(tmp_path)))
        assert pf.ok and pf.baseline_build_ok is False
        assert pf.compile_errors[0] == "top/app/src/main/java/com/acme/Codec.java:2 — package javax.xml.bind does not exist"
        md = preflight.to_markdown(pf)
        assert "| `top/app/src/main/java/com/acme/Codec.java:2` | package javax.xml.bind does not exist |" in md
        assert "acme-web" in md                                                       # skipped modules named

    def test_baseline_tests_run_on_the_baseline_jdk_when_configured(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "BASELINE_JAVA_HOME", "/opt/jdk-8")
        calls = []

        def probe(cwd, java_home=None, target=11):
            return _tc() if java_home is None else java_env.Toolchain(java_major=8)

        def run_maven(root, args, java_home=None, timeout=None):
            calls.append((args, java_home))
            if java_home == "/opt/jdk-8":
                d = root / "app/target/surefire-reports"
                d.mkdir(parents=True, exist_ok=True)
                (d / "TEST-T.xml").write_text('<testsuite><testcase classname="T" name="old"><failure/></testcase></testsuite>')
            return 0, ""
        monkeypatch.setattr(java_env, "probe", probe)
        monkeypatch.setattr(java_env, "run_maven", run_maven)
        pf = preflight.run(str(_repo(tmp_path)))
        assert pf.ok and pf.baseline_build_ok and pf.baseline_failing_tests == ["T#old"]
        assert calls[0][1] == "/opt/jdk-8" and "test" in calls[0][0]
        assert calls[1][1] is None and "package" in calls[1][0] and "-DskipTests" in calls[1][0]


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

def _session(tmp_path) -> str:
    ws = _repo(tmp_path / "ws")
    state = main._initial_state(P, str(ws), str(ws), "[]", "bigbang", False, False)
    sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
    main._sse_queues[sid] = asyncio.Queue()
    for gates in (main._brd_gates, main._plan_gates, main._companion_gates):
        gates[sid] = asyncio.Event()
        gates[sid].set()
    return sid


def _events(sid):
    out, q = [], main._sse_queues[sid]
    while not q.empty():
        raw = q.get_nowait()
        if raw:
            out += [json.loads(l[6:]) for l in raw.splitlines() if l.startswith("data: ")]
    return out


class TestWorkflow:
    def test_a_failed_preflight_stops_the_run_before_planning(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "PREFLIGHT", "on")
        steps = []

        async def no_step(*a, **k):
            steps.append(a)
        monkeypatch.setattr(main, "_run_step", no_step)
        monkeypatch.setattr(preflight, "run", lambda ws: preflight.Preflight(
            ok=False, stop_reason="Maven runs on Java 8, not Java 11.", toolchain={"maven_java_major": 8}))
        sid = _session(tmp_path)
        asyncio.run(main._run_workflow(sid))
        events = _events(sid)
        assert [e["step"] for e in events if e["type"] == "step-change"] == ["dependency-graph", "preflight"]
        error = next(e for e in events if e["type"] == "error")
        assert "nothing was changed" in error["message"] and "Java 8" in error["message"]
        assert steps == []                                                          # no model call

    def test_the_baseline_build_reaches_the_planner(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "PREFLIGHT", "on")
        seen = {}

        async def plan_step(session_id, step_key, pattern, message, sse_event_type):
            seen.update(await main._get_state(session_id))
            await main._update_state(session_id, {"plan": "# plan"})

        async def code(*a, **k):
            return None
        monkeypatch.setattr(main, "_run_step", plan_step)
        monkeypatch.setattr(main, "_run_java11_code_step", code)
        monkeypatch.setattr(preflight, "run", lambda ws: preflight.Preflight(
            toolchain={"maven_version": "3.9.6", "maven_java_major": 11, "os": "Windows 10"}, roots=["top"],
            baseline_build_ok=False, compile_errors=["top/app/X.java:2 — package javax.xml.bind does not exist"]))
        sid = _session(tmp_path)
        asyncio.run(main._run_workflow(sid))
        assert seen["technical_spec"].startswith("## Baseline Build on JDK 11")          # first thing the planner reads
        assert "package javax.xml.bind does not exist" in seen["technical_spec"]
        assert "Maven 3.9.6 on Java 11" in seen["preflight_summary"]
        steps = [e["step"] for e in _events(sid) if e["type"] == "step-change"]
        assert steps[:3] == ["dependency-graph", "preflight", "plan-generation"]

    def test_upload_says_whether_the_run_has_a_preflight(self, monkeypatch):
        from fastapi.testclient import TestClient
        import io, zipfile
        monkeypatch.setattr(config, "PREFLIGHT", "on")
        monkeypatch.setattr(main, "_run_workflow", lambda sid: asyncio.sleep(0))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("pom.xml", "<project/>")
        with TestClient(main.app) as client:
            for pattern, expected in ((P, True), ("java-8-to-25", False)):
                res = client.post("/api/upload", data={"pattern": pattern},
                                  files={"file": ("r.zip", buf.getvalue(), "application/zip")})
                assert res.json()["preflight"] is expected, pattern


# ---------------------------------------------------------------------------
# Validator's build tool
# ---------------------------------------------------------------------------

def _ctx(tmp_path, preflight_json="") -> SimpleNamespace:
    base = _repo(tmp_path / "base")
    ws = _repo(tmp_path / "ws")
    return SimpleNamespace(state={"workspace_dir": str(ws), "baseline_dir": str(base),
                                  "preflight_json": preflight_json}, actions=SimpleNamespace())


class TestBuildTool:
    def _with_pom_dep(self, ctx, group, artifact, version, where="base"):
        for which in (["base", "ws"] if where == "both" else [where]):
            pom = Path(ctx.state["baseline_dir" if which == "base" else "workspace_dir"]) / "top/app/pom.xml"
            pom.write_text(f"<project><artifactId>a</artifactId><dependencies><dependency><groupId>{group}</groupId>"
                           f"<artifactId>{artifact}</artifactId><version>{version}</version></dependency>"
                           "</dependencies></project>")

    def test_a_coordinate_the_migration_set_is_a_dependency_error(self, tmp_path, monkeypatch):
        ctx = _ctx(tmp_path)
        self._with_pom_dep(ctx, "org.powermock", "powermock-api-mockito", "1.7.4", "base")
        self._with_pom_dep(ctx, "org.powermock", "powermock-api-mockito", "2.0.9", "ws")
        monkeypatch.setattr(java_env, "run_maven", lambda *a, **k: (1, RESOLVE_OUT))
        out = tools.run_java11_build(ctx)
        assert "DEPENDENCY: org.powermock:powermock-api-mockito:2.0.9 — introduced or changed" in out
        assert out.endswith("BUILD: FAIL (1 error(s))") and ctx.state["java11_build_passed"] is False

    def test_a_coordinate_as_uploaded_is_an_environment_error(self, tmp_path, monkeypatch):
        ctx = _ctx(tmp_path)
        self._with_pom_dep(ctx, "com.acme.internal", "auth-client", "4.2.0", "both")
        monkeypatch.setattr(java_env, "run_maven", lambda *a, **k: (1, UNAUTHORIZED_OUT))
        out = tools.run_java11_build(ctx)
        assert "ENVIRONMENT:" in out and "not fixable in the code" in out and "DEPENDENCY:" not in out

    def test_tests_run_and_pre_existing_failures_are_not_errors(self, tmp_path, monkeypatch):
        ctx = _ctx(tmp_path, json.dumps({"baseline_failing_tests": ["T#old"], "baseline_tests_run": True}))
        calls = []

        def run_maven(root, args, java_home=None, timeout=None):
            calls.append(args)
            d = root / "app/target/surefire-reports"
            d.mkdir(parents=True, exist_ok=True)
            (d / "TEST-T.xml").write_text('<testsuite><testcase classname="T" name="old"><failure/></testcase>'
                                          '<testcase classname="T" name="new"><error type="java.lang.ClassCastException" '
                                          'message="AppClassLoader cannot be cast to URLClassLoader"/></testcase></testsuite>')
            return 0, "[INFO] BUILD SUCCESS"
        monkeypatch.setattr(java_env, "run_maven", run_maven)
        out = tools.run_java11_build(ctx)
        assert "-DskipTests" not in calls[0] and "-Dmaven.test.failure.ignore=true" in calls[0]
        assert "TEST: T#new — java.lang.ClassCastException: AppClassLoader cannot be cast to URLClassLoader" in out
        assert "PRE-EXISTING" in out and "T#old" in out.split("PRE-EXISTING")[1]
        assert out.endswith("BUILD: FAIL (1 error(s))")

    def test_signal_build_success_is_refused_after_a_failed_build(self, tmp_path):
        ctx = _ctx(tmp_path)
        ctx.state["java11_build_passed"] = False
        assert tools.signal_build_success(ctx).startswith("ERROR: build success NOT signalled")


# ---------------------------------------------------------------------------
# Real Maven (runs where a JDK 11 and Maven are installed)
# ---------------------------------------------------------------------------

_JDK11 = os.getenv("TEST_JDK11_HOME", "/usr/lib/jvm/java-11-openjdk-amd64")


@pytest.mark.skipif(not (shutil.which("mvn") and Path(_JDK11, "bin/java").exists() and os.getenv("RUN_MAVEN_IT")),
                    reason="needs Maven, a JDK 11 (TEST_JDK11_HOME) and RUN_MAVEN_IT=1 (downloads plugins)")
def test_real_maven_preflight_finds_what_jdk_11_breaks(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MIGRATION_JAVA_HOME", _JDK11)
    root = tmp_path / "top"
    (root / "src/main/java/a").mkdir(parents=True)
    (root / "pom.xml").write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion><groupId>t</groupId>'
        '<artifactId>t</artifactId><version>1</version><properties><maven.compiler.source>1.8</maven.compiler.source>'
        '<maven.compiler.target>1.8</maven.compiler.target></properties><build><plugins><plugin>'
        '<artifactId>maven-compiler-plugin</artifactId><version>3.8.1</version></plugin></plugins></build></project>')
    (root / "src/main/java/a/C.java").write_text("package a; import javax.xml.bind.DatatypeConverter; class C {}")
    pf = preflight.run(str(tmp_path))
    assert pf.ok and pf.toolchain["maven_java_major"] == 11
    assert any("package javax.xml.bind does not exist" in e for e in pf.compile_errors), pf
