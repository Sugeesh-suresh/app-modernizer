"""
Chunked reverse engineering for java-8-to-11 (large repositories).

A single reverse-engineering run resends every file it has read on every model
call, so request size grows with the repository until the token quota (429) or
the context window runs out. The repository is instead analysed unit by unit,
each unit in a fresh run, and the findings are combined in bounded requests.
"""
import asyncio
import json
import re
from pathlib import Path

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

import main
from agents import APP_NAME, USER_ID, config, session_service
from agents.java_8_to_11 import agents as j11
from agents.shared import re_units

P = "java-8-to-11"
RE_OUTPUT = (
    "<!-- SECTION: ANALYSIS -->\na\n<!-- SECTION: BRD -->\nb\n<!-- SECTION: TECHNICAL_SPECIFICATION -->\nt\n"
    "<!-- SECTION: TEST_INVENTORY -->\nx\n<!-- SECTION: END -->\n"
)


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _covering(units, rel):
    """Units whose scope includes *rel* — must be exactly one per file."""
    modules = sorted({u.module for u in units})
    owner = re_units._owner(rel, modules)
    hits = []
    for unit in units:
        if unit.module != owner:
            continue
        for s in unit.scope:
            whole_module = unit.parts == 1 and s == (f"{owner}/" if owner else "./")
            if whole_module or (s.endswith("/") and rel.startswith(s)) or s == rel:
                hits.append(unit.id)
                break
    return hits


# ---------------------------------------------------------------------------
# Unit planning
# ---------------------------------------------------------------------------

class TestPlanUnits:
    def test_one_unit_per_module_and_nested_modules_are_separate(self, tmp_path):
        _write(tmp_path, {
            "pom.xml": "<project/>", "README.md": "x",
            "core/pom.xml": "<project/>", "core/src/main/java/A.java": "class A {}",
            "web/pom.xml": "<project/>", "web/src/main/webapp/index.jsp": "<p/>",
            "web/api/pom.xml": "<project/>", "web/api/src/main/java/B.java": "class B {}",
            "core/target/classes/A.class": "x",  # build output: excluded
        })
        units = re_units.plan_units(str(tmp_path), max_files=100)
        assert [(u.module, u.files) for u in units] == [("", 2), ("core", 2), ("web", 2), ("web/api", 2)]
        assert "nested modules are separate units" in units[2].describe()

    def test_an_oversized_module_is_split_and_every_file_is_covered_exactly_once(self, tmp_path):
        files = {"pom.xml": "<project/>"}
        for pkg in ("orders", "billing", "admin"):
            for i in range(150):
                files[f"src/main/java/com/acme/{pkg}/C{i}.java"] = "class C {}"
        for i in range(30):
            files[f"src/main/webapp/p{i}.jsp"] = "<p/>"
        _write(tmp_path, files)

        units = re_units.plan_units(str(tmp_path), max_files=200)

        assert len(units) > 1 and all(u.files <= 200 for u in units)
        assert sum(u.files for u in units) == len(files)
        for rel in files:
            assert len(_covering(units, rel)) == 1, rel
        assert units[0].label.endswith(f"(part 1/{len(units)})")
        assert "Covers ONLY these paths" in units[0].describe()

    def test_a_small_repository_is_one_unit(self, tmp_path):
        _write(tmp_path, {"pom.xml": "<project/>", "src/main/java/A.java": "class A {}"})
        units = re_units.plan_units(str(tmp_path), max_files=300)
        assert len(units) == 1 and units[0].files == 2

    def test_planning_is_deterministic(self, tmp_path):
        _write(tmp_path, {f"m{i}/pom.xml": "<project/>" for i in range(5)})
        first = [u.describe() for u in re_units.plan_units(str(tmp_path), 10)]
        assert first == [u.describe() for u in re_units.plan_units(str(tmp_path), 10)]


# ---------------------------------------------------------------------------
# Orchestration, with the model calls stubbed
# ---------------------------------------------------------------------------

def _session(workspace: Path) -> str:
    state = main._initial_state(P, str(workspace), str(workspace) + "-base", "[]", "bigbang", False, False)
    sid = asyncio.run(session_service.create_session(app_name=APP_NAME, user_id=USER_ID, state=state)).id
    main._sse_queues[sid] = asyncio.Queue()
    return sid


class _Steps:
    def __init__(self, monkeypatch, findings_chars: int = 50, fail_units: set[str] = frozenset()):
        self.calls: list[tuple[str, str]] = []  # (step, what the step saw)

        async def fake(session_id, step_key, pattern, message, sse_event_type):
            state = await main._get_state(session_id)
            if step_key == "re_module":
                unit_id = re.search(r"Unit (\d+):", state["re_scope"]).group(1)
                self.calls.append((step_key, state["re_scope"]))
                if unit_id in fail_units:
                    raise RuntimeError(f"unit {unit_id} blew up")
                await main._update_state(session_id, {"module_findings": f"## Unit {unit_id}\n" + "x" * findings_chars})
            elif step_key == "re_merge":
                self.calls.append((step_key, state["re_findings"]))
                await main._update_state(session_id, {"merged_findings": "## Units merged\n" + "m" * 20})
            elif step_key == "re_synthesize":
                self.calls.append((step_key, state["re_findings"]))
                await main._update_state(session_id, {"analysis": RE_OUTPUT})
            else:
                self.calls.append((step_key, ""))
                await main._update_state(session_id, {"analysis": RE_OUTPUT})

        monkeypatch.setattr(main, "_run_step", fake)

    def steps(self):
        return [s for s, _ in self.calls]


@pytest.fixture
def three_modules(tmp_path):
    _write(tmp_path, {f"m{i}/pom.xml": "<project/>" for i in range(3)})
    return tmp_path


