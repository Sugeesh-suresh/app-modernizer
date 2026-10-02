"""
Hostile and malformed input: uploads, archives, files and API calls that a
real user or a broken client can send. Nothing may return a 500, write outside
the workspace, read local files through XML, or crash an analyser.
"""
import asyncio
import io
import stat
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from agents.java_8_to_11 import inventory as j11
from agents.java_8_to_11 import preflight
from agents.shared import (change_audit, companion_detector, dependency_graph, migration_inventory, plan_paths,
                           pom_facts, scope_fence, stack_detector)


def _zip(entries, symlink=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink[0])
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, symlink[1])
    return buf.getvalue()


@pytest.fixture
def client(monkeypatch):
    async def no_workflow(session_id):
        return None
    monkeypatch.setattr(main, "_run_workflow", no_workflow)
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


@pytest.mark.parametrize("body", [b"not a zip", b"", b"PK\x03\x04truncated"])
def test_an_invalid_archive_is_a_400_not_a_500(client, body):
    res = client.post("/api/upload", data={"pattern": "java-8-to-11"}, files={"file": ("repo.zip", body, "application/zip")})
    assert res.status_code == 400 and "not a valid .zip" in res.json()["detail"]


@pytest.mark.parametrize("name", ["../../escape.java", "..\\..\\escape.java", "/etc/escape.java", ".."])
def test_a_single_file_upload_cannot_write_outside_its_workspace(client, name, monkeypatch, tmp_path):
    created = []
    real = main.tempfile.mkdtemp

    def mkdtemp(*a, **k):
        d = real(dir=tmp_path, *a, **k)
        created.append(Path(d))
        return d
    monkeypatch.setattr(main.tempfile, "mkdtemp", mkdtemp)
    res = client.post("/api/upload", data={"pattern": "java-8-to-11"},
                      files={"file": (name, b"class X {}", "text/plain")})
    assert res.status_code == 200, res.text
    written = [p for p in tmp_path.rglob("*") if p.is_file() and ("escape" in p.name or p.name == "uploaded-source")]
    # The workspace and its baseline snapshot are the only places the file may be.
    assert written and all(any(d in p.parents for d in created) for p in written), written
    assert not any((d / "escape.java").exists() for d in (tmp_path, tmp_path.parent, Path("/etc")))


def test_zip_slip_absolute_paths_and_symlinks_are_not_extracted(tmp_path):
    data = _zip([("../../evil.txt", "x"), ("/abs/evil.txt", "x"), ("ok/A.java", "class A {}")],
                symlink=("ok/link", "/etc/passwd"))
    ws = tmp_path / "ws"
    ws.mkdir()
    res = main._extract_zip_to_dir(data, ws)
    assert res.unsafe >= 2 and (ws / "ok/A.java").is_file()
    assert not (tmp_path / "evil.txt").exists() and not Path("/abs/evil.txt").exists()
    assert not (ws / "ok/link").is_symlink()


def test_xml_cannot_read_local_files_or_expand_without_bound(tmp_path):
    xxe = '<?xml version="1.0"?><!DOCTYPE p [<!ENTITY x SYSTEM "file:///etc/passwd">]><project><artifactId>&x;</artifactId></project>'
    laughs = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">' + "".join(
        f'<!ENTITY {chr(98 + i)} "' + f"&{chr(97 + i)};" * 10 + '">' for i in range(8))
        + ']><project><artifactId>&i;</artifactId></project>')
    (tmp_path / "x").mkdir()
    (tmp_path / "x/pom.xml").write_text(xxe)
    (tmp_path / "l").mkdir()
    (tmp_path / "l/pom.xml").write_text(laughs)
    parsed = pom_facts.parse_pom(tmp_path, "x/pom.xml")
    assert parsed is None or "root:" not in (parsed.artifact or "")
    bomb = pom_facts.parse_pom(tmp_path, "l/pom.xml")
    assert bomb is None or len(bomb.artifact or "") < 1_000_000


HOSTILE = {
    "repo/pom.xml": "<project><artifactId>broken",
    "repo/mod/pom.xml": '﻿<?xml version="1.0"?>\r\n<project xmlns="http://maven.apache.org/POM/4.0.0"><artifactId>m</artifactId>'
                        "<properties><maven.compiler.source>1.8</maven.compiler.source></properties></project>",
    "repo/src/main/java/ünï cødé/Ä.java": "package x;\r\nimport sun.misc.BASE64Encoder;\r\nclass Ä {}\r\n",
    "repo/src/main/java/Bin.java": bytes(range(256)) * 50,
    "repo/src/main/java/Latin1.java": "// caf\xe9 import javax.xml.bind.X;".encode("latin-1"),
    "repo/src/main/java/Huge.java": "import net.sf.ehcache.CacheManager; " + "x" * 2_000_000,
    "repo/db/schema.sql": "CREATE TABLE t (c LONG);\n" * 2000,
    "repo/conf/schema.xml": '<schema version="1.5"><fieldType name="t" class="solr.TrieIntField"/></schema>',
    "repo/src/main/webapp/a.jsp": "<% sun.misc.BASE64Encoder e; %>",
    "repo/empty.java": "",
}


