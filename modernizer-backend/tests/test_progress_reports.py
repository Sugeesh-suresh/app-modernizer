"""While next_step runs slow deterministic work (the preflight's Maven builds, scans), the person sees what is
running instead of "Thinking…" (agents/shared/progress.py, cli/mcp_server.py)."""
import shutil
import sys
import threading
from pathlib import Path

import anyio
import pytest

from agents import config
from agents.shared import java_env, progress
from cli import mcp_server, pipeline
from cli.runstate import Run

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MODERNIZER_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MODERNIZER_WORKSPACE", raising=False)
    monkeypatch.setattr(config, "PROGRESS_FIRST_REPORT_SECONDS", 1)
    monkeypatch.setattr(config, "PROGRESS_REPORT_SECONDS", 1)
    mcp_server._WORKERS.clear()
    yield
    mcp_server._WORKERS.clear()
    progress.activate(None)


def test_the_report_says_what_maven_is_doing():
    t = progress.Tracker(title="Working")
    t.stage("Environment check: finding the JDKs")
    t.history.clear()                                   # instant stages are not reported; pretend it took time
    t.current_since -= 5
    t.stage("Environment check: baseline build of `rest` (2 of 3) on JDK 8")
    for line in ("[INFO] Building security-rest 1.0   [2/5]",
                 "Downloaded from nexus: https://repo/org/springframework/spring-core/3.2.18/spring-core-3.2.18.jar (1 MB)",
                 "Downloaded from nexus: https://repo/junit/junit/4.12/junit-4.12.jar (300 kB)",
                 "[INFO] --- maven-compiler-plugin:3.1:compile (default-compile) @ security-rest ---",
                 "[ERROR] /src/A.java:[3,1] cannot find symbol",
                 "[INFO] Compiling 214 source files"):
        t.output(line)
    report = t.report()
    assert "**Now:** Environment check: baseline build of `rest` (2 of 3) on JDK 8" in report
    assert "building `security-rest 1.0 [2/5]`" in report
    assert "step `maven-compiler-plugin:3.1:compile`" in report
    assert "2 artifact(s) downloaded, last `junit-4.12.jar`" in report
    assert "1 `[ERROR]` line(s)" in report
    assert "`[INFO] Compiling 214 source files`" in report
    assert "Finished so far:\n- Environment check: finding the JDKs (5s)" in report


def test_credentials_and_jvm_banners_never_reach_a_report():
    t = progress.Tracker()
    t.stage("Building")
    t.output("Picked up JAVA_TOOL_OPTIONS: -Dhttps.proxyHost=proxy -Dhttps.proxyPassword=hunter2")
    assert t.command is None                                  # not even counted
    t.output("[INFO] Downloading from corp: https://builder:s3cr3t@nexus.corp/repo/a.pom")
    assert "s3cr3t" not in t.report() and "https://***@nexus.corp/repo/a.pom" in t.report()
    t.output("[ERROR] Failed: -Ddb.password=hunter2 token: abc123")
    assert "hunter2" not in t.report() and "abc123" not in t.report()


def test_without_a_tracker_nothing_is_recorded_or_streamed():
    assert progress.active() is None and not progress.wants_output()
    progress.stage("ignored")                           # no tracker: a no-op, never an error
    code, out = java_env._run([sys.executable, "-c", "print('a'); print('b')"], Path.cwd(), dict(__import__("os").environ), 30)
    assert (code, out.split()) == (0, ["a", "b"])