def test_one_run_per_unit_then_one_combining_run(monkeypatch, three_modules):
    steps = _Steps(monkeypatch)
    sid = _session(three_modules)
    asyncio.run(main._run_java11_re(sid, "go"))

    assert steps.steps() == ["re_module"] * 3 + ["re_synthesize"]
    assert [re.search(r"Unit \d+: (\S+)", seen).group(1) for _, seen in steps.calls[:3]] == ["m0", "m1", "m2"]
    combined = steps.calls[-1][1]
    assert all(f"## Unit {i}" in combined for i in (1, 2, 3))
    state = asyncio.run(main._get_state(sid))
    assert state["analysis"] == RE_OUTPUT and len(json.loads(state["re_findings_json"])) == 3


def test_findings_too_large_for_one_request_are_merged_in_batches_first(monkeypatch, three_modules):
    monkeypatch.setattr(config, "RE_SYNTHESIS_MAX_CHARS", 250)
    steps = _Steps(monkeypatch, findings_chars=100)
    asyncio.run(main._run_java11_re(_session(three_modules), "go"))

    assert "re_merge" in steps.steps() and steps.steps()[-1] == "re_synthesize"
    assert all(len(seen) <= 250 for step, seen in steps.calls if step in ("re_merge", "re_synthesize"))


def test_oversized_findings_are_cut_and_the_cut_is_stated(monkeypatch, three_modules):
    monkeypatch.setattr(config, "RE_FINDINGS_MAX_CHARS", 30)
    steps = _Steps(monkeypatch, findings_chars=500)
    asyncio.run(main._run_java11_re(_session(three_modules), "go"))
    assert "were cut at 30 characters" in steps.calls[-1][1]


def test_a_failed_unit_is_recorded_and_the_rest_still_run(monkeypatch, three_modules):
    steps = _Steps(monkeypatch, fail_units={"2"})
    asyncio.run(main._run_java11_re(_session(three_modules), "go"))
    combined = steps.calls[-1][1]
    assert steps.steps() == ["re_module"] * 3 + ["re_synthesize"]
    assert "Not analysed** — unit 2 blew up" in combined and "## Unit 3" in combined


def test_every_unit_failing_fails_the_step(monkeypatch, three_modules):
    _Steps(monkeypatch, fail_units={"1", "2", "3"})
    with pytest.raises(RuntimeError, match="failed for every unit"):
        asyncio.run(main._run_java11_re(_session(three_modules), "go"))


def test_refine_rewrites_from_stored_findings_without_reanalysing(monkeypatch, three_modules):
    steps = _Steps(monkeypatch)
    sid = _session(three_modules)
    asyncio.run(main._run_java11_re(sid, "go"))
    steps.calls.clear()
    asyncio.run(main._run_java11_re(sid, "Revise: reviewer feedback", refine=True))
    assert steps.steps() == ["re_synthesize"]


def test_unit_size_zero_restores_the_single_pass(monkeypatch, three_modules):
    monkeypatch.setattr(config, "RE_UNIT_MAX_FILES", 0)
    steps = _Steps(monkeypatch)
    asyncio.run(main._run_java11_re(_session(three_modules), "go"))
    assert steps.steps() == ["re"]


# ---------------------------------------------------------------------------
# The point of it: request size is bounded by the unit, not the repository
# ---------------------------------------------------------------------------

class _Reader(BaseLlm):
    """Lists its unit, reads every file in it, then writes findings. Records
    the size of every request it receives."""
    sizes: list = []

    async def generate_content_async(self, req, stream=False):
        self.sizes.append(sum(
            len(str(p.function_response.response)) if p.function_response else len(p.text or "")
            for c in req.contents for p in (c.parts or [])
        ))
        system = str(req.config.system_instruction or "")
        if "Module Findings below are its results" in system:          # the combining step
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=RE_OUTPUT)]))
            return
        responses = [p.function_response for c in req.contents for p in (c.parts or []) if p.function_response]
        if not responses:
            subdir = re.search(r"Unit \d+: (\S+)", system).group(1)
            call = types.FunctionCall(name="list_files", args={"subdir": subdir})
        else:
            listed = (responses[0].response or {}).get("result", "")
            paths = [line for line in listed.splitlines() if line.endswith(".java")]
            done = len(responses) - 1
            if done < len(paths):
                call = types.FunctionCall(name="read_file", args={"path": paths[done]})
            else:
                yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=f"## Unit findings: read {done} files")]))
                return
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))


def test_the_largest_request_is_bounded_by_the_unit_not_the_repository(monkeypatch, tmp_path):
    # Chunking alone: masking old reads (shared/llm_traffic.py) would shrink it further.
    monkeypatch.setattr(main.config, "CONTEXT_PROTECT_TOKENS", 0)
    body = "\n".join(f"// line {j} of a typical source file with some code" for j in range(300))
    files = {}
    for m in range(4):
        files[f"m{m}/pom.xml"] = "<project/>"
        for i in range(10):
            files[f"m{m}/src/main/java/C{m}_{i}.java"] = body
    _write(tmp_path, files)

    model = _Reader(model="scripted")
    for agent in (j11.module_re_agent, j11.re_synthesis_agent):
        monkeypatch.setattr(agent, "model", model)
    asyncio.run(main._run_java11_re(_session(tmp_path), "go"))

    per_file = len(body)
    largest = max(model.sizes)
    # One unit reads 10 of the 40 files: its last request carries ~10 files, never ~40.
    assert 9 * per_file < largest < 12 * per_file, (largest, per_file)
    assert sum(1 for s in model.sizes if s > per_file) >= 30   # all 40 files were really read, unit by unit