@pytest.fixture
def hostile(tmp_path):
    for rel, data in HOSTILE.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return tmp_path


def test_every_analyser_survives_a_hostile_repository(hostile):
    ws = str(hostile)
    assert "Ä.java" in j11.to_document(j11.build(ws))
    for pattern in migration_inventory.SPECS:
        assert "<!-- SECTION: END -->" in migration_inventory.to_document(pattern, ws)
    for pattern in ["java-8-to-11", "java-8-to-25", "solr-4-to-9", "oracle-19c-to-23ai",
                    "tibco-ems-to-pubsub", "jsp-to-react-bff"]:
        dependency_graph.build_dependency_graph(ws, pattern)
    stack_detector.detect_stacks(ws)
    companion_detector.detect_companions(ws, "java-8-to-25")
    assert [r.name for r in preflight.maven_roots(hostile)] == ["repo"]
    scope_fence.verify_invariants("java-8-to-11", ws, ws)
    change_audit.audit_changes("java-8-to-25", ws, ws)
    fixed, missing = plan_paths.reconcile("| `Ä.java` | x | y |\n- Files: `nope/X.java`\n", ws)[1:]
    assert fixed == {"Ä.java": "repo/src/main/java/ünï cødé/Ä.java"} and missing == ["nope/X.java"]


# ---------------------------------------------------------------------------
# API calls with unknown sessions and out of order
# ---------------------------------------------------------------------------

ENDPOINTS = [
    ("post", "/api/sessions/{sid}/select-companions", {"json": {"selected": []}}),
    ("post", "/api/sessions/{sid}/confirm-brd", {"json": {}}),
    ("post", "/api/sessions/{sid}/refine-brd", {"json": {"feedback": "x"}}),
    ("get", "/api/sessions/{sid}/download/brd", {}),
    ("get", "/api/sessions/{sid}/download/reverse-engineering", {}),
    ("post", "/api/sessions/{sid}/context-files", {"files": {"files": ("a.txt", b"x", "text/plain")}}),
    ("post", "/api/sessions/{sid}/confirm-plan", {"json": {}}),
    ("post", "/api/sessions/{sid}/refine-plan", {"json": {"feedback": "x"}}),
    ("get", "/api/sessions/{sid}/download/plan", {}),
    ("get", "/api/sessions/{sid}/download/code", {}),
    ("get", "/api/sessions/{sid}", {}),
]


@pytest.mark.parametrize("method, path, kwargs", ENDPOINTS, ids=[p for _, p, _ in ENDPOINTS])
def test_unknown_sessions_never_500(client, method, path, kwargs):
    res = getattr(client, method)(path.format(sid="no-such-session"), **kwargs)
    assert res.status_code in (400, 404, 422), (res.status_code, res.text[:200])


@pytest.mark.parametrize("method, path, kwargs", ENDPOINTS, ids=[p for _, p, _ in ENDPOINTS])
def test_calls_at_the_wrong_moment_never_500(client, method, path, kwargs):
    """A fresh session that has not produced a BRD, plan or code yet."""
    buf = _zip([("pom.xml", "<project/>")])
    sid = client.post("/api/upload", data={"pattern": "java-8-to-25"},
                      files={"file": ("r.zip", buf, "application/zip")}).json()["session_id"]
    res = getattr(client, method)(path.format(sid=sid), **kwargs)
    assert res.status_code < 500, (res.status_code, res.text[:200])


def test_bad_request_bodies_are_rejected_cleanly(client):
    buf = _zip([("pom.xml", "<project/>")])
    sid = client.post("/api/upload", data={"pattern": "java-8-to-25"},
                      files={"file": ("r.zip", buf, "application/zip")}).json()["session_id"]
    for path, body in (("refine-brd", {}), ("refine-plan", {"feedback": 3}), ("select-companions", {"selected": "x"})):
        res = client.post(f"/api/sessions/{sid}/{path}", json=body)
        assert res.status_code < 500, (path, res.status_code, res.text[:200])
    res = client.post("/api/upload", data={"pattern": "not-a-pattern"},
                      files={"file": ("r.zip", buf, "application/zip")})
    assert res.status_code == 422


