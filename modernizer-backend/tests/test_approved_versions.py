"""
The organisation's approved versions: parsed from a file the team maintains,
given to the agents, enforced by validation, and checked to download before
planning.
"""
import asyncio
from pathlib import Path

import pytest

import main
from agents import APP_NAME, USER_ID, config, session_service
from agents.java_8_to_11 import agents as j11, preflight
from agents.shared import approved_versions as av, java_env, scope_fence

LIST = """# comment
org.mockito:mockito-core = 2.28.2
org.powermock:powermock-api-mockito2 = 2.0.9   # renamed module
org.springframework:* = 5.3.34
"""


def _pom(root: Path, deps: list[tuple[str, str, str]]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    body = "".join(f"<dependency><groupId>{g}</groupId><artifactId>{a}</artifactId><version>{v}</version></dependency>"
                   for g, a, v in deps)
    (root / "pom.xml").write_text(f"<project><artifactId>x</artifactId><dependencies>{body}</dependencies></project>")
    return root


@pytest.fixture
def listed(tmp_path, monkeypatch):
    f = tmp_path / "approved-versions.txt"
    f.write_text(LIST)
    monkeypatch.setattr(config, "APPROVED_VERSIONS_FILE", str(f))
    return f


def test_parse_and_lookup(listed):
    entries, problems = av.load()
    assert problems == [] and [e.coordinate for e in entries] == [
        "org.mockito:mockito-core", "org.powermock:powermock-api-mockito2", "org.springframework:*"]
    assert av.lookup(entries, "org.springframework", "spring-webmvc").version == "5.3.34"   # group wildcard
    assert av.lookup(entries, "org.powermock", "powermock-api-mockito2").note == "renamed module"
    assert av.lookup(entries, "junit", "junit") is None


def test_a_malformed_or_contradictory_list_is_reported(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("org.mockito:mockito-core 2.28.2\na:b = 1\na:b = 2\n")
    _, problems = av.load(str(f))
    assert len(problems) == 2 and "line 1" in problems[0] and "listed twice" in problems[1]


def test_a_version_the_migration_set_against_the_list_fails_validation(listed, tmp_path):
    base = _pom(tmp_path / "b", [("org.mockito", "mockito-core", "1.10.19"), ("junit", "junit", "4.12")])
    ws = _pom(tmp_path / "w", [("org.mockito", "mockito-core", "4.11.0"), ("junit", "junit", "4.12")])
    problems = av.problems(str(base), str(ws))
    assert len(problems) == 1 and "mockito-core:4.11.0` contradicts the approved version `2.28.2`" in problems[0]
    fence, _ = scope_fence.verify_invariants("java-8-to-11", str(base), str(ws))
    assert any("contradicts the approved version" in p for p in fence)


def test_the_listed_version_passes_and_uploaded_versions_are_never_flagged(listed, tmp_path):
    base = _pom(tmp_path / "b", [("org.mockito", "mockito-core", "1.10.19"), ("org.springframework", "spring-core", "4.3.30")])
    ws = _pom(tmp_path / "w", [("org.mockito", "mockito-core", "2.28.2"), ("org.springframework", "spring-core", "4.3.30")])
    assert av.problems(str(base), str(ws)) == []


def test_strict_mode_flags_any_unlisted_introduced_version(listed, tmp_path):
    base = _pom(tmp_path / "b", [("junit", "junit", "4.12")])
    ws = _pom(tmp_path / "w", [("junit", "junit", "4.13.2")])
    assert av.problems(str(base), str(ws)) == []
    strict = av.problems(str(base), str(ws), strict=True)
    assert len(strict) == 1 and "not on the approved-versions list" in strict[0]


def test_the_agents_are_given_the_list(listed, tmp_path):
    for agent in (j11.planner_agent, j11.modifier_agent, j11.fixer_agent):
        assert "{approved_versions?}" in agent.instruction
    state = main._initial_state("java-8-to-11", str(tmp_path), str(tmp_path), "[]", "bigbang", False, False)
    assert "| `org.powermock:powermock-api-mockito2` | `2.0.9` | renamed module |" in state["approved_versions"]
    assert "use exactly this version" in state["approved_versions"]


def test_the_preflight_stops_on_a_broken_list_and_flags_versions_that_do_not_download(listed, tmp_path, monkeypatch):
    (tmp_path / "ws/top").mkdir(parents=True)
    (tmp_path / "ws/top/pom.xml").write_text("<project><artifactId>a</artifactId></project>")
    monkeypatch.setattr(java_env, "probe", lambda *a, **k: java_env.Toolchain(maven_version="3.9.6", maven_java_major=11))
    fetched = []

    def run_maven(root, args, java_home=None, timeout=None):
        if args[0] == "dependency:get":
            fetched.append(args[1])
            if "powermock" in args[1]:
                return 1, ("[ERROR] Failed to execute goal ...: Couldn't download artifact: Could not transfer artifact "
                           "org.powermock:powermock-api-mockito2:jar:2.0.9 from/to corp: status code: 401")
        return 0, ""
    monkeypatch.setattr(java_env, "run_maven", run_maven)
    pf = preflight.run(str(tmp_path / "ws"))
    assert pf.ok and pf.approved_checked == 2                                       # wildcard not fetched
    assert sorted(fetched) == ["-Dartifact=org.mockito:mockito-core:2.28.2",
                               "-Dartifact=org.powermock:powermock-api-mockito2:2.0.9"]
    assert pf.approved_unavailable[0].startswith("org.powermock:powermock-api-mockito2:2.0.9 (line 3)")
    assert "NOT downloadable: org.powermock:powermock-api-mockito2:2.0.9" in preflight.summary(pf)

    listed.write_text("org.mockito:mockito-core 2.28.2\n")
    broken = preflight.run(str(tmp_path / "ws"))
    assert not broken.ok and "approved-versions list" in broken.stop_reason


# ---------------------------------------------------------------------------
# Every pipeline
# ---------------------------------------------------------------------------
import re
from types import SimpleNamespace

from agents.shared import workspace_tools

SCOPED = """org.apache.maven.plugins:maven-surefire-plugin = 2.22.2
org.springframework:* = 5.3.39
[oracle-19c-to-23ai]
com.oracle.database.jdbc:ojdbc11 = 23.5.0.24.07
[java-8-to-25]
org.springframework:* = 6.2.11
[java-8-to-25 stage 3]
org.springframework:* = 5.3.39
[java-8-to-25 stage 6]
org.springframework:* = 6.2.11
"""


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    f = tmp_path / "approved.txt"
    f.write_text(SCOPED)
    monkeypatch.setattr(config, "APPROVED_VERSIONS_FILE", str(f))
    return f


def _versions(entries):
    return {e.coordinate: e.version for e in entries}


def test_the_most_specific_entry_wins(scoped):
    entries, problems = av.load()
    assert problems == []
    assert _versions(av.effective(entries, "solr-4-to-9")) == {
        "org.apache.maven.plugins:maven-surefire-plugin": "2.22.2", "org.springframework:*": "5.3.39"}
    assert _versions(av.effective(entries, "oracle-19c-to-23ai"))["com.oracle.database.jdbc:ojdbc11"] == "23.5.0.24.07"
    assert "com.oracle.database.jdbc:ojdbc11" not in _versions(av.effective(entries, "java-8-to-25"))
    assert _versions(av.effective(entries, "java-8-to-25"))["org.springframework:*"] == "6.2.11"       # bigbang: final
    assert _versions(av.effective(entries, "java-8-to-25", 3))["org.springframework:*"] == "5.3.39"
    assert _versions(av.effective(entries, "java-8-to-25", 6))["org.springframework:*"] == "6.2.11"
    # A stage with no section of its own: only global entries for artifacts no stage section names.
    assert _versions(av.effective(entries, "java-8-to-25", 4)) == {
        "org.apache.maven.plugins:maven-surefire-plugin": "2.22.2"}


def test_a_bad_section_header_is_reported(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("[java-8-to-25 phase 3]\na:b = 1\n")
    assert "not a section header" in av.load(str(f))[1][0]


def _ctx(tmp_path, pattern, base_deps, ws_deps, stage=""):
    base, ws = _pom(tmp_path / "b", base_deps), _pom(tmp_path / "w", ws_deps)
    return SimpleNamespace(state={"pattern": pattern, "baseline_dir": str(base), "workspace_dir": str(ws),
                                  "approved_stage": stage},
                           actions=SimpleNamespace(escalate=False, skip_summarization=False))


@pytest.mark.parametrize("pattern", ["java-8-to-25", "solr-4-to-9", "oracle-19c-to-23ai",
                                     "tibco-ems-to-pubsub", "jsp-to-react-bff"])
def test_every_pipeline_refuses_to_finish_on_a_contradicting_version(scoped, tmp_path, pattern):
    ctx = _ctx(tmp_path, pattern, [("junit", "junit", "4.12")],
               [("junit", "junit", "4.12"), ("org.apache.maven.plugins", "maven-surefire-plugin", "3.2.5")])
    out = workspace_tools.signal_build_success(ctx)
    assert out.startswith("ERROR: build success NOT signalled") and "maven-surefire-plugin:3.2.5" in out
    assert ctx.actions.escalate is False


def test_the_listed_version_lets_the_loop_finish(scoped, tmp_path):
    ctx = _ctx(tmp_path, "oracle-19c-to-23ai", [("com.oracle.database.jdbc", "ojdbc8", "19.3.0.0")],
               [("com.oracle.database.jdbc", "ojdbc11", "23.5.0.24.07")])
    assert workspace_tools.signal_build_success(ctx).startswith("Build success")
    assert ctx.actions.escalate is True


def test_an_incremental_stage_is_held_to_its_own_section(scoped, tmp_path):
    spring_53 = [("org.springframework", "spring-core", "5.3.39")]
    base = [("org.springframework", "spring-core", "4.3.30")]
    assert workspace_tools.signal_build_success(_ctx(tmp_path / "s3", "java-8-to-25", base, spring_53, "3")) \
        .startswith("Build success")
    # The same 5.3.39 at stage 6 contradicts that stage's 6.2.11.
    assert workspace_tools.signal_build_success(_ctx(tmp_path / "s6", "java-8-to-25", base, spring_53, "6")) \
        .startswith("ERROR")


def test_no_list_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPROVED_VERSIONS_FILE", str(tmp_path / "missing.txt"))
    ctx = _ctx(tmp_path, "solr-4-to-9", [], [("org.apache.solr", "solr-solrj", "9.6.1")])
    assert workspace_tools.signal_build_success(ctx).startswith("Build success")


AGENT_MODULES = ["java_8_to_25", "solr_4_to_9", "oracle_19c_to_23ai", "tibco_ems_to_pubsub", "jsp_to_react_bff"]


def _instructions(module):
    import importlib
    from google.adk.agents import LlmAgent
    mod = importlib.import_module(f"agents.{module}.agents")
    found, seen = [], set()

    def walk(agent):
        if id(agent) in seen:
            return
        seen.add(id(agent))
        if isinstance(agent, LlmAgent) and isinstance(agent.instruction, str):
            found.append(agent.instruction)
        for sub in getattr(agent, "sub_agents", []) or []:
            walk(sub)
    for value in vars(mod).values():
        if isinstance(value, LlmAgent) or hasattr(value, "sub_agents"):
            walk(value)
    return found


@pytest.mark.parametrize("module", AGENT_MODULES)
def test_every_list_key_an_agent_reads_is_in_the_session_state(scoped, tmp_path, module):
    state = main._initial_state("java-8-to-25", str(tmp_path), str(tmp_path), "[]", "incremental", False, True)
    keys = {k for text in _instructions(module) for k in re.findall(r"\{(approved_versions[\w]*)\?\}", text)}
    assert keys, module                                                     # the planner/modifier/fixer read one
    for key in keys:
        assert key in state and state[key].startswith("These versions were chosen"), key
    stage_keys = [k for k in state if k.startswith("approved_versions_java_8_to_25_stage")]
    assert len(stage_keys) == 8 and "6.2.11" in state["approved_versions_java_8_to_25_stage6"]


def test_the_list_reaches_a_real_planner_prompt(scoped, tmp_path, monkeypatch):
    """Rendered by ADK itself, not just present in state."""
    from google.adk.models import BaseLlm, LlmResponse
    from google.genai import types
    from agents import PATTERN_RUNNERS
    from agents.oracle_19c_to_23ai import agents as oracle

    seen = []

    class Model(BaseLlm):
        async def generate_content_async(self, req, stream=False):
            seen.append(str(req.config.system_instruction))
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="# plan")]))

    monkeypatch.setattr(oracle.planner_agent, "model", Model(model="scripted"))
    state = main._initial_state("oracle-19c-to-23ai", str(tmp_path), str(tmp_path), "[]", "bigbang", False, False)
    state.update({"brd": "b", "technical_spec": "t", "test_inventory": "i"})
    sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
    main._sse_queues[sid] = asyncio.Queue()
    asyncio.run(main._run_step(sid, "plan", "oracle-19c-to-23ai", "plan", "plan-stream"))
    assert "| `com.oracle.database.jdbc:ojdbc11` | `23.5.0.24.07` |" in seen[0]
    assert "{approved_versions" not in seen[0]
