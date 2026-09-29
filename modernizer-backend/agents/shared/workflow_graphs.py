"""
Graph-based pipeline construction on ADK 2.x's `google.adk.workflow`.

ADK 2.x deprecates `SequentialAgent` and `LoopAgent` ("Please use Workflow
instead"), replacing both with one primitive: a `Workflow` is a directed graph
of nodes joined by edges, where a node may emit a *route* that selects which of
its outgoing edges fire. A straight line of edges is what `SequentialAgent`
was; a cycle back to an earlier node is what `LoopAgent` was — except the exit
condition is now an explicit node in the graph instead of an `escalate` flag
smuggled out through an event action.

Every pattern's code phase is the same graph, so it is built once here rather
than five times:

    START -> generator(s) -> build_loop_start -> validator -> build_gate
                                                     ^            |
                            fixer <- fixer_brief <---|------------|  route="fix"
                              |                                   |
                              +-----------------------------------+
                                                                  |  route="pass"
             code_reviewer -> reporter -> skill_curator <---------+

`make_build_loop_graph` builds the validate/fix cycle on its own, for the
java-8-to-25 incremental strategy — main.py runs each stage's modifier once per
plan task and then the stage's loop once over the finished stage, so the two
halves have to be separately runnable (see main.py's
_run_java8_incremental_code_step).


Three things about this graph are worth knowing before changing it.

**Brief nodes.** In a `Workflow`, the input handed to a node is whatever its
predecessor emitted, and for an `LlmAgent` node that input is appended as the
turn's user message. Every agent here runs with `include_contents="none"` and
pulls everything it needs out of session state via `{...}` templating, so the
user turn is framing, not data — but under `SequentialAgent` every agent saw
the *same* framing (one user message for the whole pipeline), and under a graph
each would instead see the previous agent's entire output. The `_brief` nodes
restore control over that: each one replaces its predecessor's output with a
fixed sentence naming what the next agent is being asked to do. They emit no
model calls and cost nothing.

**The gate reads state, not `escalate`.** `LoopAgent` exited early when
`signal_build_success` set `tool_context.actions.escalate`. A graph has no
enclosing loop to escalate out of, so `build_gate` decides from two things it
can actually see in session state: the flag `signal_build_success` now records
there, and the validator's own JSON verdict under `result_key`. Reading the
verdict is the more reliable of the two — every validate skill is required to
end with that JSON object, whereas calling the tool is something the model may
simply forget to do. Unparseable or missing output counts as *not* passed, so
a broken verdict costs another fix pass rather than silently ending the loop.

**`BUILD_LOOP_MAX_ITERATIONS` now counts fix passes.** Under `LoopAgent` it
counted (validate, fix) pairs, which meant the last fix of an exhausted loop
was applied and never re-validated: the `build_result` the report was written
from described the code as it stood *before* that final fix. Here the cap is on
fix passes and a validation always follows one, so the same number of fix
attempts is spent and the verdict always describes the code actually on disk.
The cost is one extra validation run on a run that exhausts its budget.
"""
from __future__ import annotations

from collections.abc import Sequence

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.workflow import Workflow, node

from .. import config
from .callbacks import parse_json_object
from .workspace_tools import BUILD_SUCCESS_SIGNAL_KEY

# Routes emitted by `build_gate`. Plain strings rather than booleans so a graph
# printed for debugging reads as words.
_ROUTE_PASS = "pass"
_ROUTE_FIX = "fix"


def _fix_count_key(result_key: str) -> str:
    """Fix passes spent so far, namespaced by result key: all eight
    java-8-to-25 incremental stages share one ADK session, so a single key
    would let one stage spend another's budget."""
    return f"build_loop_fix_passes__{result_key}"


def validation_passed(raw: str | None) -> bool:
    """Whether *raw* — a validate agent's JSON verdict — positively reports a
    clean build.

    Deliberately pessimistic, and so NOT the same call as main.py's
    `_parse_validation_json`, which assumes success when it cannot parse. That
    one is deciding what to *report* about a finished run, where inventing a
    failure would be worse than saying nothing; this one is deciding whether to
    stop trying, where assuming success ends the loop on a result nobody can
    read.
    """
    if not raw or not raw.strip():
        return False
    parsed = parse_json_object(raw)
    return bool(parsed and parsed.get("passed") is True)


