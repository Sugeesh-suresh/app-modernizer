"""
End-to-end stress: every pipeline through the REAL ADK runners, real tools,
real plugins (masking, pacing), real state templating and the real workflow —
with only the model scripted. One scripted model plays every role, chosen by
the skill its instruction loads, and drives the tools the way an agent would:
lists files, reads one, edits it with replace_in_file, validates, signals.

Catches what stubbed tests cannot: a `{key}` an instruction reads that is not
in state, a tool signature an agent cannot call, a gate or state key that does
not flow from one step to the next, an exception in a callback or plugin.
"""
import asyncio
import json
import re
from pathlib import Path

import pytest
from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm, LlmResponse
from google.genai import types

import main
from agents import _ROOT_AGENTS, APP_NAME, USER_ID, config, session_service
from agents.java_8_to_11.agents import STAGE_TITLE as J11_STAGE
from agents.java_8_to_25.agents import incremental_stages
from agents.shared import java_env

RE_DOC = ("<!-- SECTION: ANALYSIS -->\nanalysis\n<!-- SECTION: BRD -->\n# BRD\nscope\n"
          "<!-- SECTION: TECHNICAL_SPECIFICATION -->\n# Spec\nfacts\n<!-- SECTION: TEST_INVENTORY -->\n"
          "# Tests\nnone\n<!-- SECTION: END -->\n")
# What an evidence specialist returns for the TIBCO fixture.
DISCOVERY_EVIDENCE = (
    "### Components\n- `OrderPublisher` publishes each confirmed order to the `orders.q` queue\n"
    "### Business Behaviour\n- Publishes each confirmed order.\n"
    "### Integrations & Configuration\n- Uses `com.tibco.tibjms.TibjmsConnectionFactory`\n"
    "### Tests\nNone found.\n"
)


def _writer_reply(skill: str, system: str) -> str:
    """What the writers might produce despite their instructions: the evidence's
    facts (cited) must survive, the migration talk must not."""
    ev = re.findall(r"\[(EV-[^\]]+)\]", system)
    cite = f" ({ev[0]})" if ev else ""
    labels = re.findall(r"^- (.+?) \(id `", system, re.M)
    if skill == "as-is-brd":
        return ("## Executive Summary\nPublishes each confirmed order. Orders are published to the `orders.q` queue "
                f"by `OrderPublisher`{cite}. This should be migrated to Google Cloud Pub/Sub.\n"
                "## Migration Considerations\n- EMS 8 is end of life\n## Business Journeys\n"
                + "".join(f"- A journey through {label}{cite}\n" for label in labels)
                + "## Recommendations\n- Add tests\n")
    return ("<!-- SECTION: TECHNICAL_SPECIFICATION -->\n## Architecture Overview\n"
            f"- Uses `com.tibco.tibjms.TibjmsConnectionFactory`{cite}\n- Java 8 → 25 upgrade needed for this client\n"
            "| Queue | Producer | Target |\n|---|---|---|\n| orders.q | OrderPublisher | Pub/Sub topic |\n"
            "## Per-Stack Detail\n" + "".join(f"### {label}\ncomponents{cite}\n" for label in labels)
            + "<!-- SECTION: TEST_INVENTORY -->\nNone found.\n## Recommendations\n- Add tests\n<!-- SECTION: END -->")


_SKILL = re.compile(r"Load and execute the `([a-z0-9-]+)` skill")
_COMMENT = {".java": "// migrated", ".sql": "-- migrated", ".xml": "<!-- migrated -->",
            ".properties": "# migrated", ".pkb": "-- migrated"}


def _six_sections(manifest_files: list[str], stages: list[str]) -> str:
    rows = "\n".join(f"| `{f}` | build | migrate |" for f in manifest_files)
    stage_text = "\n".join(
        f"## Stage {i}: {title}\n### Task {i}.1: Apply\n- Files: " + ", ".join(f"`{f}`" for f in manifest_files)
        + "\n- Change: migrate\n- Done when: builds\n" for i, title in enumerate(stages, 1))
    return (
        "# Migration Plan\n\n## Overview\nok\n\n## 1. What Changes\n### Skill Composition\n| a | b |\n"
        "### Dependency & Version Delta\n| c | d |\n### Sample Transformations\nnone\n### File Change Manifest\n"
        f"| File | Change Type | What Changes |\n|---|---|---|\n{rows}\n\n{stage_text}\n"
        "## 2. What Stays the Same\n### Explicit Non-Changes\nnone\n### Out of Scope\nnone\n"
        "## 3. Why This Is Safe\n### Risk Tier\nLow: small\n### Behaviour Inventory\nnone\n### Blast Radius\nnone\n"
        "## 4. How We'll Prove It Worked\n### Evidence Plan\nbuild\n### Coverage Gaps\nnone\n### Validation Contract\nbuild\n"
        "## 5. What Happens If It Fails\n### Rollback Plan\nrevert\n### Escalation Triggers\nnone\n"
        "## 6. What the Planner Doesn't Know\n### Confidence Register\nnone\n### Assumptions\nnone\n"
        "### Open Questions for the SME\nnone\n"
    )


