"""
Tests for the graph pipelines that replaced SequentialAgent/LoopAgent.

Two halves:

  * The *shape* tests read each pattern's pipeline as a graph — are the nodes
    there, is the fixer actually wired back to the validator, does the gate
    have exactly one edge per route. These are cheap and catch a miswired edge
    at import time, which is where a graph fails.

  * The *behaviour* tests run a real `Workflow` end to end with function nodes
    standing in for the validator and fixer, so the gate, the cycle and the fix
    budget are exercised by ADK's own scheduler rather than by calling the
    gate's closure directly. `_loop_nodes` is annotated for LlmAgents because
    that is what every real caller passes, but it only ever treats them as
    graph nodes — which is why the substitution works.
"""
import asyncio

import pytest

from google.adk.agents.context import Context
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow, node
from google.genai import types

from agents.shared import workflow_graphs as wg
from agents.shared.workspace_tools import BUILD_SUCCESS_SIGNAL_KEY


# ---------------------------------------------------------------------------
# validation_passed — deliberately the pessimistic half of the pair
# ---------------------------------------------------------------------------

class TestValidationPassed:
    @pytest.mark.parametrize("raw", [
        '{"passed": true, "errors": [], "summary": "ok"}',
        '```json\n{"passed": true, "errors": []}\n```',
        'Here is the result: {"passed": true} — done.',
    ])
    def test_recognises_a_clean_verdict(self, raw):
        assert wg.validation_passed(raw) is True

    @pytest.mark.parametrize("raw", [
        None, "", "   ",
        '{"passed": false, "errors": ["Foo.java:3 — nope"]}',
        "the build failed",           # unparseable
        '{"summary": "no verdict"}',  # parseable, but says nothing
        '{"passed": "true"}',         # a string is not a verdict
    ])
    def test_anything_else_is_not_a_pass(self, raw):
        assert wg.validation_passed(raw) is False

    def test_disagrees_with_mains_reporting_parser_on_garbage(self):
        """The two defaults are opposite on purpose — see both docstrings."""
        import main
        assert main._parse_validation_json("garbage")["passed"] is True
        assert wg.validation_passed("garbage") is False


# ---------------------------------------------------------------------------
# Graph shape
# ---------------------------------------------------------------------------

def _edge_map(graph_workflow: Workflow) -> dict[tuple[str, str], object]:
    return {
        (e.from_node.name, e.to_node.name): e.route
        for e in graph_workflow.graph.edges
    }


def _all_pipelines():
    from agents.java_8_to_25.agents import code_pipeline_bigbang, STAGE_BUILD_LOOPS, STAGE_PIPELINES
    from agents.jsp_to_react_bff.agents import code_pipeline as jsp_code
    from agents.oracle_19c_to_23ai.agents import code_pipeline as oracle_code
    from agents.solr_4_to_9.agents import code_pipeline as solr_code
    from agents.tibco_ems_to_pubsub.agents import code_pipeline as tibco_code
    return {
        "java-bigbang": code_pipeline_bigbang,
        "solr": solr_code,
        "oracle": oracle_code,
        "tibco": tibco_code,
        "jsp": jsp_code,
        **{f"java-stage{i + 1}-loop": w for i, w in enumerate(STAGE_BUILD_LOOPS)},
        **{f"java-stage{i + 1}": w for i, w in enumerate(STAGE_PIPELINES)},
    }