def _brief(text: str, *, name: str):
    """A node that replaces whatever its predecessor emitted with *text*.

    See the module docstring: this is what keeps each agent's user turn fixed
    and short instead of letting the previous agent's whole output become it.
    """

    async def emit_brief() -> str:
        return text

    return node(emit_brief, name=name)


def _loop_start(brief: str, *, name: str, result_key: str):
    """Entry node of a validate/fix cycle: zeroes the cycle's counters, then
    briefs the validator.

    The counters live in session state, which outlives a single run (all eight
    java-8-to-25 incremental stages share one ADK session), so a run that did
    not reset them would inherit the previous one's budget as already spent.
    """
    fix_key = _fix_count_key(result_key)

    async def start_loop(ctx: Context) -> str:
        ctx.state[fix_key] = 0
        ctx.state[BUILD_SUCCESS_SIGNAL_KEY] = False
        return brief

    return node(start_loop, name=name)


def _build_gate(*, name: str, result_key: str, max_fix_passes: int):
    """Routes `"pass"` out of the cycle, or `"fix"` back into it.

    Exits on any of: the validator called `signal_build_success`, its JSON
    verdict says `passed`, or the fix budget is spent.
    """
    fix_key = _fix_count_key(result_key)

    async def gate(ctx: Context) -> None:
        signalled = bool(ctx.state.get(BUILD_SUCCESS_SIGNAL_KEY))
        ctx.state[BUILD_SUCCESS_SIGNAL_KEY] = False  # one signal belongs to one validation
        fixes_done = int(ctx.state.get(fix_key) or 0)

        if signalled or validation_passed(ctx.state.get(result_key)) or fixes_done >= max_fix_passes:
            ctx.route = _ROUTE_PASS
            return

        ctx.state[fix_key] = fixes_done + 1
        ctx.route = _ROUTE_FIX

    return node(gate, name=name)


def _loop_nodes(
    *,
    validator: LlmAgent,
    fixer: LlmAgent,
    result_key: str,
    max_fix_passes: int | None,
    suffix: str,
    entry_brief: str,
    fix_brief: str,
):
    """The four nodes and three edges every validate/fix cycle is made of.

    Returns `(entry_node, gate_node, edges)`; the caller attaches whatever the
    `"pass"` route should reach, which is the only thing that differs between
    the standalone loop and the full pipeline.
    """
    if max_fix_passes is None:
        max_fix_passes = config.BUILD_LOOP_MAX_ITERATIONS

    entry = _loop_start(entry_brief, name=f"build_loop_start{suffix}", result_key=result_key)
    gate = _build_gate(name=f"build_gate{suffix}", result_key=result_key, max_fix_passes=max_fix_passes)
    to_fixer = _brief(fix_brief, name=f"fixer_brief{suffix}")

    edges = [
        (entry, validator, gate),
        (gate, {_ROUTE_FIX: to_fixer}),
        (to_fixer, fixer, validator),  # the cycle
    ]
    return entry, gate, edges


def _generator_chain(generators: Sequence[LlmAgent], briefs: Sequence[str], *, name: str) -> list:
    """The `START -> gen[0] -> brief -> gen[1] -> ...` head of a graph, without
    its final element — the caller appends whatever the last generator feeds."""
    if len(briefs) != max(len(generators) - 1, 0):
        raise ValueError(
            f"{name}: {len(generators)} generators need {max(len(generators) - 1, 0)} briefs "
            f"(one for each after the first), got {len(briefs)}."
        )
    chain: list = ["START"]
    if generators:
        chain.append(generators[0])
        for generator, brief_text in zip(generators[1:], briefs):
            chain += [_brief(brief_text, name=f"{generator.name}_brief"), generator]
    return chain