class Scripted(BaseLlm):
    """Plays every agent. `calls` records (skill, request chars) per call."""
    calls: list = []
    plan_files: list = []
    stages: list = []
    rule_batches: list = []
    units: list = []
    writers: list = []

    def _reply(self, text=None, call=None):
        part = types.Part(text=text) if text is not None else types.Part(function_call=types.FunctionCall(
            name=call[0], args=call[1]))
        return LlmResponse(content=types.Content(role="model", parts=[part]),
                           usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100))

    async def generate_content_async(self, req, stream=False):
        system = str(req.config.system_instruction or "")
        skill = (_SKILL.search(system) or [None, "?"])[1]
        tools = set((req.tools_dict or {}).keys())
        responses = [p.function_response for c in req.contents for p in c.parts or [] if p.function_response]
        self.calls.append((skill, len(system)))
        assert "{" + "approved_versions" not in system, "unresolved template key"
        n = len(responses)
        last = json.dumps(responses[-1].response) if responses else ""

        if skill.endswith("-plan"):
            yield self._reply(_six_sections(self.plan_files, self.stages))
        elif skill in ("dependency-mapper",):
            yield self._reply("Inventory.\n```json\n{\"confirmed\": [], \"added\": [], \"rejected\": []}\n```")
        elif "running the `business-rules-extract` skill" in system:
            # Answer every candidate in the batch, citing each one's first line.
            found = re.findall(r"### (C\d{5}) .*?\nFile: `[^`]+` lines (\d+)-", system)
            self.rule_batches.append([cid for cid, _ in found])
            results = [{"candidate": cid, "rules": [{"statement": f"Rule found in candidate {cid} applies.", "type": "validation",
                                                     "lines": start, "basis": "explicit"}]} for cid, start in found]
            yield self._reply("```json\n" + json.dumps({"results": results}) + "\n```")
        elif skill == "stack-discovery-unit":
            listed = re.findall(r"- `([^`]+)`", system)
            self.units.append(listed)
            yield self._reply("## Unit\n### Components\n" + "\n".join(f"- `{f}`: component" for f in listed))
        elif "running the `as-is-brd` skill" in system:
            self.writers.append("po_brd")
            yield self._reply(_writer_reply("as-is-brd", system))
        elif "running the `current-state-architecture` skill" in system:
            self.writers.append("ea_spec")
            yield self._reply(_writer_reply("current-state-architecture", system))
        elif "Merge the evidence below" in system:
            yield self._reply("\n".join(re.findall(r"^- \[EV-[^\n]+", system, re.M)))
        elif skill in ("stack-discovery-re", "wildfly-re"):
            yield self._reply(DISCOVERY_EVIDENCE)
        elif skill == "jsp-re":
            yield self._reply("JSP facts: index.jsp uses JSTL.")
        elif skill.endswith("-re") or skill == "jsp-logic-classifier":
            yield self._reply(RE_DOC)
        elif skill.endswith("-re-module"):
            yield self._reply("## Unit findings\nnone")
        elif skill.endswith("-validate"):
            order = [t for t in ("run_java11_build", "validate_solr_config", "validate_sql_syntax",
                                 "validate_pubsub_mapping", "check_java11_invariants") if t in tools]
            if n < len(order):
                yield self._reply(call=(order[n], {}))
            elif n == len(order):
                yield self._reply(call=("signal_build_success", {}))
            else:
                ok = "ERROR" not in last
                yield self._reply(json.dumps({"passed": ok, "errors": [] if ok else [last[:200]], "summary": "s"}))
        elif skill.endswith("-fix"):
            yield self._reply("## Fix Result\n- Files fixed: 0")
        elif skill == "code-review":
            order = [t for t in ("audit_migration_changes", "compare_plan_to_actual_changes") if t in tools]
            yield self._reply(call=(order[n], {})) if n < len(order) else self._reply("## Code Review\nNo findings.")
        elif skill == "skill-curator":
            yield self._reply("## Skill Curator Summary\nNo changes made — nothing in this run surfaced a gap.")
        elif skill.endswith("-report"):
            yield self._reply("# Migration Report\nDone.")
        elif {"write_file", "replace_in_file", "read_file", "list_files"} <= tools:
            yield self._modify(skill, n, responses, last)
        else:
            yield self._reply("ok")

    def _modify(self, skill, n, responses, last):
        if skill.endswith("-generate"):
            target = "backend/pom.xml" if "spring-boot" in skill else "frontend/package.json"
            if n == 0:
                return self._reply(call=("write_file", {"path": target, "content": "<project/>\n" if target.endswith(
                    ".xml") else "{\"name\": \"app\"}\n"}))
            return self._reply(f"## Generate Result\n- {target}")
        if n == 0:
            return self._reply(call=("list_files", {"subdir": "."}))
        listing = str((responses[0].response or {}).get("result", ""))
        files = re.findall(r"([\w./\-]+\.(?:java|sql|pkb|xml|properties))", listing)
        files = [f for f in files if "webapp" not in f and "/test/" not in f] or files
        rank = {".java": 0, ".sql": 1, ".pkb": 1, ".xml": 2, ".properties": 3}
        target = sorted(files, key=lambda f: rank[Path(f).suffix])[0] if files else None
        if target is None:
            return self._reply("## Modify Result\n- Files changed: 0")
        if n == 1:
            return self._reply(call=("read_file", {"path": target}))
        if n == 2:
            text = (responses[1].response or {}).get("result", "")
            first = next((l.split("|", 1)[1] if "|" in l else l for l in text.splitlines()[1:] if l.strip()), "")
            first = re.sub(r"^\s*\d+\s*\|\s?", "", first)
            if not first.strip():
                return self._reply("## Modify Result\n- Files changed: 0")
            return self._reply(call=("replace_in_file", {"path": target, "old_text": first,
                                                         "new_text": first + "\n" + _COMMENT[Path(target).suffix]}))
        return self._reply(f"## Modify Result\n- Files changed: 1 — `{target}`\n- Files skipped (no change needed): "
                           "all other listed files — covered by this change")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def _fixture(pattern: str) -> dict[str, str]:
    from tests.test_migration_inventory import FIXTURES
    if pattern in FIXTURES:
        return dict(FIXTURES[pattern])
    if pattern == "java-8-to-11":
        return {"top/pom.xml": "<project><artifactId>p</artifactId><packaging>war</packaging><properties>"
                               "<maven.compiler.source>1.8</maven.compiler.source></properties></project>",
                "top/src/main/java/a/Codec.java": "package a;\nimport sun.misc.BASE64Encoder;\nclass Codec {}\n",
                "top/src/main/webapp/index.jsp": "<html/>",
                "top/src/main/webapp/WEB-INF/jboss-web.xml": "<jboss-web/>"}
    if pattern in ("jsp-to-react-bff", "stack-discovery"):
        return {"pom.xml": "<project><artifactId>w</artifactId><packaging>war</packaging><dependencies>"
                           "<dependency><groupId>com.tibco</groupId><artifactId>tibjms</artifactId></dependency>"
                           "</dependencies></project>",
                "src/main/webapp/index.jsp": "<%@ taglib prefix=\"c\" uri=\"http://java.sun.com/jsp/jstl/core\" %>"
                                             "<html><c:out value=\"x\"/></html>",
                "src/main/webapp/WEB-INF/jboss-web.xml": "<jboss-web/>",
                "src/main/java/a/Svc.java": "package a;\nimport javax.jms.Queue;\nclass Svc {}\n"}
    raise KeyError(pattern)