class TestPipelineShape:
    def test_every_pipeline_is_a_graph_workflow(self):
        for label, pipeline in _all_pipelines().items():
            assert isinstance(pipeline, Workflow), label
            assert pipeline.graph is not None, label

    def test_no_pattern_still_uses_the_deprecated_composites(self):
        """ADK 2.x removes these; an import that sneaks one back in fails here."""
        from google.adk.agents import LoopAgent, SequentialAgent
        for label, pipeline in _all_pipelines().items():
            for graph_node in pipeline.graph.nodes:
                assert not isinstance(graph_node, (LoopAgent, SequentialAgent)), f"{label}/{graph_node.name}"

    def test_every_cycle_closes_back_onto_its_validator(self):
        """The fixer must re-enter the validator, or a fix is never verified."""
        for label, pipeline in _all_pipelines().items():
            names = [n.name for n in pipeline.graph.nodes]
            validator = next(n for n in names if n.startswith("validator_"))
            fixer = next(n for n in names if n.startswith("fixer_") and not n.endswith("_brief")
                         and "brief" not in n)
            assert (fixer, validator) in _edge_map(pipeline), label

    def test_the_gate_routes_both_ways(self):
        for label, pipeline in _all_pipelines().items():
            gate = next(n.name for n in pipeline.graph.nodes if n.name.startswith("build_gate"))
            routes = {route for (src, _), route in _edge_map(pipeline).items() if src == gate}
            assert routes == {wg._ROUTE_PASS, wg._ROUTE_FIX}, f"{label}: {routes}"

    def test_the_code_phases_end_on_the_curator(self):
        """Reviewer -> reporter -> curator still runs only on the `pass` route."""
        for label in ("java-bigbang", "solr", "oracle", "tibco", "jsp"):
            pipeline = _all_pipelines()[label]
            edges = _edge_map(pipeline)
            assert ("reporter_agent", "skill_curator_agent_brief") in edges, label
            assert ("skill_curator_agent_brief", "skill_curator_agent") in edges, label
            # ...and is reached from the gate, not from the fixer.
            gate = next(n.name for n in pipeline.graph.nodes if n.name.startswith("build_gate"))
            assert edges.get((gate, "code_reviewer_agent_brief")) == wg._ROUTE_PASS, label

    def test_jsp_generates_both_trees_before_the_cycle(self):
        edges = _edge_map(_all_pipelines()["jsp"])
        assert ("backend_generator_agent", "frontend_generator_agent_brief") in edges
        assert ("frontend_generator_agent", "build_loop_start") in edges

    def test_each_java_stage_gets_its_own_node_names(self):
        loops = _all_pipelines()
        stage1 = {n.name for n in loops["java-stage1-loop"].graph.nodes}
        stage2 = {n.name for n in loops["java-stage2-loop"].graph.nodes}
        assert stage1.isdisjoint(stage2 - {"__START__"})

    def test_a_stage_pipeline_adds_its_modifier_in_front_of_its_loop(self):
        from agents.java_8_to_25.agents import STAGE_BUILD_LOOPS, STAGE_MODIFIERS, STAGE_PIPELINES
        for modifier, loop, pipeline in zip(STAGE_MODIFIERS, STAGE_BUILD_LOOPS, STAGE_PIPELINES):
            pipeline_names = {n.name for n in pipeline.graph.nodes}
            loop_names = {n.name for n in loop.graph.nodes}
            assert loop_names - {"__START__"} <= pipeline_names
            assert modifier.name in pipeline_names
            assert modifier.name not in loop_names


class TestBuilderGuards:
    def test_a_missing_generator_brief_is_rejected(self):
        with pytest.raises(ValueError, match="briefs"):
            wg.make_sequential_graph(
                name="two_agents", description="", agents=[node(_noop, name="a"), node(_noop, name="b")],
            )

    def test_a_pipeline_needs_a_generator(self):
        with pytest.raises(ValueError, match="at least one generator"):
            wg.make_code_pipeline_graph(
                name="empty", description="", generators=[],
                validator=node(_noop, name="v"), fixer=node(_noop, name="f"),
                reviewer=node(_noop, name="rv"), reporter=node(_noop, name="rp"),
                curator=node(_noop, name="c"),
            )


async def _noop() -> str:
    return ""


# ---------------------------------------------------------------------------
# Behaviour: run the cycle for real
# ---------------------------------------------------------------------------

RESULT_KEY = "build_result"
PASS_JSON = '{"passed": true, "errors": [], "summary": "clean"}'
FAIL_JSON = '{"passed": false, "errors": ["Foo.java:1 — boom"], "summary": "boom"}'


def _loop_under_test(trace: list, *, verdicts, max_fix_passes=3, signal_on_pass=False):
    """A build loop whose validator returns *verdicts* in order (the last one
    repeating once exhausted), recording every visit in *trace*."""

    async def validator(ctx: Context) -> str:
        visit = len([t for t in trace if t.startswith("validate")])
        verdict = verdicts[min(visit, len(verdicts) - 1)]
        trace.append(f"validate#{visit + 1}")
        ctx.state[RESULT_KEY] = verdict
        if signal_on_pass and verdict == PASS_JSON:
            # What signal_build_success does, minus the ToolContext.
            ctx.state[BUILD_SUCCESS_SIGNAL_KEY] = True
        return verdict

    async def fixer(ctx: Context) -> str:
        trace.append("fix")
        return "fixed"

    return wg.make_build_loop_graph(
        name="loop_under_test",
        description="",
        validator=node(validator, name="validator_agent"),
        fixer=node(fixer, name="fixer_agent"),
        result_key=RESULT_KEY,
        max_fix_passes=max_fix_passes,
    )