def test_a_command_streams_its_lines_to_the_active_tracker(tmp_path):
    t = progress.Tracker()
    progress.activate(t)
    t.stage("Building")
    script = "import sys\nprint('[INFO] Building demo 1.0')\nprint('err line', file=sys.stderr)\nsys.exit(3)\n"
    code, out = java_env._run([sys.executable, "-c", script], tmp_path, dict(__import__("os").environ), 30)
    assert code == 3                                    # the exit code and the whole output, as before
    assert "[INFO] Building demo 1.0" in out and "err line" in out
    assert t.command.module == "demo 1.0" and t.command.lines == 2
    code, out = java_env._run([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path,
                              dict(__import__("os").environ), 1)
    assert code == 124 and out.startswith("TIMEOUT after 1s")
    assert java_env._run(["no-such-binary-xyz"], tmp_path, {}, 5)[0] == 127


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "shop"
    shutil.copytree(FIXTURES / "thymeleaf-rules", repo)
    pipeline.start(repo, "stack-discovery")
    return repo


def test_next_step_reports_progress_and_reattaches_instead_of_restarting(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    release, calls = threading.Event(), []

    def slow_next_step(run):
        calls.append(1)
        progress.stage("Environment check: baseline build of `.` (1 of 1) on JDK 8")
        progress.output("[INFO] Building shop 1.0")
        release.wait(30)
        return {"id": "select-stacks", "kind": "ask_user", "title": "Choose", "text": "Pick the stacks."}, ["Built."]

    monkeypatch.setattr(mcp_server.pipeline, "next_step", slow_next_step)
    first = anyio.run(lambda: mcp_server.next_step(workspace=str(repo)))
    assert first.startswith("## Still working — no step for you yet")
    assert "**Now:** Environment check: baseline build of `.` (1 of 1) on JDK 8" in first
    assert "building `shop 1.0`" in first and "call `next_step` again" in first

    status = anyio.run(lambda: mcp_server.run_status(workspace=str(repo)))
    assert status.startswith("## In progress") and "baseline build" in status   # not blocked by the busy run

    again = anyio.run(lambda: mcp_server.next_step(workspace=str(repo)))
    assert again.startswith("## Still working") and len(calls) == 1               # the same work, not a new one
    release.set()
    done = anyio.run(lambda: mcp_server.next_step(workspace=str(repo)))
    assert "## Next: Choose" in done and "- Built." in done and len(calls) == 1
    assert not mcp_server._WORKERS and progress.active() is None


def test_a_result_nobody_collected_is_returned_unless_the_run_moved_on(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    answers = iter(["first", "second", "third"])

    def quick(run):
        return {"id": next(answers), "kind": "ask_user", "title": "Q", "text": ""}, []

    monkeypatch.setattr(mcp_server.pipeline, "next_step", quick)
    key = str(repo.resolve())
    worker = mcp_server._WORKERS[key] = mcp_server._start_worker(key, str(repo))   # e.g. Gemini cancelled the wait
    assert worker.done.wait(10)
    assert "step_id: `first`" in anyio.run(lambda: mcp_server.next_step(workspace=str(repo)))

    worker = mcp_server._WORKERS[key] = mcp_server._start_worker(key, str(repo))
    assert worker.done.wait(10)
    run = Run.load(repo)
    run.state["touched"] = True                                       # another tool changed the run since
    run.save()
    import os
    os.utime(repo / ".modernizer" / "run.json", (1, 1))
    assert "step_id: `third`" in anyio.run(lambda: mcp_server.next_step(workspace=str(repo)))


def test_the_command_line_echoes_each_stage(tmp_path, monkeypatch, capsys):
    from cli import __main__ as cli_main
    repo = _repo(tmp_path)

    def staged(run):
        progress.stage("Analysis: the inventory")
        return {"id": "x", "kind": "ask_user", "title": "X", "text": ""}, []

    monkeypatch.setattr(pipeline, "next_step", staged)
    cli_main.main(["--workspace", str(repo), "next"])
    assert "[modernizer] Analysis: the inventory" in capsys.readouterr().err
    assert progress.active() is None


def test_each_wait_names_a_new_poll_number_so_the_calls_are_never_identical(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    release = threading.Event()
    monkeypatch.setattr(mcp_server.pipeline, "next_step",
                        lambda run: (release.wait(30), ({"id": "x", "kind": "ask_user", "title": "X", "text": ""}, []))[1])
    first = anyio.run(lambda: mcp_server.next_step(workspace=str(repo)))
    assert "call `next_step` again with `poll=1`" in first
    second = anyio.run(lambda: mcp_server.next_step(workspace=str(repo), poll=1))
    assert "`poll=2`" in second
    release.set()
    assert "## Next: X" in anyio.run(lambda: mcp_server.next_step(workspace=str(repo), poll=2))


def test_maven_builds_skip_snapshot_update_checks_and_can_use_their_own_repository(monkeypatch):
    monkeypatch.setattr(config, "MAVEN_SETTINGS", "")
    monkeypatch.setattr(config, "MAVEN_NO_SNAPSHOT_UPDATES", True)
    monkeypatch.setattr(config, "MAVEN_REPO_LOCAL", "")
    assert java_env.maven_settings_args(["clean", "package"]) == ["-nsu"]
    assert java_env.maven_settings_args(["-U", "clean"]) == []                     # the call asked for updates
    assert java_env.maven_settings_args(["-nsu", "clean"]) == []
    monkeypatch.setattr(config, "MAVEN_REPO_LOCAL", "/cache/m2")
    assert java_env.maven_settings_args(["clean"]) == ["-nsu", "-Dmaven.repo.local=/cache/m2"]
    assert java_env.maven_settings_args(["-Dmaven.repo.local=/x", "clean"]) == ["-nsu"]
    monkeypatch.setattr(config, "MAVEN_NO_SNAPSHOT_UPDATES", False)
    assert java_env.maven_settings_args(["clean"]) == ["-Dmaven.repo.local=/cache/m2"]


def test_a_finished_build_is_summarised_in_the_report_and_the_next_step_answer(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    failing = "[INFO] web ... FAILURE [ 1.0 s]\n[INFO] BUILD FAILURE\n[INFO] Total time:  2.0 s\n" \
              "[ERROR] /w/A.java:[4,2] cannot find symbol\n"

    def build_step(run):
        progress.stage("Environment check: baseline build")
        monkeypatch.setattr(java_env, "_run", lambda *a, **k: (1, failing))
        monkeypatch.setattr(java_env, "maven_executable", lambda cwd=None: "mvn")
        java_env.run_maven(repo, ["-fae", "clean", "package", "-Dx=1"])
        return {"id": "x", "kind": "ask_user", "title": "X", "text": ""}, []

    monkeypatch.setattr(mcp_server.pipeline, "next_step", build_step)
    answer = anyio.run(lambda: mcp_server.next_step(workspace=str(repo)))
    assert "### Build summary" in answer and "maven build FAILED" in answer and "A.java:4 cannot find symbol" in answer
    assert "`mvn -fae clean package`" in answer and "-Dx=1" not in answer


def test_run_command_appends_the_build_summary_for_maven_only(tmp_path, monkeypatch):
    from agents.shared import workspace_tools as wt
    import subprocess
    monkeypatch.setattr(wt, "workspace_root", lambda ctx: tmp_path)
    monkeypatch.setattr(wt, "resolve_within_workspace", lambda ctx, sub: tmp_path)
    monkeypatch.setattr(wt, "_resolve_executable", lambda exe, cwd: exe)

    class R:
        returncode, stdout, stderr = 0, "[INFO] BUILD SUCCESS\n[INFO] Total time:  1.0 s\n", ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    run = wt.make_run_command({"mvn", "javac"})
    assert run(None, "mvn -q test").endswith("Build summary: maven build PASSED (1.0 s)")
    assert "Build summary" not in run(None, "javac A.java")