@pytest.fixture
def scripted(monkeypatch):
    model = Scripted(model="scripted")
    model.calls, model.plan_files, model.stages = [], [], []
    model.rule_batches, model.units, model.writers = [], [], []
    seen = set()

    def walk(agent):
        if id(agent) in seen:
            return
        seen.add(id(agent))
        if isinstance(agent, LlmAgent):
            monkeypatch.setattr(agent, "model", model)
        for sub in getattr(agent, "sub_agents", None) or []:
            walk(sub)
    for agent in _ROOT_AGENTS:
        walk(agent)
    # Builds are not run here (no Maven / npm needed); everything else is real.
    monkeypatch.setattr(java_env, "run_maven", lambda *a, **k: (0, "[INFO] BUILD SUCCESS"))
    return model


def _run(tmp_path, pattern, strategy="bigbang", springboot=False, companions=(), stacks=(), extra=None):
    ws, base = tmp_path / "ws", tmp_path / "base"
    files = {**_fixture(pattern), **(extra or {})}
    for root in (ws, base):
        _write(root, files)
    graph = json.dumps(main.dependency_graph.build_dependency_graph(str(ws), pattern))
    # Recommendations exactly as the upload builds them.
    if stacks:
        recs = main.stack_detector.detect_stacks(str(ws))
    elif companions:
        recs = main.companion_detector.detect_companions(str(ws), pattern)
    else:
        recs = []
    state = main._initial_state(pattern, str(ws), str(base), graph, strategy, False, springboot, json.dumps(recs))
    if companions or stacks:
        state["companion_patterns_json"] = json.dumps(list(companions or stacks))
    sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
    main._sse_queues[sid] = asyncio.Queue()
    for gates in (main._brd_gates, main._plan_gates, main._companion_gates):
        gates[sid] = asyncio.Event()
        gates[sid].set()
    asyncio.run(main._run_workflow(sid))
    events = []
    while not main._sse_queues[sid].empty():
        raw = main._sse_queues[sid].get_nowait()
        if raw:
            events += [json.loads(l[6:]) for l in raw.splitlines() if l.startswith("data: ")]
    return events, asyncio.run(main._get_state(sid))


