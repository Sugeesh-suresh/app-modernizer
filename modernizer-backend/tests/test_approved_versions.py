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