def _run(workflow: Workflow, initial_state: dict | None = None) -> dict:
    """Run *workflow* to completion and hand back the session state it left.

    Sync on purpose: this suite has no async plugin, and one asyncio.run per
    test is cheaper than a dependency.
    """
    return asyncio.run(_run_async(workflow, initial_state))


async def _run_async(workflow: Workflow, initial_state: dict | None = None) -> dict:
    svc = InMemorySessionService()
    await svc.create_session(app_name="t", user_id="u", session_id="s", state=initial_state or {})
    runner = Runner(app_name="t", agent=workflow, session_service=svc)
    async for _ in runner.run_async(
        session_id="s", user_id="u",
        new_message=types.Content(role="user", parts=[types.Part(text="go")]),
    ):
        pass
    session = await svc.get_session(app_name="t", user_id="u", session_id="s")
    return dict(session.state)


class TestBuildLoopBehaviour:
    def test_a_clean_first_build_never_reaches_the_fixer(self):
        trace: list = []
        _run(_loop_under_test(trace, verdicts=[PASS_JSON]))
        assert trace == ["validate#1"]

    def test_signal_build_success_alone_ends_the_cycle(self):
        """Even with a verdict the gate cannot read, the tool's signal exits."""
        trace: list = []
        _run(_loop_under_test(trace, verdicts=["BUILD OK (not JSON)"], signal_on_pass=False,
                                    max_fix_passes=2))
        assert trace == ["validate#1", "fix", "validate#2", "fix", "validate#3"], trace

        trace = []

        async def validator(ctx: Context) -> str:
            trace.append("validate")
            ctx.state[RESULT_KEY] = "BUILD OK (not JSON)"
            ctx.state[BUILD_SUCCESS_SIGNAL_KEY] = True
            return "ok"

        async def fixer(ctx: Context) -> str:
            trace.append("fix")
            return "fixed"

        _run(wg.make_build_loop_graph(
            name="signal_loop", description="",
            validator=node(validator, name="validator_agent"),
            fixer=node(fixer, name="fixer_agent"),
            result_key=RESULT_KEY, max_fix_passes=3,
        ))
        assert trace == ["validate"]

    def test_it_fixes_until_the_build_comes_back_clean(self):
        trace: list = []
        _run(_loop_under_test(trace, verdicts=[FAIL_JSON, FAIL_JSON, PASS_JSON]))
        assert trace == ["validate#1", "fix", "validate#2", "fix", "validate#3"]

    def test_the_fix_budget_is_a_ceiling_and_the_last_fix_is_verified(self):
        """N fixes, N+1 validations: the verdict always describes the code on
        disk, which is the one thing LoopAgent's pair counting could not do."""
        trace: list = []
        state = _run(_loop_under_test(trace, verdicts=[FAIL_JSON], max_fix_passes=3))
        assert trace.count("fix") == 3
        assert len([t for t in trace if t.startswith("validate")]) == 4
        assert trace[-1].startswith("validate")
        assert state[RESULT_KEY] == FAIL_JSON

    def test_a_previous_runs_spent_budget_is_not_inherited(self):
        """All eight java stages share one ADK session, so the entry node has
        to zero the counters — otherwise stage 2 starts with stage 1's spent."""
        trace: list = []
        stale = {
            wg._fix_count_key(RESULT_KEY): 3,
            BUILD_SUCCESS_SIGNAL_KEY: True,
        }
        _run(_loop_under_test(trace, verdicts=[FAIL_JSON, PASS_JSON]), initial_state=stale)
        assert trace == ["validate#1", "fix", "validate#2"]

    def test_one_stages_budget_does_not_touch_another_stages(self):
        from agents.java_8_to_25.agents import INCREMENTAL_STAGES
        keys = {wg._fix_count_key(f"build_result_stage{s.idx}") for s in INCREMENTAL_STAGES}
        assert len(keys) == len(INCREMENTAL_STAGES)


class TestBriefNodes:
    def test_a_brief_replaces_the_upstream_output(self):
        """Without this, each agent's user turn would be the previous agent's
        entire output instead of the framing it had under SequentialAgent."""
        seen: list = []

        async def upstream() -> str:
            return "UPSTREAM-OUTPUT"

        async def downstream(ctx: Context, node_input) -> str:
            seen.append(node_input)
            return "done"

        graph = wg.make_sequential_graph(
            name="brief_probe", description="",
            agents=[node(upstream, name="upstream"), node(downstream, name="downstream")],
            briefs=["THE BRIEF"],
        )
        _run(graph)
        assert seen == ["THE BRIEF"]