SCENARIOS = [
    ("java-8-to-11", "bigbang", False, ["top/pom.xml", "top/src/main/java/a/Codec.java"], [J11_STAGE]),
    ("java-8-to-25", "bigbang", False, ["pom.xml"], []),
    ("java-8-to-25", "incremental", False, ["pom.xml"], [s.title for s in incremental_stages(False)]),
    ("java-8-to-25", "incremental", True, ["pom.xml"], [s.title for s in incremental_stages(True)]),
    ("solr-4-to-9", "bigbang", False, ["solr/collection1/conf/schema.xml"], []),
    ("oracle-19c-to-23ai", "bigbang", False, ["db/schema/orders.sql"], []),
    ("tibco-ems-to-pubsub", "bigbang", False, ["src/main/java/com/acme/OrderPublisher.java"], []),
    ("jsp-to-react-bff", "bigbang", False, ["src/main/webapp/index.jsp"], []),
]


@pytest.mark.parametrize("pattern, strategy, springboot, plan_files, stages", SCENARIOS,
                         ids=[f"{s[0]}-{s[1]}{'-boot' if s[2] else ''}" for s in SCENARIOS])
def test_every_pipeline_runs_end_to_end_through_the_real_runners(scripted, tmp_path, pattern, strategy,
                                                                 springboot, plan_files, stages):
    scripted.plan_files, scripted.stages = plan_files, stages
    events, state = _run(tmp_path, pattern, strategy, springboot)
    errors = [e for e in events if e["type"] == "error"]
    assert not errors, errors
    assert any(e["type"] == "workflow-complete" for e in events)
    assert any(e["type"] == "code-ready" for e in events)
    skills = {s for s, _ in scripted.calls}
    assert any(s.endswith("-plan") for s in skills)
    assert any(s.endswith("-validate") for s in skills), skills
    assert any(s.endswith("-report") for s in skills), skills
    assert "code-review" in skills and "skill-curator" in skills
    diff = next(e for e in events if e["type"] == "diff-ready")
    if pattern == "jsp-to-react-bff":
        assert {"backend/pom.xml", "frontend/package.json"} <= {f["path"] for f in diff["changed_files"]}
    else:
        assert diff["changed_files"], "the scripted modifier's edit should be in the diff"


def test_a_companion_bundle_runs_both_pipelines(scripted, tmp_path):
    scripted.plan_files = ["pom.xml"]
    extra = {"web/src/main/resources/db.properties": "url=jdbc:oracle:thin:@//db:1521/ORCL\n",
             "db/schema/orders.sql": "CREATE TABLE orders (notes LONG);\n"}
    events, state = _run(tmp_path, "java-8-to-25", companions=["oracle-19c-to-23ai"], extra=extra)
    assert json.loads(state["companion_patterns_json"]) == ["oracle-19c-to-23ai"]
    assert not [e for e in events if e["type"] == "error"]
    plans = [s for s, _ in scripted.calls if s.endswith("-plan")]
    assert plans == ["oracle-19c-to-23ai-plan", "java-8-to-25-plan"]
    assert any(e["type"] == "workflow-complete" for e in events)