@pytest.mark.parametrize("path", ["confirm-plan", "refine-plan", "confirm-brd", "refine-brd"])
def test_a_review_action_before_its_document_exists_is_refused(client, path):
    """An early confirm would release the gate, and the document would later pass review unseen."""
    buf = _zip([("pom.xml", "<project/>")])
    sid = client.post("/api/upload", data={"pattern": "jsp-to-react-bff"},
                      files={"file": ("r.zip", buf, "application/zip")}).json()["session_id"]
    res = client.post(f"/api/sessions/{sid}/{path}", json={"feedback": "x"} if "refine" in path else {})
    assert res.status_code == 409 and "no" in res.json()["detail"].lower()
    gates = main._plan_gates if "plan" in path else main._brd_gates
    assert not gates[sid].is_set()


def test_a_model_failure_during_refine_is_a_502_with_the_reason(client, monkeypatch):
    buf = _zip([("pom.xml", "<project/>")])
    sid = client.post("/api/upload", data={"pattern": "java-8-to-25"},
                      files={"file": ("r.zip", buf, "application/zip")}).json()["session_id"]
    asyncio.run(main._update_state(sid, {"plan": "# plan"}))

    async def boom(*a, **k):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")
    monkeypatch.setattr(main, "_run_bundle_plan", boom)
    res = client.post(f"/api/sessions/{sid}/refine-plan", json={"feedback": "x"})
    assert res.status_code == 502 and "429" in res.json()["detail"]
    assert sid not in main._refining                                  # the lock is released


def test_two_refines_at_once_are_not_run_concurrently(client):
    buf = _zip([("pom.xml", "<project/>")])
    sid = client.post("/api/upload", data={"pattern": "java-8-to-25"},
                      files={"file": ("r.zip", buf, "application/zip")}).json()["session_id"]
    asyncio.run(main._update_state(sid, {"plan": "# plan"}))
    main._refining.add(sid)
    try:
        assert client.post(f"/api/sessions/{sid}/refine-plan", json={"feedback": "x"}).status_code == 409
        assert client.post(f"/api/sessions/{sid}/confirm-plan", json={}).status_code == 409
    finally:
        main._refining.discard(sid)


# ---------------------------------------------------------------------------
# Pacing under concurrency; Windows command resolution
# ---------------------------------------------------------------------------

def test_the_pacer_under_heavy_concurrency_never_exceeds_its_limits(monkeypatch):
    from agents import config
    from agents.shared import llm_traffic as lt
    monkeypatch.setattr(config, "LLM_LIMITS", "m=tpm:10000,rpm:5")
    clock = {"t": 0.0}
    granted = []

    async def sleep(d):
        clock["t"] += d
        await asyncio.sleep(0)

    pacer = lt.Pacer(clock=lambda: clock["t"], sleep=sleep)

    async def call(i):
        await pacer.acquire("m", 3000)
        granted.append(clock["t"])

    async def main_():
        await asyncio.wait_for(asyncio.gather(*(call(i) for i in range(40))), timeout=10)
    asyncio.run(main_())
    assert len(granted) == 40
    granted.sort()
    for i, t in enumerate(granted):                       # any 60s window: <= 5 requests and <= 3 x 3000 tokens
        in_window = [g for g in granted if t - 60 < g <= t]
        assert len(in_window) <= 3, (i, in_window)


def test_maven_resolution_on_windows(monkeypatch, tmp_path):
    from agents.shared import java_env
    monkeypatch.setattr(java_env, "_IS_WINDOWS", True)
    monkeypatch.setattr(java_env.shutil, "which", lambda n: r"C:\maven\bin\mvn.cmd" if n == "mvn.cmd" else None)
    assert java_env.maven_executable(tmp_path) == r"C:\maven\bin\mvn.cmd"
    (tmp_path / "mvnw.cmd").write_text("@echo off")
    assert java_env.maven_executable(tmp_path) == str(tmp_path / "mvnw.cmd")
    monkeypatch.setattr(java_env.config, "MIGRATION_JAVA_HOME", r"C:\jdk-11")
    env = java_env.build_env()
    assert env["JAVA_HOME"] == r"C:\jdk-11" and env["PATH"].startswith(str(java_env.Path(r"C:\jdk-11") / "bin"))


def test_windows_style_plan_paths_resolve(tmp_path):
    (tmp_path / "top/src").mkdir(parents=True)
    (tmp_path / "top/src/A.java").write_text("class A {}")
    plan, fixed, missing = plan_paths.reconcile("| `top\\src\\A.java` | x | y |\n", str(tmp_path))
    assert missing == [] and ("top/src/A.java" in plan or fixed)