def make_build_loop_graph(
    *,
    name: str,
    description: str,
    validator: LlmAgent,
    fixer: LlmAgent,
    result_key: str = "build_result",
    max_fix_passes: int | None = None,
    suffix: str = "",
    entry_brief: str = "Build the workspace and report the result.",
    fix_brief: str = "Fix every error the build report lists, in the workspace, in place.",
    generators: Sequence[LlmAgent] = (),
    generator_briefs: Sequence[str] = (),
) -> Workflow:
    """The validate/fix cycle as a runnable graph of its own — the direct
    replacement for `LoopAgent(sub_agents=[validator, fixer])`.

    With *generators*, the same graph with a modifier pass in front of the
    cycle: that is one java-8-to-25 incremental stage end to end. main.py runs
    the two halves separately (a stage's modifier once per plan task, then its
    cycle once over the finished stage), so both the loop alone and the whole
    stage have to be buildable from here.
    """
    entry, gate, edges = _loop_nodes(
        validator=validator, fixer=fixer, result_key=result_key,
        max_fix_passes=max_fix_passes, suffix=suffix,
        entry_brief=entry_brief, fix_brief=fix_brief,
    )
    head = _generator_chain(generators, generator_briefs, name=name)
    head.append(entry)

    # Nothing follows the cycle in this graph, so the `"pass"` route reaches a
    # node that does nothing: a route with no edge would leave the graph with
    # no way to finish cleanly.
    done = _brief("", name=f"build_loop_done{suffix}")
    return Workflow(
        name=name,
        description=description,
        edges=[tuple(head), *edges, (gate, {_ROUTE_PASS: done})],
    )


def make_code_pipeline_graph(
    *,
    name: str,
    description: str,
    generators: Sequence[LlmAgent],
    validator: LlmAgent,
    fixer: LlmAgent,
    reviewer: LlmAgent,
    reporter: LlmAgent,
    curator: LlmAgent,
    result_key: str = "build_result",
    max_fix_passes: int | None = None,
    generator_briefs: Sequence[str] = (),
    entry_brief: str = "Build the workspace and report the result.",
    fix_brief: str = "Fix every error the build report lists, in the workspace, in place.",
) -> Workflow:
    """One pattern's whole code phase as a single flat graph — the direct
    replacement for `SequentialAgent(generators..., build_loop, reviewer,
    reporter, curator)`.

    *generators* is the one modifier every pattern has, except jsp-to-react-bff,
    which writes two separate target trees and so has two. *generator_briefs*
    supplies the user turn for every generator after the first; the first one
    keeps the real message the caller sent, exactly as it did when the pipeline
    was a `SequentialAgent`.
    """
    if not generators:
        raise ValueError("A code pipeline needs at least one generator agent.")

    entry, gate, loop_edges = _loop_nodes(
        validator=validator, fixer=fixer, result_key=result_key,
        max_fix_passes=max_fix_passes, suffix="",
        entry_brief=entry_brief, fix_brief=fix_brief,
    )

    # START -> generator[0] -> brief -> generator[1] -> ... -> loop entry
    head = _generator_chain(generators, generator_briefs, name=name)
    head.append(entry)

    tail = (
        _brief(
            "Independently review the migrated workspace against the confirmed plan.",
            name=f"{reviewer.name}_brief",
        ),
        reviewer,
        _brief(
            "Produce the final migration report for this run.",
            name=f"{reporter.name}_brief",
        ),
        reporter,
        _brief(
            "Curate this pattern's skill library from the evidence this run produced.",
            name=f"{curator.name}_brief",
        ),
        curator,
    )

    return Workflow(
        name=name,
        description=description,
        edges=[tuple(head), *loop_edges, (gate, {_ROUTE_PASS: tail[0]}), tail],
    )


def make_sequential_graph(
    *,
    name: str,
    description: str,
    agents: Sequence[LlmAgent],
    briefs: Sequence[str] = (),
) -> Workflow:
    """A straight line of agents — the direct replacement for
    `SequentialAgent`, for the one pipeline that is not a code phase
    (jsp-to-react-bff's reverse-engineering pair).

    *briefs* supplies the user turn for every agent after the first; the first
    keeps the real message the caller sent. See the module docstring for why
    the briefs are here at all.
    """
    if not agents:
        raise ValueError("A sequential graph needs at least one agent.")
    chain = _generator_chain(agents, briefs, name=name)
    return Workflow(name=name, description=description, edges=[tuple(chain)])