def test_stack_discovery_runs_end_to_end(scripted, tmp_path):
    events, state = _run(tmp_path, "stack-discovery", stacks=["tibco-ems", "wildfly"])
    assert not [e for e in events if e["type"] == "error"], events
    assert any(e["type"] == "brd-ready" for e in events)
    skills = {s for s, _ in scripted.calls}
    assert {"dependency-mapper", "stack-discovery-re", "wildfly-re"} <= skills
    # The migrations' own RE skills are written towards a target; discovery never uses them.
    assert not [s for s in skills if s.endswith("-re") and s not in ("stack-discovery-re", "wildfly-re")]
    document = "\n".join(state[k] for k in ("brd", "technical_spec", "test_inventory"))
    evidence = Path(state["evidence_path"]).read_text()
    # The Product Owner's code wording stays out of the BRD; the writer's own output keeps it.
    assert "`orders.q` queue" in state["po_brd"] and "`" not in state["brd"] and "EV-" not in state["brd"]
    assert "TibjmsConnectionFactory" in document
    assert "Publishes each confirmed order." in document
    assert "### TIBCO EMS messaging" in state["technical_spec"] and "### WildFly / JBoss (app server)" in state["technical_spec"]
    assert sorted(scripted.writers) == ["ea_spec", "po_brd"]                 # each writer once, for both stacks
    assert "Every evidence and rule id cited by either document exists." in evidence
    assert "## Dependency Graph & Migration Groups" not in document
    for banned in ("migrat", "Pub/Sub", "Google Cloud", "upgrade", "end of life", "Recommendations",
                   "tibco-ems-to-pubsub", "→ 25", "Target"):
        assert banned.lower() not in document.lower(), banned
    brd = next(e for e in events if e["type"] == "brd-ready")["brd"]
    assert "migrat" not in brd.lower() and "pubsub" not in brd.lower()


def test_concurrent_runs_stay_isolated(scripted, tmp_path):
    """Several pipelines at once in one event loop: separate state, SSE queues
    and workspaces; the shared plugins (pacing, masking) under concurrency."""
    scripted.plan_files = ["pom.xml"]
    sids = []
    for i, pattern in enumerate(["java-8-to-25", "solr-4-to-9", "oracle-19c-to-23ai", "tibco-ems-to-pubsub"]):
        ws, base = tmp_path / f"ws{i}", tmp_path / f"base{i}"
        for root in (ws, base):
            _write(root, _fixture(pattern))
        state = main._initial_state(pattern, str(ws), str(base), "[]", "bigbang", False, False)
        sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
        main._sse_queues[sid] = asyncio.Queue()
        for gates in (main._brd_gates, main._plan_gates, main._companion_gates):
            gates[sid] = asyncio.Event()
            gates[sid].set()
        sids.append((sid, pattern))

    async def all_runs():
        await asyncio.gather(*(main._run_workflow(sid) for sid, _ in sids))
    asyncio.run(all_runs())
    for sid, pattern in sids:
        events = []
        while not main._sse_queues[sid].empty():
            raw = main._sse_queues[sid].get_nowait()
            if raw:
                events += [json.loads(l[6:]) for l in raw.splitlines() if l.startswith("data: ")]
        assert not [e for e in events if e["type"] == "error"], (pattern, events)
        assert any(e["type"] == "workflow-complete" for e in events), pattern
        state = asyncio.run(main._get_state(sid))
        assert state["pattern"] == pattern and state["plan"].startswith("# Migration Plan")
        assert Path(state["result_archive_path"]).is_file()                 # each run archived its own result


# ---------------------------------------------------------------------------
# Java 8 -> 11 with REAL Maven: preflight, build, tests, fence, approved versions
# ---------------------------------------------------------------------------
import os
import shutil

_JDK11 = os.getenv("TEST_JDK11_HOME", "/usr/lib/jvm/java-11-openjdk-amd64")
_JDK8 = os.getenv("TEST_JDK8_HOME", "/usr/lib/jvm/java-8-openjdk-amd64")

REAL_REPO = {
    "acme-master/pom.xml": """<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>
  <groupId>com.acme</groupId><artifactId>acme-parent</artifactId><version>1.0-SNAPSHOT</version><packaging>pom</packaging>
  <properties><maven.compiler.source>1.8</maven.compiler.source><maven.compiler.target>1.8</maven.compiler.target><project.build.sourceEncoding>UTF-8</project.build.sourceEncoding></properties>
  <modules><module>app</module></modules>
  <build><pluginManagement><plugins>
    <plugin><artifactId>maven-compiler-plugin</artifactId><version>3.8.1</version></plugin>
    <plugin><artifactId>maven-surefire-plugin</artifactId><version>2.22.2</version></plugin>
    <plugin><artifactId>maven-war-plugin</artifactId><version>3.4.0</version><configuration><failOnMissingWebXml>false</failOnMissingWebXml></configuration></plugin>
  </plugins></pluginManagement></build>
</project>""",
    "acme-master/app/pom.xml": """<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>
  <parent><groupId>com.acme</groupId><artifactId>acme-parent</artifactId><version>1.0-SNAPSHOT</version></parent>
  <artifactId>acme-app</artifactId><packaging>war</packaging>
  <dependencies>
    <dependency><groupId>junit</groupId><artifactId>junit</artifactId><version>4.12</version><scope>test</scope></dependency>
    <dependency><groupId>org.mockito</groupId><artifactId>mockito-core</artifactId><version>1.10.19</version><scope>test</scope></dependency>
  </dependencies>
</project>""",
    "acme-master/app/src/main/java/com/acme/Codec.java":
        "package com.acme;\nimport javax.xml.bind.DatatypeConverter;\n"
        "public class Codec { public String hex(byte[] b) { return DatatypeConverter.printHexBinary(b); } }\n",
    "acme-master/app/src/main/java/com/acme/Svc.java": "package com.acme;\npublic class Svc { public String name() { return \"svc\"; } }\n",
    "acme-master/app/src/test/java/com/acme/SvcTest.java":
        "package com.acme;\nimport org.junit.Test; import org.junit.runner.RunWith; import org.mockito.runners.MockitoJUnitRunner;\n"
        "import static org.junit.Assert.*; import static org.mockito.Mockito.*;\n@RunWith(MockitoJUnitRunner.class)\n"
        "public class SvcTest {\n  @Test public void mocks() { Svc s = mock(Svc.class); when(s.name()).thenReturn(\"x\"); assertEquals(\"x\", s.name()); }\n"
        "  @Test public void alreadyBroken() { assertEquals(1, 2); }\n}\n",
    "acme-master/app/src/main/webapp/index.jsp": "<html/>",
    "acme-master/app/src/main/webapp/WEB-INF/jboss-web.xml": "<jboss-web/>",
}
_EDITS = {
    "acme-master/pom.xml": ("<maven.compiler.source>1.8</maven.compiler.source><maven.compiler.target>1.8</maven.compiler.target>",
                            "<maven.compiler.release>11</maven.compiler.release>"),
    "acme-master/app/pom.xml": ("<dependencies>", "<dependencies>\n    <dependency><groupId>javax.xml.bind</groupId>"
                                "<artifactId>jaxb-api</artifactId><version>2.3.1</version><scope>provided</scope></dependency>"),
}


class RealJava11(Scripted):
    """The Java 11 modifier makes the real migration edits named in its task."""

    def _modify(self, skill, n, responses, last):
        system = self._system
        todo = [f for f in _EDITS if f"`{f}`" in system]
        if n < len(todo):
            old, new = _EDITS[todo[n]]
            return self._reply(call=("replace_in_file", {"path": todo[n], "old_text": old, "new_text": new}))
        return self._reply("## Modify Result\n- Files changed: " + ", ".join(f"`{f}`" for f in todo))

    async def generate_content_async(self, req, stream=False):
        self._system = str(req.config.system_instruction or "")
        async for r in super().generate_content_async(req, stream):
            yield r


@pytest.mark.skipif(not (shutil.which("mvn") and Path(_JDK11, "bin/java").exists() and Path(_JDK8, "bin/java").exists()
                         and os.getenv("RUN_MAVEN_IT")),
                    reason="needs Maven, JDK 11 + 8 (TEST_JDK11_HOME / TEST_JDK8_HOME) and RUN_MAVEN_IT=1")
def test_java11_end_to_end_with_real_maven(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PREFLIGHT", "on")
    monkeypatch.setattr(config, "MIGRATION_JAVA_HOME", _JDK11)
    monkeypatch.setattr(config, "BASELINE_JAVA_HOME", _JDK8)
    approved = tmp_path / "approved.txt"
    approved.write_text("javax.xml.bind:jaxb-api = 2.3.1\n")
    monkeypatch.setattr(config, "APPROVED_VERSIONS_FILE", str(approved))
    model = RealJava11(model="scripted")
    model.calls, model.stages = [], [J11_STAGE]
    model.plan_files = list(_EDITS)
    seen = set()

    def walk(agent):
        if id(agent) in seen:
            return
        seen.add(id(agent))
        if isinstance(agent, LlmAgent):
            monkeypatch.setattr(agent, "model", model)
        for sub in getattr(agent, "sub_agents", None) or []:
            walk(sub)
    for agent in _ROOT_AGENTS:
        walk(agent)

    ws, base = tmp_path / "ws", tmp_path / "base"
    for root in (ws, base):
        _write(root, REAL_REPO)
    state = main._initial_state("java-8-to-11", str(ws), str(base), "[]", "bigbang", False, False)
    sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
    main._sse_queues[sid] = asyncio.Queue()
    for gates in (main._brd_gates, main._plan_gates, main._companion_gates):
        gates[sid] = asyncio.Event()
        gates[sid].set()
    asyncio.run(main._run_workflow(sid))
    events = []
    while not main._sse_queues[sid].empty():
        raw = main._sse_queues[sid].get_nowait()
        if raw:
            events += [json.loads(l[6:]) for l in raw.splitlines() if l.startswith("data: ")]
    assert not [e for e in events if e["type"] == "error"], events
    state = asyncio.run(main._get_state(sid))

    pf = json.loads(state["preflight_json"])
    assert pf["toolchain"]["maven_java_major"] == 11
    assert any("javax.xml.bind does not exist" in e for e in pf["compile_errors"])         # what 11 breaks
    assert pf["baseline_failing_tests"] == ["com.acme.SvcTest#alreadyBroken"]              # pre-existing
    assert pf["approved_checked"] == 1 and pf["approved_unavailable"] == []
    assert "## Baseline Build on JDK 11" in state["technical_spec"]

    build = json.loads(state["build_result"])
    assert build["passed"] is True, build                       # real build + tests on 11, fence PASS, gate PASS
    assert state["java11_build_passed"] is True
    import zipfile
    with zipfile.ZipFile(state["result_archive_path"]) as z:
        parent = z.read("acme-master/pom.xml").decode()
        test = z.read("acme-master/app/src/test/java/com/acme/SvcTest.java").decode()
        jsp = z.read("acme-master/app/src/main/webapp/index.jsp").decode()
    assert "<maven.compiler.release>11</maven.compiler.release>" in parent
    assert "org.mockito.runners" in test          # Mockito stays 1.x (passed on 11), so no runner rewrite
    assert jsp == "<html/>"
    validations = [s for s, _ in model.calls if s.endswith("-validate")]
    assert len(validations) == 3                  # run_java11_build, check_java11_invariants, signal: one round


class FailThenPass(Scripted):
    """Validator fails round 1 (reports JSON), passes round 2 (signals)."""
    rounds: int = 0

    async def generate_content_async(self, req, stream=False):
        system = str(req.config.system_instruction or "")
        skill = (_SKILL.search(system) or [None, "?"])[1]
        responses = [p.function_response for c in req.contents for p in c.parts or [] if p.function_response]
        if skill.endswith("-validate") and not responses:
            self.rounds += 1
            if self.rounds == 1:
                self.calls.append((skill, 0))
                yield self._reply(json.dumps({"passed": False, "errors": ["schema.xml:2 — TrieIntField"],
                                              "summary": "round 1 fails"}))
                return
        async for r in super().generate_content_async(req, stream):
            yield r


def test_a_run_that_fails_then_passes_is_reported_as_passed(monkeypatch, tmp_path, scripted):
    model = FailThenPass(model="scripted")
    model.calls, model.plan_files, model.stages, model.rounds = [], ["solr/collection1/conf/schema.xml"], [], 0
    seen = set()

    def walk(agent):
        if id(agent) in seen:
            return
        seen.add(id(agent))
        if isinstance(agent, LlmAgent):
            monkeypatch.setattr(agent, "model", model)
        for sub in getattr(agent, "sub_agents", None) or []:
            walk(sub)
    for agent in _ROOT_AGENTS:
        walk(agent)
    events, state = _run(tmp_path, "solr-4-to-9")
    done = next(e for e in events if e["type"] == "validation-complete")
    assert model.rounds == 2
    assert done["passed"] is True and done["errors"] == [], done          # not round 1's stale failure
    assert json.loads(state["build_result_solr-4-to-9"] if "build_result_solr-4-to-9" in state
                      else state["build_result"])["passed"] is True


def test_stack_discovery_documents_each_stack_the_repository_contains(scripted, tmp_path, monkeypatch):
    """JSP + Backbone + Java: the stacks come from the repository (script
    includes, AMD imports, sources), each is documented by the discovery agent
    with its own checklist, and the fingerprint is part of the document."""
    extra = {
        "src/main/webapp/index.jsp": '<%@ page %>\n<script src="js/lib/backbone-min.js"></script>\n',
        "src/main/webapp/js/lib/backbone-min.js": "/* lib */",
        "src/main/webapp/js/app.js": "define(['backbone'], function (Backbone) { return Backbone.Router.extend({}); });",
        "src/main/java/a/OrderController.java": "package a;\nimport org.springframework.stereotype.Controller;\nclass O {}\n",
    }
    requests: list[str] = []
    real_run_step = main._run_step

    async def recording(session_id, step_key, pattern, message, sse_event_type):
        if step_key == "discover":
            requests.append(message)
        await real_run_step(session_id, step_key, pattern, message, sse_event_type)

    monkeypatch.setattr(main, "_run_step", recording)
    ws = tmp_path / "probe"
    _write(ws, {**_fixture("stack-discovery"), **extra})
    found = [s["pattern"] for s in main.stack_detector.detect_stacks(str(ws))]
    assert {"jsp", "backbone", "java"} <= set(found)

    events, state = _run(tmp_path, "stack-discovery", stacks=found, extra=extra)

    assert not [e for e in events if e["type"] == "error"], events
    documented = [re.search(r"\(id `([^`]+)`", m).group(1) for m in requests]
    assert documented == [p for p in found if p != "wildfly"]
    checklist = {re.search(r"\(id `([^`]+)`", m).group(1): re.search(r"`references/([\w.-]+)`", m).group(1)
                 for m in requests}
    assert (checklist["jsp"], checklist["backbone"], checklist["java"]) == ("jsp.md", "spa-frontend.md", "java.md")
    assert "src/main/webapp/js/app.js: imports `backbone`" in next(m for m in requests if "(id `backbone`" in m)
    brd, spec = state["brd"], state["technical_spec"]
    evidence = Path(state["evidence_path"]).read_text()
    assert "## Executive Summary" in brd
    for heading in ("## Detected Technology Stacks", "## Repository Fingerprint"):
        assert heading in evidence and heading not in brd, heading
    for label in ("JSP / Servlet web tier", "Backbone.js front end", "Java application"):
        assert f"A journey through {label}" in brd                          # the PO saw every stack
    assert spec.index("### JSP / Servlet web tier") < spec.index("### Backbone.js front end") \
        < spec.index("### Java application")                                 # the EA's per-stack detail



def test_large_repository_discovery_with_the_business_rules_ledger(scripted, tmp_path, monkeypatch):
    """Rules extraction and unit-by-unit documentation through the real agents
    and runners: every candidate is classified, every Java file is read by
    exactly one unit, and the document carries the catalog and the coverage."""
    monkeypatch.setattr(config, "RULES_EXTRACTION", "on")
    monkeypatch.setattr(config, "RULES_BATCH_MAX_CANDIDATES", 2)
    monkeypatch.setattr(config, "DISCOVERY_CHUNK_MIN_FILES", 3)
    monkeypatch.setattr(config, "DISCOVERY_UNIT_MAX_FILES", 2)
    java = {f"src/main/java/com/acme/m{i % 2}/Svc{i}.java":
            f"package com.acme.m{i % 2};\npublic class Svc{i} {{\n  int fee(int a) {{\n    if (a > {i}) return 1;\n"
            f"    return 0;\n  }}\n}}\n" for i in range(5)}
    events, state = _run(tmp_path, "stack-discovery", stacks=["java"], extra=java)

    assert not [e for e in events if e["type"] == "error"], events
    ledger = json.loads(Path(state["rules_ledger_path"]).read_text())
    classified = [e for e in ledger["candidates"].values() if e["status"] != "auto-technical"]
    assert classified and all(e["status"] == "rule" for e in classified)
    assert all(len(b) <= 2 for b in scripted.rule_batches)
    assert sorted(cid for b in scripted.rule_batches for cid in b) == sorted(e["id"] for e in classified)
    java_files = sorted(f for f in {**_fixture("stack-discovery"), **java} if f.endswith(".java"))
    assert sorted(f for u in scripted.units for f in u) == java_files          # each file read once
    assert all(len(u) <= 2 for u in scripted.units)
    brd, evidence = state["brd"], Path(state["evidence_path"]).read_text()
    assert brd.index("## Executive Summary") < brd.index("## Business Rules by Capability")
    assert "| Rule ID | Business rule | Use case | Negative scenario | Edge cases |" in brd
    assert re.search(r"\| BR-[A-Z0-9-]+-\d{3} \| Rule found in candidate C\d+ applies\. \|", brd)
    assert "## Business Rules Coverage" not in brd and "Source" not in brd and "evidence file" not in brd
    assert evidence.index("## Business Rules Catalog — Code Locations and Tests") \
        < evidence.index("## Business Rules Coverage") < evidence.index("## Evidence Check")
