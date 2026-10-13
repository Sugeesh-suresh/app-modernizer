"""
The migration pipeline as a state machine, for Gemini CLI.

main.py drives each pattern as ADK runners: analyse -> (analysis review) ->
plan -> plan review -> modify -> build/fix loop -> review -> report ->
scope-fence restore -> diff. Here the same sequence is a cursor in `.modernizer/run.json`:

- `next_step(run)` runs every deterministic step it reaches (inventory,
  preflight, plan checks, mechanical rewrites, the final diff) and stops at the
  first step that needs a model or a person. For a model it returns the
  subagent to call and its brief — the skill to activate and the inputs, the
  same instructions the ADK agent was given; for a person, what to review and
  which command answers it.
- `complete_step(run, step_id)` reads what the subagent saved (`save_output`)
  and does what the ADK callbacks and main.py did with an agent's output:
  split the analysis into its sections, check and reconcile the plan, send a
  task back once for listed files it left unchanged, route a failed build to
  the fixer, publish verified lessons to the skills.
- `confirm(run, gate, ...)` and `refine(run, gate, feedback)` are the human
  gates (companion/stack selection, analysis review, plan approval).

Stack discovery has its own steps (cli/discovery.py) behind the same three calls.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from agents import config
from agents.java_8_to_11 import inventory as java11_inventory
from agents.java_8_to_11 import mechanical as java11_mechanical
from agents.java_8_to_11.fence_rules import FENCE_RULES, STAGE_TITLE as JAVA11_STAGE_TITLE
from agents.java_8_to_25.stages import COMPANIONS_AFTER_STAGE, INCREMENTAL_STAGES, incremental_stages
from agents.shared import (
    approved_versions, knowledge_slice, progress, callbacks, change_audit, companion_detector, dependency_graph, diffing, java_preflight,
    learned_fixes, migration_inventory, plan_contract, plan_paths, plan_tasks, re_units, scope_fence, skill_manifest,
    skill_steps,
)
from agents.shared.pipeline_text import (
    file_digests, inject_dependency_graph, parse_re_sections, task_paths, unexplained_unchanged,
    with_reviewer_notes, workspace_paths,
)

from . import patterns as P
from .runstate import Run, RunError

SKILLS_DIR = Path(__file__).resolve().parent.parent / "agents" / "skills"
_COMPANION_PRIORITY = ["oracle-19c-to-23ai", "solr-4-to-9", "tibco-ems-to-pubsub"]

# Subagents (gemini-cli/agents/*.md), one per role.
ANALYST, PLANNER, CODER, VALIDATOR, REVIEWER, WRITER = (
    "modernizer-analyst", "modernizer-planner", "modernizer-coder", "modernizer-validator",
    "modernizer-reviewer", "modernizer-writer",
)


# ═════════════════════════════════════════════════════════════════════════════
# Starting a run
# ═════════════════════════════════════════════════════════════════════════════

MAX_REQUIREMENTS_CHARS = 4000


def requirements_block(run: Run, role: str) -> str:
    """The person's requirements as a section of a step's query ("" when none were given). `role` says what
    the step does with them: plan | review | report."""
    text = (run.state.get("requirements") or "").strip()
    if not text:
        return ""
    use = {
        "plan": ("These are binding. Where they ask for something the skill's defaults would leave alone (a "
                 "library to move, a version, a target), plan it: it is in scope, with a task and a manifest row "
                 "for every file it touches, and the plan's Open Questions cover only what you cannot decide. "
                 "Where they conflict with the scope fence, the approved-versions list or a rule the skill calls "
                 "absolute, keep the rule and say in the plan's Open Questions exactly which requirement it blocks "
                 "and why. Do not widen the work beyond them and the skill's own scope."),
        "review": ("Check the result against each requirement as well as the plan: a requirement the migrated "
                   "code does not meet is a finding, however well the plan was followed."),
        "report": ("Add a section \"Requirements\" that states, for each requirement, whether the result meets it "
                   "and the evidence (the file, the version, the build or test result) — or what is not met and why."),
    }[role]
    return f"## Requirements from the person who asked for this migration\n{text}\n\n{use}"


def start(workspace: Path, pattern: str, migration_strategy: str = "bigbang", springboot_upgrade: bool = False,
          junit_upgrade: bool = False, context_files: list[str] | None = None, restart: bool = False,
          requirements: str = "") -> Run:
    """Snapshot the repository and set up the run — main.py's upload handler,
    minus the upload: the repository is the one Gemini CLI has open.

    `requirements` is what the person asked for, in their words ("move Spring and Hibernate to compatible
    versions"). It goes to the planner, the reviewer and the reporter as binding text: the pattern's
    skill decides how to migrate by default, the requirements decide what this person needs."""
    if pattern not in P.ALL_PATTERNS:
        raise RunError(f"Unknown pattern '{pattern}'. Choose one of: {', '.join(P.ALL_PATTERNS)}.")
    if Run.exists(workspace) and not restart:
        raise RunError("A modernizer run already exists in this repository (.modernizer/run.json). "
                       "Continue it with /modernize:next, or start over with restart=true.")
    if migration_strategy not in ("bigbang", "incremental"):
        raise RunError("migration_strategy must be 'bigbang' or 'incremental'.")
    if pattern != P.JAVA_8_TO_25 and (migration_strategy != "bigbang" or junit_upgrade or springboot_upgrade):
        raise RunError("The incremental strategy and the JUnit / Spring Boot upgrade options apply to "
                       "java-8-to-25 only.")
    requirements = "\n".join(line.rstrip() for line in (requirements or "").strip().splitlines())
    if len(requirements) > MAX_REQUIREMENTS_CHARS:
        raise RunError(f"The requirements are {len(requirements):,} characters; keep them under "
                       f"{MAX_REQUIREMENTS_CHARS:,} (put long documents in context_files).")
    if requirements and pattern == P.STACK_DISCOVERY:
        raise RunError("Stack discovery documents what the repository contains, so requirements do not apply.")
    context = ""
    for name in context_files or []:
        path = (workspace / name).resolve() if not Path(name).is_absolute() else Path(name)
        if not path.is_file():
            raise RunError(f"Context file '{name}' not found.")
        from agents.shared.file_parser import extract_text
        text = extract_text(path.name, path.read_bytes())
        if text.strip():
            context += f"\n\n--- CONTEXT FILE: {path.name} ---\n{text}"
    if context and pattern == P.STACK_DISCOVERY:
        raise RunError("Stack discovery produces no plan, so context files do not apply.")

    run = Run.create(workspace, pattern, migration_strategy=migration_strategy,
                     springboot_upgrade=bool(springboot_upgrade), junit_upgrade=bool(junit_upgrade),
                     additional_context=context, requirements=requirements)
    ws = str(workspace)
    if pattern == P.STACK_DISCOVERY:
        from . import discovery
        discovery.init(run)
    else:
        graph = dependency_graph.build_dependency_graph(ws, pattern)
        run.state["dependency_graph_json"] = json.dumps(graph)
        recs = (companion_detector.detect_companions(ws, pattern)
                if pattern in companion_detector.COMPANION_CANDIDATES else [])
        run.state.update({"recommendations": recs, "selection_confirmed": not recs, "bundle": [pattern],
                          "phase": "select", "pi": 0, "sub": 0})
    run.save()
    return run


def summary(run: Run) -> str:
    s = run.state
    lines = [f"# Modernizer run `{s['run_id']}`", "",
             f"- **Pattern:** {s['pattern']}", f"- **Repository:** {s['workspace_dir']}",
             f"- **Baseline snapshot:** {s['baseline_dir']}"]
    if s["pattern"] == P.JAVA_8_TO_25:
        lines.append(f"- **Strategy:** {s.get('migration_strategy')} (Spring Boot upgrade: "
                     f"{s.get('springboot_upgrade')}, JUnit upgrade: {s.get('junit_upgrade')})")
    if s.get("requirements"):
        lines.append(f"- **Requirements:** {s['requirements'][:300]}" + (" …" if len(s["requirements"]) > 300 else ""))
    if s.get("bundle") and len(s["bundle"]) > 1:
        lines.append(f"- **Bundle:** {', '.join(s['bundle'])}")
    lines.append(f"- **Phase:** {s.get('phase')}")
    if s.get("current_step"):
        current = s["current_step"]
        if current["kind"] == "parallel":
            from .discovery import pending_ids
            open_ids = pending_ids(current)
            lines.append(f"- **Waiting on:** {len(open_ids)} of {len(current['members'])} parallel batches — "
                         + ", ".join(f"`{i}`" for i in open_ids))
        else:
            lines.append(f"- **Waiting on:** `{current['id']}` ({current['kind']})")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _uses_inventory(pattern: str) -> bool:
    if pattern == P.JAVA_8_TO_11:
        return config.JAVA11_ANALYSIS != "agent"
    if pattern not in migration_inventory.INVENTORY_PATTERNS:
        return False
    return pattern in migration_inventory.INVENTORY_ONLY or config.MIGRATION_ANALYSIS != "agent"


def _approved(run: Run, pattern: str, stage: int | None = None) -> str:
    entries, _ = approved_versions.load()
    text = approved_versions.to_markdown(approved_versions.effective(entries, pattern, stage))
    if pattern == P.JAVA_8_TO_11 and run.state.get("approved_unavailable"):
        text += ("\n\n**⚠ Not downloadable through the configured repository — do NOT use these until the list "
                 "is corrected:** " + ", ".join(f"`{u.split(' ')[0]}`" for u in run.state["approved_unavailable"]))
    return text or "(none listed)"


def _output_rule(step_id: str, what: str) -> str:
    return (f"\n\n## Output\nWhen you are done, call the `save_output` tool with `step_id` = `{step_id}` and "
            f"your complete {what} as `content` — that is the only output the pipeline reads; text you only "
            "reply with is lost. Then reply with one short line saying what you saved.")


def _files_block(run: Run, items: list[tuple[str, Path]]) -> str:
    rows = [f"- {label}: `{run.rel(path)}`" for label, path in items if path.is_file()]
    return ("\n\n## Inputs (read each with read_file before you start)\n" + "\n".join(rows)) if rows else ""


def _step(run: Run, step_id: str, kind: str, **fields) -> dict:
    step = {"id": step_id, "kind": kind, **fields}
    run.state["current_step"] = step
    run.save()
    return step


def _subagent(run: Run, step_id: str, subagent: str, query: str, title: str) -> dict:
    return _step(run, step_id, "subagent", subagent=subagent, title=title, query=query)


def _bundle(run: Run) -> list[str]:
    return run.state.get("bundle") or [run.state["pattern"]]


def build_pattern(run: Run, pattern: str) -> str | None:
    """The pattern whose build tool a `pattern` without one borrows: a companion (Oracle, Solr) changes
    dependencies, drivers and client code of a Java build, which only a real build can verify. It
    builds with the run's Java pattern's tool, on the JDK of the Java stage it follows. None when the
    pattern builds itself, or the run has no Java build."""
    if hasattr(P.get(pattern).tools(), "run_command"):
        return None
    return next((p for p in _bundle(run) if p in (P.JAVA_8_TO_25, P.JAVA_8_TO_11)
                 and hasattr(P.get(p).tools(), "run_command")
                 and (any(run.workspace.rglob("pom.xml")) or any(run.workspace.rglob("build.gradle*")))), None)


def _results(run: Run, pattern: str, name: str) -> Path:
    return run.result_path(f"{pattern}/{name}")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _parse_validation(raw: str) -> dict:
    """The validator's JSON verdict ({passed, errors, summary}); a reply that is not
    JSON is a failed validation with the reply as its summary — never a pass."""
    result = callbacks._parse_json_safely(raw or "")
    if not isinstance(result, dict) or "passed" not in result:
        return {"passed": False, "errors": [], "summary": (raw or "The validator saved no result.")[:4000]}
    result.setdefault("errors", [])
    return result


# ═════════════════════════════════════════════════════════════════════════════
# next_step / complete_step
# ═════════════════════════════════════════════════════════════════════════════

def next_step(run: Run) -> tuple[dict, list[str]]:
    """The step the run is waiting on, running every deterministic step on the way.
    Returns (step, log of what ran)."""
    if run.state["pattern"] == P.STACK_DISCOVERY:
        from . import discovery
        return discovery.next_step(run)
    log: list[str] = []
    current = run.state.get("current_step")
    if current and current["kind"] == "subagent":
        # Asked again before completing: the same step, so a restarted CLI picks up where it was.
        return current, log
    for _ in range(500):          # deterministic steps are finite; this only guards a bug
        phase = run.state.get("phase")
        handler = _PHASES[phase]
        step = handler(run, log)
        if step is not None:
            return step, log
    raise RunError("The pipeline did not reach a step — report this as a bug with .modernizer/run.json.")


def complete_step(run: Run, step_id: str) -> str:
    """Process what the subagent saved for `step_id` and advance the cursor."""
    if run.state["pattern"] == P.STACK_DISCOVERY:
        from . import discovery
        return discovery.complete_step(run, step_id)
    current = run.state.get("current_step") or {}
    if current.get("id") != step_id:
        raise RunError(f"The run is waiting on `{current.get('id', 'nothing')}`, not `{step_id}`. "
                       "Call next_step to see the current step.")
    if current["kind"] != "subagent":
        raise RunError(f"`{step_id}` is a {current['kind']} step — answer it with the command it names.")
    output = run.read_out(step_id)
    if not output.strip():
        raise RunError(f"Nothing was saved for `{step_id}`. The subagent must call save_output with that "
                       "step_id before the step can complete — run it again.")
    message = _COMPLETE[current["handler"]](run, current, output)
    run.state["current_step"] = None
    run.save()
    return message


# ── select ───────────────────────────────────────────────────────────────────

def _phase_select(run: Run, log: list[str]) -> dict | None:
    if run.state.get("selection_confirmed"):
        run.state["phase"] = "preflight"
        return None
    recs = run.state.get("recommendations") or []
    rows = "\n".join(
        f"- `{r['pattern']}` — {r.get('label', '')}: {r.get('reason', '')}"
        + "".join(f"\n    - {e}" for e in (r.get("evidence") or [])[:8]) for r in recs)
    return _step(run, "select-companions", "ask_user", title="Choose companion migrations", text=(
        f"The repository also uses technologies that must move for the {run.state['pattern']} migration to "
        f"keep working:\n\n{rows}\n\nAsk the user which of these to migrate in the same run (any, all or "
        "none), then call `confirm` with gate=`companions` and `selection` = the chosen pattern ids."))


def _phase_preflight(run: Run, log: list[str]) -> dict | None:
    java = next((p for p in _bundle(run) if java_preflight.module_for(p)), None) \
        if config.PREFLIGHT != "off" else None
    if java and not run.state.get("preflight_ok"):
        progress.stage(f"Environment check for {P.get(java).label}: JDKs, Maven, then a build of the code as uploaded")
        module = java_preflight.module_for(java)
        pf = java_preflight.run(java, str(run.workspace), run.state.get("migration_strategy") or "bigbang",
                                bool(run.state.get("springboot_upgrade")))
        run.state["preflight_json"] = pf.to_json()
        run.state["preflight_summary"] = module.summary(pf)
        run.state["approved_unavailable"] = list(pf.approved_unavailable or [])
        log.append(f"Environment check: {run.state['preflight_summary']}")
        if not pf.ok:
            run.save()
            return _step(run, "preflight", "blocked", title="Environment check failed", text=(
                f"Environment check failed — nothing was changed. {pf.stop_reason}\n\nFix the environment "
                "(MIGRATION_JAVA_HOME / MIGRATION_JAVA_HOMES, Maven, MAVEN_SETTINGS) and call next_step again; set "
                "PREFLIGHT=warn to continue with these problems reported, or PREFLIGHT=off to skip the check "
                "(nothing can then be verified)."))
        run.state["preflight_ok"] = True
    run.state.update({"phase": "analysis", "pi": 0, "sub": 0})
    run.save()
    return None


# ── analysis ─────────────────────────────────────────────────────────────────

def _store_analysis(run: Run, pattern: str, document: str) -> None:
    analysis, brd, tech, tests = parse_re_sections(document)
    tech = inject_dependency_graph(tech, run.state.get("dependency_graph_json", ""), pattern)
    tech = java_preflight.with_preflight(tech, pattern, run.state.get("preflight_json", ""))
    for name, text in (("analysis", document), ("brd", brd), ("technical_spec", tech), ("test_inventory", tests)):
        run.write_doc(name, text, pattern)


def _phase_analysis(run: Run, log: list[str]) -> dict | None:
    bundle = _bundle(run)
    pi = run.state.get("pi", 0)
    if pi >= len(bundle):
        agent = any(not _uses_inventory(p) for p in bundle)
        run.state.update({"phase": "analysis_review" if agent else "plan", "pi": 0, "sub": 0})
        run.save()
        return None
    pattern = bundle[pi]
    feedback = run.state.get("analysis_feedback")
    ws = str(run.workspace)
    if _uses_inventory(pattern):
        progress.stage(f"Analysis: the {P.get(pattern).label} inventory — every relevant file scanned against the "
                       "migration's checklist (no model)")
        if pattern == P.JAVA_8_TO_11:
            inv = java11_inventory.build(ws)
            document = java11_inventory.to_document(inv, max_rows=config.INVENTORY_MAX_ROWS)
            log.append(f"Java 11 inventory: {inv.files_scanned:,} files ({inv.lines_scanned:,} lines) scanned "
                       "without a language model.")
        else:
            document = migration_inventory.to_document(pattern, ws, config.INVENTORY_MAX_ROWS)
            log.append(f"{P.get(pattern).label} inventory generated without a language model.")
        _store_analysis(run, pattern, with_reviewer_notes(document, feedback))
        run.state.update({"pi": pi + 1, "sub": 0})
        run.save()
        return None
    return _analysis_agent_step(run, pattern, feedback)


def _analysis_agent_step(run: Run, pattern: str, feedback: str | None) -> dict:
    spec = P.get(pattern)
    sub = run.state.get("sub", 0)
    explore = ("Explore the repository with read_file, list_directory, glob and grep_search (it is the "
               "workspace root; ignore `.modernizer/`). These are the only way to inspect the code: nothing "
               "here executes it. Do not assume any file contents you have not read.")
    note = ""
    if feedback:
        previous = run.doc_path("analysis", pattern)
        note = (f"\n\n## Reviewer Feedback (revise the analysis accordingly)\n{feedback}"
                + (f"\n\nYour previous analysis is in `{run.rel(previous)}` — revise it rather than start over."
                   if previous.is_file() else ""))
    four = ("the four-section document the skill's OUTPUT CONTRACT specifies (the `<!-- SECTION: ... -->` "
            "markers as separators, in order)")
    if pattern == P.JSP_TO_REACT:
        if sub == 0:
            sid = f"analysis-{pattern}-facts"
            q = (skill_steps.cli_instruction(spec.re_skills[0]) + f" on this repository. {explore}{note}"
                 + _output_rule(sid, "extracted JSP facts"))
            return _sub(run, sid, ANALYST, q, "Extract JSP facts", "analysis", pattern=pattern, part="facts")
        sid = f"analysis-{pattern}"
        q = (skill_steps.cli_instruction(spec.re_skills[1]) + " to classify the extracted logic, then produce the "
             "standard four-section output (Analysis / BRD / Technical Specification / Existing Test "
             "Inventory) — fold the frontend-vs-backend classification table into the Technical "
             "Specification section." + note
             + _files_block(run, [("Extracted JSP facts", run.out_path(f"analysis-{pattern}-facts"))])
             + _output_rule(sid, four))
        return _sub(run, sid, ANALYST, q, "Classify JSP logic", "analysis", pattern=pattern, part="final")
    if pattern == P.JAVA_8_TO_11 and config.RE_UNIT_MAX_FILES > 0:
        units = run.state.get("re_units")
        if units is None:
            units = [{"id": u.id, "label": u.label, "files": u.files}
                     for u in re_units.plan_units(str(run.workspace), config.RE_UNIT_MAX_FILES)]
            run.state["re_units"] = units
        if len(units) > 1 and sub < len(units):
            unit = units[sub]
            sid = f"analysis-{pattern}-unit-{sub + 1}"
            listing = "\n".join(f"- `{f}`" for f in unit["files"][:config.RE_UNIT_MAX_FILES])
            q = (skill_steps.cli_instruction("java-8-to-11:re-module") + " (it also has you read "
                 f"`references/steps/re.md` for reference) for the unit below. {explore}\n\n## Your Unit\n{unit['label']} "
                 f"(unit {sub + 1} of {len(units)}) — these files:\n{listing}{note}"
                 + _output_rule(sid, "Module Findings for this unit"))
            return _sub(run, sid, ANALYST, q, f"Analyse unit {sub + 1}/{len(units)}", "analysis",
                        pattern=pattern, part="unit")
        if len(units) > 1:
            sid = f"analysis-{pattern}"
            findings = run.result_path(f"{pattern}/module-findings.md")
            parts = [run.read_out(f"analysis-{pattern}-unit-{i + 1}") for i in range(len(units))]
            findings.write_text("\n\n---\n\n".join(p for p in parts if p.strip()), encoding="utf-8")
            q = (skill_steps.cli_load_only("java-8-to-11:re") + " and write its four-section document, following its OUTPUT "
                 "CONTRACT and its section contents exactly. Its DISCOVERY WORKFLOW has already been carried "
                 "out, unit by unit: the Module Findings file below is its results and your only evidence — do "
                 "not inspect other files, and never claim to have read a file the findings do not cite. Carry "
                 "every row of every unit's Java 11 Blockers table into the Analysis blocker table and the "
                 "Technical Specification's dependency, removed-module and Frozen Zone sections; the plan's "
                 "file manifest depends on them." + note
                 + _files_block(run, [("Module Findings", findings)]) + _output_rule(sid, four))
            return _sub(run, sid, ANALYST, q, "Combine module findings", "analysis", pattern=pattern, part="final")
    sid = f"analysis-{pattern}"
    q = skill_steps.cli_instruction(spec.re_skills[0]) + f" on this repository. {explore}{note}" \
        + _output_rule(sid, four)
    return _sub(run, sid, ANALYST, q, f"Reverse-engineer ({spec.label})", "analysis", pattern=pattern, part="final")


def _sub(run: Run, step_id: str, subagent: str, query: str, title: str, handler: str, **fields) -> dict:
    # A step id can recur (a refined plan, a rewritten document): an earlier output must
    # never stand in for an answer the subagent did not save this time.
    run.out_path(step_id).unlink(missing_ok=True)
    return _step(run, step_id, "subagent", subagent=subagent, title=title, query=query, handler=handler, **fields)


def _complete_analysis(run: Run, step: dict, output: str) -> str:
    pattern = step["pattern"]
    if step["part"] != "final":
        run.state["sub"] = run.state.get("sub", 0) + 1
        return f"Saved {step['title'].lower()}."
    _store_analysis(run, pattern, output)
    run.state.update({"pi": run.state.get("pi", 0) + 1, "sub": 0})
    run.state.pop("re_units", None)
    return (f"Analysis for {pattern} split into BRD, Technical Specification and Test Inventory under "
            f"`{run.rel(run.doc_path('brd', pattern).parent)}/`.")


def _phase_analysis_review(run: Run, log: list[str]) -> dict | None:
    if run.state.get("analysis_confirmed"):
        run.state.update({"phase": "plan", "pi": 0})
        return None
    docs = "\n".join(f"- `{run.rel(run.doc_path(n, p))}`" for p in _bundle(run)
                     for n in ("brd", "technical_spec", "test_inventory"))
    return _step(run, "analysis-review", "review_gate", title="Review the analysis", text=(
        "HUMAN GATE 1 — the analysis was written by an agent, so a person confirms it before anything is "
        f"planned. Ask the user to review (and edit in place if needed):\n{docs}\n\nThen either "
        "`/modernize:approve` (calls `confirm` with gate=`analysis`) or `/modernize:refine <feedback>` "
        "(calls `refine` with gate=`analysis`)."))


# ── plan ─────────────────────────────────────────────────────────────────────

def _phase_plan(run: Run, log: list[str]) -> dict | None:
    bundle = _bundle(run)
    pi = run.state.get("pi", 0)
    if pi >= len(bundle):
        run.state.update({"phase": "plan_review", "pi": 0})
        return None
    pattern = bundle[pi]
    spec = P.get(pattern)
    sid = f"plan-{pattern}"
    feedback = run.state.get("plan_feedback")
    parts = [skill_steps.cli_instruction(spec.plan_skill) + " to create the migration plan.",
             skill_manifest.planner_block(spec.roster)]
    if requirements_block(run, "plan"):
        parts.append(requirements_block(run, "plan"))
    if pattern == P.JAVA_8_TO_25:
        parts.append(f"## Migration Strategy\n{run.state.get('migration_strategy')}\n\n"
                     f"## JUnit Upgrade Requested\n{str(run.state.get('junit_upgrade')).lower()}\n\n"
                     f"## Spring Boot Upgrade Requested\n{str(run.state.get('springboot_upgrade')).lower()}")
    if pattern == P.JAVA_8_TO_11:
        parts.append("## Scope Fence (the plan must stay inside it)\n" + FENCE_RULES)
    parts.append("## Approved Versions (your organisation's list — use exactly these for these artifacts)\n"
                 + _approved(run, pattern))
    parts.append("The Test Inventory is what question 4 is answered from — its Coverage Gaps section is the "
                 "starting point for the plan's own, never a substitute for it.")
    if len(bundle) > 1:
        parts.append(f"The documents may cover several migrations — plan the {spec.label} migration only.")
    if feedback:
        parts.append("Revise your previous plan (`" + run.rel(run.doc_path("plan", pattern)) + "`) based on the "
                     "reviewer's feedback, keeping its overall structure (and, if incremental, the exact same "
                     f"phase and stage headings).\n\n## Reviewer Feedback\n{feedback}")
    if run.state.get("additional_context", "").strip() and not feedback:
        ctx = run.result_path("additional-context.md")
        ctx.write_text(run.state["additional_context"], encoding="utf-8")
    inputs = [("Confirmed Business Requirements Document", run.doc_path("brd", pattern)),
              ("Confirmed Technical Specification", run.doc_path("technical_spec", pattern)),
              ("Existing Test Inventory", run.doc_path("test_inventory", pattern)),
              ("Additional context (Swagger / OpenAPI / design docs)", run.result_path("additional-context.md"))]
    if feedback:
        inputs.append(("Previous plan", run.doc_path("plan", pattern)))
    q = "\n\n".join(parts) + _files_block(run, inputs) + _output_rule(sid, "migration plan (markdown)")
    return _sub(run, sid, PLANNER, q, f"Plan ({spec.label})", "plan", pattern=pattern)


def check_plan(run: Run, pattern: str, plan: str) -> tuple[str, list[str]]:
    """The planner's after-callback and main.py's post-processing: Java 11 paths
    reconciled with the repository, and the completeness check appended."""
    notes = []
    plan = plan_contract.strip_warning(plan)
    if pattern == P.JAVA_8_TO_11:
        plan, fixed, missing = plan_paths.reconcile(plan, str(run.workspace))
        if fixed:
            notes.append(f"{len(fixed)} shortened path(s) corrected: "
                         + ", ".join(f"`{a}` → `{b}`" for a, b in list(fixed.items())[:10]))
        if missing:
            notes.append(f"{len(missing)} planned path(s) match no file (flagged at the top of the plan).")
    gaps = plan_contract.manifest_gaps(plan, run.read_doc("technical_spec", pattern))
    warning = plan_contract.to_markdown(plan_contract.check(plan), gaps)
    if warning:
        plan = plan.rstrip() + "\n" + warning
        notes.append("The plan does not answer every completeness question — see the warning at its end."
                     if not plan_contract.check(plan).complete else "The plan is complete.")
    if gaps:
        notes.append(f"{len(gaps)} file(s) with legacy code are not in the File Change Manifest: "
                     + ", ".join(f"`{p}`" for p, _ in gaps[:8]) + (" …" if len(gaps) > 8 else "")
                     + " — listed in the warning at the plan's end.")
    return plan, notes


def _complete_plan(run: Run, step: dict, output: str) -> str:
    pattern = step["pattern"]
    plan, notes = check_plan(run, pattern, output)
    path = run.write_doc("plan", plan, pattern)
    run.state["pi"] = run.state.get("pi", 0) + 1
    return f"Plan saved to `{run.rel(path)}`." + "".join(f"\n- {n}" for n in notes)


def _phase_plan_review(run: Run, log: list[str]) -> dict | None:
    if run.state.get("plan_approved"):
        run.state.update({"phase": "code", "pi": 0, "code": None})
        return None
    plans = "\n".join(f"- `{run.rel(run.doc_path('plan', p))}`" for p in _bundle(run))
    return _step(run, "plan-review", "review_gate", title="Approve the migration plan", text=(
        "HUMAN GATE 2 — nothing is changed until a person approves the plan. Ask the user to review (and edit "
        f"in place if needed):\n{plans}\n\nThen either `/modernize:approve` (calls `confirm` with gate=`plan`) "
        "or `/modernize:refine <feedback>` (calls `refine` with gate=`plan`)."))


# ── code generation ──────────────────────────────────────────────────────────

def _code_units(run: Run, pattern: str, plan: str) -> list[dict]:
    """The work list of one pattern: stages (java-8-to-25 incremental) or one
    pass, each with its modifier units (plan tasks, generators, or the plan)."""
    strategy = run.state.get("migration_strategy")
    if pattern == P.JAVA_8_TO_25 and strategy == "incremental":
        stages = []
        chosen = incremental_stages(bool(run.state.get("springboot_upgrade")))
        for pos, stage in enumerate(chosen, 1):
            units, _ = plan_tasks.stage_units(plan, stage.title)
            stages.append({"idx": stage.idx, "position": pos, "total": len(chosen), "title": stage.title,
                           "units": [{"id": u.id, "title": u.title, "body": u.body, "files": u.files}
                                     for u in units]})
        return stages
    if pattern == P.JAVA_8_TO_11:
        units, _ = plan_tasks.stage_units(plan, JAVA11_STAGE_TITLE)
        units = [{"id": u.id, "title": u.title, "body": u.body, "files": u.files} for u in units] or \
            [{"id": "all", "title": JAVA11_STAGE_TITLE, "body": plan, "files": []}]
        return [{"idx": 0, "position": 1, "total": 1, "title": JAVA11_STAGE_TITLE, "units": units}]
    spec = P.get(pattern)
    units = [{"id": skill.replace(":", "-"), "title": skill_steps.label(skill).replace("`", ""), "body": "",
              "files": [], "skill": skill} for skill in spec.modify_skills]
    return [{"idx": 0, "position": 1, "total": 1, "title": spec.label, "units": units}]


def _code_order(run: Run) -> list[dict]:
    """The code phase's passes, in order: the bundle's patterns, companions first — except in an
    incremental Java 8 -> 25 run, whose readiness stages build on JDK 8: there the companions (which
    need Java 11+) run once the Java 17 stage has passed (stages.COMPANIONS_AFTER_STAGE), between the
    Java stages' two halves. `part` "pre" ends without review; "post" carries its summaries on."""
    bundle = _bundle(run)
    primary = run.state["pattern"]
    companions = [p for p in bundle if p != primary]
    if primary == P.JAVA_8_TO_25 and companions and run.state.get("migration_strategy") == "incremental":
        return [{"pattern": primary, "part": "pre"}, *({"pattern": c} for c in companions),
                {"pattern": primary, "part": "post"}]
    return [{"pattern": p} for p in bundle]


def _phase_code(run: Run, log: list[str]) -> dict | None:
    code = run.state.get("code")
    if code is None:
        order = _code_order(run)
        pi = run.state.get("pi", 0)
        if pi >= len(order):
            run.state["phase"] = "finish"
            return None
        pattern, part = order[pi]["pattern"], order[pi].get("part")
        stages = _code_units(run, pattern, run.read_doc("plan", pattern))
        if part:
            stages = [s for s in stages if (s["idx"] <= COMPANIONS_AFTER_STAGE) == (part == "pre")]
        carried = run.state.pop("carried_code", None) if part == "post" else None
        code = {"pattern": pattern, "stages": stages, "split": part,
                "si": 0, "ui": 0, "retry": False, "iter": 0, "part": "modify",
                "summaries": (carried or {}).get("summaries", []), "written": (carried or {}).get("written", []),
                "earlier": (carried or {}).get("stages", []), "digests": {}}
        run.state["code"] = code
        run.state["current_pattern"] = pattern
        # What this pass changes is told apart from the bundle's other passes (see _record_pass).
        _pass_start(run, pattern).write_text(json.dumps(change_audit.snapshot(run.workspace)), encoding="utf-8")
        run.save()
    pattern = code["pattern"]
    spec = P.get(pattern)

    if code["part"] in ("modify", "build", "fix", "hold"):
        if code["si"] >= len(code["stages"]):
            _record_pass(run, code)
            if code.get("split") == "pre":
                # The companions run now; the Java stages resume after them, then one review over all.
                run.state["carried_code"] = {"summaries": code["summaries"], "written": code.get("written", []),
                                             "stages": code["stages"]}
                log.append(f"{spec.label}: stages up to Java 17 done — the companion migrations run next, then the "
                           "remaining stages.")
                code["part"] = "done"
                run.save()
                return None
            code["part"] = "review"
            run.save()
            return None
        stage = code["stages"][code["si"]]
        run.state["approved_stage"] = str(stage["idx"]) if stage["idx"] else ""
        if code["part"] == "hold":
            return _hold_step(run, code, stage)
        if code["part"] == "modify":
            if not stage["units"]:
                note = (f"SKIPPED — the confirmed plan has no `## Stage <n>: {stage['title']}` section, so there is "
                        "nothing approved for this stage to apply. Nothing was changed.")
                code["summaries"].append(f"### {stage['title']}\n{note}")
                log.append(f"{stage['title']}: {note}")
                _next_stage(code)
                run.save()
                return None
            if code["ui"] >= len(stage["units"]):
                if pattern == P.JAVA_8_TO_11:
                    log.append(_mockito_rewrite(run, code))
                _write_modify_result(run, code)
                code.update({"part": "build", "iter": 0, "extra": 0})
                run.save()
                return None
            return _modify_step(run, code, stage, spec)
        if code["part"] == "build":
            return _validate_step(run, code, stage, spec)
        return _fix_step(run, code, stage, spec)

    if code["part"] == "review":
        return _review_step(run, code, spec)
    if code["part"] == "report":
        return _report_step(run, code, spec)
    # done with this pattern
    run.state["code"] = None
    run.state["pi"] = run.state.get("pi", 0) + 1
    run.save()
    return None


def _pass_start(run: Run, pattern: str) -> Path:
    return _results(run, pattern, "pass_start.json")


def _record_pass(run: Run, code: dict) -> None:
    """Add the files this pass changed to `pass_changes`, so each pattern's review sets aside
    what only the bundle's other migrations changed (change_audit.other_migrations_files)."""
    try:
        before = json.loads(_read(_pass_start(run, code["pattern"])) or "{}")
    except json.JSONDecodeError:
        return
    changes = run.state.setdefault("pass_changes", {})
    changes[code["pattern"]] = sorted(set(changes.get(code["pattern"], [])) |
                                      set(change_audit.changed_since(run.workspace, before)))


def _next_stage(code: dict) -> None:
    code.update({"si": code["si"] + 1, "ui": 0, "retry": False, "iter": 0, "extra": 0, "part": "modify"})


def _stage_label(code: dict, stage: dict) -> str:
    if code["pattern"] == P.JAVA_8_TO_25 and (len(code["stages"]) > 1 or code.get("split")):
        return f"stage{stage['idx']}"
    return ""


def sliced_knowledge(run: Run, pattern: str, step_name: str, sid: str, match_text: str,
                     files: list[str] | None = None, stage_title: str = "") -> str:
    """The brief's paragraph pointing a subagent at per-task slices of the step's large knowledge files
    (agents/shared/knowledge_slice.py), "" when the step has none worth slicing or there is nothing to match
    against. Matched against: the stage title, `match_text` (the task's text, or a failing build's output) and
    the ORIGINAL contents of `files` — what the task has to change is what the repository had."""
    if not config.KNOWLEDGE_SLICING:
        return ""
    skill, step = skill_steps.parse(step_name)
    step_file = skill_steps.file(step_name)
    if not step_file.is_file():
        return ""
    line = next((l for l in step_file.read_text(encoding="utf-8").splitlines()
                 if l.startswith("**Knowledge for this step**")), "")
    base = Path(run.state.get("baseline_dir") or "")
    text_haystack = "\n".join([stage_title, match_text or ""])
    # What the task SAYS it does decides first; the original contents of its files only when its text names
    # nothing the knowledge file is tagged with (a file that mentions Spring is not a Spring task).
    file_text = []
    for rel in (files or [])[:40]:
        for root in (base, run.workspace):
            path = root / rel
            if path.is_file():
                try:
                    file_text.append(path.read_text(encoding="utf-8", errors="replace")[:60_000])
                except OSError:
                    pass
                break
    if not text_haystack.strip() or (not files and len(match_text or "") < 40):
        return ""
    joined = text_haystack
    made = []
    for rel in re.findall(r"`(references/[\w./-]+\.md)`", line):
        src = skill_steps.SKILLS_DIR / skill / rel
        if not src.is_file() or not knowledge_slice.tagged(text := src.read_text(encoding="utf-8")):
            continue
        sliced, kept, omitted = knowledge_slice.slice_text(text, joined, f"references/{Path(rel).name}")
        if kept <= knowledge_slice.core_count(text) and file_text:        # the text named nothing: use the files
            sliced, kept, omitted = knowledge_slice.slice_text(text, joined + "\n" + "\n".join(file_text),
                                                               f"references/{Path(rel).name}")
        if not omitted:
            continue
        out = run.result_path(f"{pattern}/knowledge/{sid}--{Path(rel).name}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(sliced, encoding="utf-8")
        made.append((rel, run.rel(out), len(text), len(sliced)))
    if not made:
        return ""
    names = "; ".join(f"read `{o}` INSTEAD of loading `{r}`" for r, o, _, _ in made)
    return ("## Knowledge for this task\nThe step file lists large knowledge files. For this task they were cut down to "
            f"the sections that apply to it: {names}. Each copy lists what it left out; if your task needs an omitted "
            "section, read it from the full file. Load the step's other knowledge files as usual.")


def _modify_step(run: Run, code: dict, stage: dict, spec: P.Pattern) -> dict:
    pattern = code["pattern"]
    unit = stage["units"][code["ui"]]
    suffix = _stage_label(code, stage)
    sid = f"modify-{pattern}{'-' + suffix if suffix else ''}-{re.sub(r'[^A-Za-z0-9.-]+', '-', unit['id'])}" \
          + ("-retry" if code["retry"] else "")
    write_tools = ("Read with read_file / grep_search / glob / list_directory; write ONLY with `ws_replace_in_file` "
                   "(preferred for edits to existing files) and `ws_write_file`."
                   + (" Remove a file the task makes obsolete with `ws_delete_file` (one file per call)."
                      if pattern == P.JAVA_8_TO_25 else ""))
    plan_file = [("Confirmed Migration Plan", run.doc_path("plan", pattern))]
    if pattern == P.JAVA_8_TO_25 and run.state.get("migration_strategy") == "incremental":
        st = next(s for s in INCREMENTAL_STAGES if s.idx == stage["idx"])
        guides = " and ".join(f"`{skill_steps.step_resource(n)}`" for n in st.extra_skills)
        preamble = (f"You are applying the '{st.title}' stage (step {stage['position']} of {stage['total']}, "
                    f"Phase {st.phase}: {st.phase_title}) of the confirmed migration plan.")
        body = (skill_steps.cli_instruction("java-8-to-25:modify") + " — apply ONLY the work described under '## Your Task' "
                f"below. It is one task of the '{st.title}' stage; earlier tasks and stages are already applied, and "
                "the remaining ones run as separate passes — do not do their work, and do not re-do work already "
                f"in place. {write_tools}\n\nThis is Phase {st.phase} ({st.phase_title}) of an incremental "
                "migration. After this stage the build's compiler release level (`maven.compiler.release` / "
                "`sourceCompatibility` / `targetCompatibility` / toolchain) must be exactly "
                f"{st.java_release}.\n\nGuardrail for this stage: {st.guardrail}\n\n"
                + (f"Also read and follow the stage guide{'s' if len(st.extra_skills) > 1 else ''} {guides} in the "
                   f"skill's folder — use the part covering '{st.title}'; it governs how this stage's changes are made "
                   "and supersedes the modify step's generic guidance for this stage.\n\n" if st.extra_skills else "")
                + "## Approved Versions (your organisation's list for this stage — use exactly these)\n"
                + _approved(run, pattern, st.idx) + f"\n\n## Your Task\n{preamble}\n\n{unit['body']}")
        plan_file = []
    elif pattern == P.JAVA_8_TO_11:
        preamble = f"You are applying the '{JAVA11_STAGE_TITLE}' migration plan, one task at a time."
        body = (skill_steps.cli_instruction("java-8-to-11:modify") + " — apply ONLY the work described under '## Your Task' "
                "below. Earlier tasks are already applied to the workspace and later ones run as separate passes — "
                f"do not do their work and do not redo work already in place. {write_tools}\n\n"
                "The target is exactly Java 11: after the run the build's compiler release (`maven.compiler.release` "
                "/ `<release>` / `options.release` / toolchain) is 11.\n\n" + FENCE_RULES
                + "\n\n## Approved Versions (use exactly these for these artifacts)\n" + _approved(run, pattern)
                + f"\n\n## Your Task\n{preamble}\n\n{unit['body']}")
        plan_file = [] if unit["id"] != "all" else plan_file
    elif pattern == P.JSP_TO_REACT:
        if unit["skill"] == "spring-boot-bff-generate":
            body = ("Activate the `spring-boot-bff-generate` skill to generate the BFF backend under the workspace "
                    "subdirectory `backend/`, reading the original JSP source (read-only reference) and writing new "
                    f"files. {write_tools}\n\n## Approved Versions (use exactly these for these artifacts)\n"
                    + _approved(run, pattern))
        else:
            backend = run.out_path(f"modify-{pattern}-spring-boot-bff-generate")
            plan_file.append(("Backend Generation Result (the actual BFF endpoints just generated)", backend))
            designs = run.state.get("ux_designs") or []
            body = ("Activate the `react-frontend-generate` skill to generate the React app under the workspace "
                    "subdirectory `frontend/`, reading the original JSP source (read-only reference) and writing new "
                    f"files. {write_tools} The BFF's API contract is in the plan — call it exactly as specified, do "
                    "not invent different endpoint shapes."
                    + ("\n\nUX design files to match (follow the skill's UX designs section and the plan's UX "
                       "Design Mapping): " + ", ".join(f"`{d}`" for d in designs) if designs else ""))
    else:
        extra = ""
        if pattern == P.JAVA_8_TO_25 and run.state.get("springboot_upgrade"):
            extra = ("\n\nA Spring Boot upgrade was requested: also read and follow the skill's "
                     "`references/steps/springboot-boot4.md` for the plan's Spring Boot 4 Target section — the final state is the newest Spring Boot "
                     "4.x as an executable JAR on an embedded Tomcat (never a WAR), with Spring Data JPA, Thymeleaf "
                     "instead of JSP, and every conflicting legacy library removed. It supersedes the modify step's "
                     "generic Spring Boot guidance.")
        body = (skill_steps.cli_instruction(unit["skill"]) + " to apply the confirmed migration plan to the "
                f"files in the workspace. {write_tools}{extra}\n\n## Approved Versions (your organisation's list — "
                f"use exactly these for these artifacts)\n" + _approved(run, pattern))
    if code["retry"]:
        left = "\n".join(f"- `{p}`" for p in code.get("left", []))
        body += ("\n\n## Not done yet\nYour previous pass on this task left these listed files exactly as they "
                 f"were, without listing them under Files skipped:\n{left}\nApply this task's change to each of them "
                 "now (read each file first). If one truly needs no change, list it under Files skipped with the "
                 "reason.")
    elif unit.get("files") and pattern == P.JAVA_8_TO_11:
        paths = task_paths(unit["files"], workspace_paths(str(run.workspace)))
        code["digests"] = file_digests(str(run.workspace), paths)
    if pattern in (P.JAVA_8_TO_25, P.JAVA_8_TO_11):
        knowledge = sliced_knowledge(run, pattern, spec.modify_skills[0], sid, unit["body"], unit.get("files"),
                                     stage.get("title", ""))
        if knowledge:
            body += "\n\n" + knowledge
    q = body + _files_block(run, plan_file) + _output_rule(
        sid, "modify result (what you changed, file by file; a `Files skipped` list with the reason for each "
             "listed file you did not change; anything refused)")
    title = f"{'Retry ' if code['retry'] else ''}{unit['title']}" + (f" — {stage['title']}" if suffix else "")
    return _sub(run, sid, CODER, q, title, "modify", pattern=pattern)


def _complete_modify(run: Run, step: dict, output: str) -> str:
    code = run.state["code"]
    stage = code["stages"][code["si"]]
    unit = stage["units"][code["ui"]]
    result = output.strip()
    msg = f"Recorded {step['title']}."
    if code["pattern"] == P.JAVA_8_TO_11 and code.get("digests"):
        left = unexplained_unchanged(str(run.workspace), code["digests"], result)
        if left and not code["retry"]:
            code.update({"retry": True, "left": left, "partial": result})
            return msg + f" {len(left)} listed file(s) unchanged and unexplained — the task goes back once."
        if code["retry"]:
            result = f"{code.pop('partial', '')}\n\n{result}".strip()
            if left:
                result += ("\n\n**⚠ NOT APPLIED** — listed in this task but still unchanged after a retry, with no "
                           "reason given:\n" + "\n".join(f"- `{p}`" for p in left))
    heading = f"### Task {unit['id']}: {unit['title']}" if unit.get("body") else f"### {unit['title']}"
    code["summaries"].append(f"{heading}\n{result}")
    code.update({"ui": code["ui"] + 1, "retry": False, "left": [], "digests": {}})
    return msg


def _mockito_rewrite(run: Run, code: dict) -> str:
    try:
        rewritten, why_not = java11_mechanical.rewrite_mockito_runner(str(run.workspace))
    except Exception as exc:                                  # noqa: BLE001 — reported, not fatal
        rewritten, why_not = [], f"failed — {type(exc).__name__}: {exc}"
    joined = "".join(code["summaries"])
    if rewritten or "org.mockito.runners" in joined or why_not.startswith("the build still"):
        shown = "\n".join(f"- `{p}`" for p in rewritten[:50]) + (
            f"\n- … and {len(rewritten) - 50} more" if len(rewritten) > 50 else "")
        code["summaries"].append(
            "### Mechanical rewrite: Mockito runner import\n"
            + (f"`org.mockito.runners.MockitoJUnitRunner` → `org.mockito.junit.MockitoJUnitRunner` in "
               f"{len(rewritten)} file(s) (identical behaviour: the old class is a deprecated subclass of the new "
               f"one in Mockito 2.x/3.x):\n{shown}" if rewritten else f"Not applied: {why_not}."))
    return f"Mechanical Mockito runner rewrite: {len(rewritten)} file(s)" + ("" if rewritten else f" ({why_not})")


def _write_modify_result(run: Run, code: dict) -> None:
    stage = code["stages"][code["si"]]
    suffix = _stage_label(code, stage)
    name = f"modify_result{'_' + suffix if suffix else ''}.md"
    stage_summaries = [s for s in code["summaries"] if s not in code.get("written", [])]
    _results(run, code["pattern"], name).write_text("\n\n".join(stage_summaries).strip() + "\n", encoding="utf-8")
    code.setdefault("written", []).extend(stage_summaries)


def _build_result_name(code: dict, stage: dict) -> str:
    suffix = _stage_label(code, stage)
    return f"build_result{'_' + suffix if suffix else ''}.json"


def _validate_step(run: Run, code: dict, stage: dict, spec: P.Pattern) -> dict:
    pattern = code["pattern"]
    suffix = _stage_label(code, stage)
    sid = f"validate-{pattern}{'-' + suffix if suffix else ''}-{code['iter'] + 1}"
    run.state["build_signalled"] = False
    body = skill_steps.cli_instruction(spec.validate_skill) + " to validate the workspace and report the result."
    # Java 8 -> 25 validations RUN the tests (VALIDATE_RUN_TESTS): a suite broken by the migration (a Mockito that
    # cannot mock on the new JDK, a removed API in a test) must fail the stage, not surface after the run.
    tests = pattern == P.JAVA_8_TO_25 and config.VALIDATE_RUN_TESTS
    compile_cmd = "mvn -B clean test" if tests else "mvn -q -DskipTests clean test-compile"
    package_cmd = "mvn -B clean package" if tests else "mvn -q -DskipTests clean package"
    if pattern == P.JAVA_8_TO_25 and suffix:
        st = next(s for s in INCREMENTAL_STAGES if s.idx == stage["idx"])
        body += (f" This is validating the '{st.title}' stage (Phase {st.phase}: {st.phase_title}) of an incremental "
                 f"migration — the build should target Java {st.java_release}.")
        if st.build_goal == "package":
            body += (f" For this stage run the `package` goal instead (`{package_cmd}`, or "
                     "`./gradlew assemble` for Gradle) so the new executable artifact is actually produced — a "
                     "failed repackage is a failed build.")
    if pattern == P.JAVA_8_TO_25 and not suffix and run.state.get("springboot_upgrade"):
        body += (" This big-bang run converts the application to a Spring Boot executable JAR: run the `package` goal "
                 f"instead (`{package_cmd}`, or `./gradlew clean bootJar`) so the "
                 "artifact is really produced — a failed repackage is a failed build.")
    if tests:
        known = (json.loads(run.state.get("preflight_json") or "{}") or {}).get("baseline_failing_tests") or []
        body += (f" Build command: `{compile_cmd}` (a package stage: `{package_cmd}`) — it RUNS THE TESTS, main and test "
                 "sources compiled and the suite executed on this stage's JDK.\n\n"
                 "## Tests\nA test that fails now and is not in the list below FAILS the validation: put each one in "
                 "`errors` as `TEST: Class#method — the failure`, whatever its cause (a library that cannot work on "
                 "this JDK, a removed API, a changed behaviour). A test the plan deliberately deleted or rewrote is "
                 "not a failure. Zero tests run when the repository has tests is also a failure (a broken runner).\n"
                 + ("Tests that ALREADY FAIL on the code as uploaded (before any change) — report them in `summary`, "
                    "never fail the validation for them:\n" + "\n".join(f"- `{t}`" for t in known[:60])
                    if known else "No test failed on the code as uploaded: every failure is the migration's."))
    note = spec.validator_note
    if build_pattern(run, pattern):
        note += (" This pass may also change the build (dependencies, the JDBC driver or client library) and Java "
                 f"code: ALSO build with ws_run_command (`{compile_cmd}`, or `gradle clean test`) — "
                 "it runs on the JDK of the Java stage this pass follows. The validation passes only when the "
                 "static check AND the build pass.")
    body += (f"\n\n{note}\n\nIf — and only if — the validation succeeded, call "
             "`ws_signal_build_success`; it refuses while an approved-versions or scope-fence check still fails, "
             "and then validation has failed. Never edit files: you only build and report.")
    q = body + _output_rule(sid, 'result as the JSON object the skill specifies: {"passed": true|false, "errors": '
                                 '[...], "summary": "..."}')
    return _sub(run, sid, VALIDATOR, q, f"Validate ({spec.label}{', ' + stage['title'] if suffix else ''}) "
                                        f"— pass {code['iter'] + 1}", "validate", pattern=pattern)


def _complete_validate(run: Run, step: dict, output: str) -> str:
    code = run.state["code"]
    stage = code["stages"][code["si"]]
    spec = P.get(code["pattern"])
    result = _parse_validation(output)
    if run.state.get("build_signalled"):
        result = {"passed": True, "errors": [],
                  "summary": result.get("summary") or "Validation passed — the validator signalled success."}
    elif result.get("passed"):
        # A JSON "passed" without the gate's agreement is not a pass: the gate is the check.
        result = {"passed": False, "errors": result.get("errors") or [],
                  "summary": "The validator reported a pass but did not call ws_signal_build_success (or it was "
                             "refused) — treated as a failed validation. " + str(result.get("summary", ""))}
    raw = json.dumps(result, indent=2, ensure_ascii=False)
    _results(run, code["pattern"], _build_result_name(code, stage)).write_text(raw, encoding="utf-8")
    # The validator's ADK callbacks: verify the fixer's pending lessons, and note new errors in its skill.
    ctx_state = {"build_result": raw, "pending_lessons": run.state.get("pending_lessons", "[]")}
    fake = type("Ctx", (), {"state": ctx_state})()
    learned_fixes.make_lesson_verify_callback("build_result", "pending_lessons", _lesson_targets(spec),
                                              spec.id)(fake)
    callbacks.make_skill_update_callback("build_result", skill_steps.file(spec.validate_skill, SKILLS_DIR),
                                         "Validation Pass")(fake)
    run.state["pending_lessons"] = ctx_state.get("pending_lessons", "[]")
    code["iter"] += 1
    if result["passed"]:
        _next_stage(code)
        return f"Validation PASSED for {step['title']}."
    if code["iter"] - code.get("extra", 0) >= max(1, config.BUILD_LOOP_MAX_ITERATIONS):
        if _holds_on_failure(code):
            code["part"], code["hold"] = "hold", {"errors": (result.get("errors") or [])[:12],
                                                 "summary": str(result.get("summary", ""))[:600]}
            return (f"Validation FAILED and the build loop is out of iterations "
                    f"(BUILD_LOOP_MAX_ITERATIONS={config.BUILD_LOOP_MAX_ITERATIONS}) — the run is paused for "
                    f"{step['title']}: the next stage does not start until the user decides.")
        _next_stage(code)
        return (f"Validation FAILED and the build loop is out of iterations (BUILD_LOOP_MAX_ITERATIONS="
                f"{config.BUILD_LOOP_MAX_ITERATIONS}) — moving on; the review and report will say so.")
    code["part"] = "fix"
    return f"Validation FAILED ({len(result.get('errors') or [])} error(s)) — the fixer runs next."


def _holds_on_failure(code: dict) -> bool:
    """An incremental Java 8 -> 25 run stops when a stage's build loop runs out: each stage builds on the previous
    one, so carrying on would stack the next upgrade on a repository that does not build."""
    return code["pattern"] == P.JAVA_8_TO_25 and (len(code["stages"]) > 1 or bool(code.get("split")))


HOLD_CHOICES = {
    "retry": "the user fixed the code themselves — validate this stage again",
    "fix": "the fixer tries again",
    "skip": "carry on with the next stage as it is, knowing it does not build",
}


def _hold_step(run: Run, code: dict, stage: dict) -> dict:
    hold = code.get("hold") or {}
    errors = "\n".join(f"- {e}" for e in hold.get("errors") or []) or "- (no individual errors were reported)"
    budget = max(1, config.BUILD_LOOP_MAX_ITERATIONS)
    return _step(run, "stage-build-failed", "ask_user", title=f"Build failing after {stage['title']}", text=(
        f"The build/fix loop used all {budget} validation(s) of the **{stage['title']}** stage and the build still "
        "fails. The run is paused here on purpose: the next stage would build on a repository that does not "
        f"compile.\n\nLast validation: {hold.get('summary') or 'failed'}\n\nErrors:\n{errors}\n\n"
        f"The workspace is `{run.workspace}` — the user can open it and fix it by hand (the full report is in "
        f"`{run.rel(_results(run, code['pattern'], _build_result_name(code, stage)))}`). Tell the user this, show the "
        "errors, and ask which they want, then call `confirm` with gate=`stage` and `selection` = [that choice]:\n"
        + "\n".join(f"- `{k}` — {v}" for k, v in HOLD_CHOICES.items())
        + f"\n\nA `retry` or `fix` gives the loop {budget} more validation(s) for this stage."))


def _lesson_targets(spec: P.Pattern):
    if spec.id == P.JSP_TO_REACT:
        return learned_fixes.jsp_targets(SKILLS_DIR)
    return learned_fixes.skill_targets(SKILLS_DIR, spec.modify_skills[0], spec.fix_skill)


def _fix_step(run: Run, code: dict, stage: dict, spec: P.Pattern) -> dict:
    pattern = code["pattern"]
    suffix = _stage_label(code, stage)
    sid = f"fix-{pattern}{'-' + suffix if suffix else ''}-{code['iter']}"
    body = (skill_steps.cli_instruction(spec.fix_skill) + " on the validation report below. Read with "
            "read_file / grep_search / glob / list_directory; write ONLY with `ws_replace_in_file` and "
            "`ws_write_file`.")
    if pattern == P.JAVA_8_TO_11:
        body += "\n\n" + FENCE_RULES
    st_idx = stage["idx"] if suffix else None
    if pattern in (P.JAVA_8_TO_25, P.JAVA_8_TO_11):
        report = _read(_results(run, pattern, _build_result_name(code, stage)))
        knowledge = sliced_knowledge(run, pattern, spec.fix_skill, sid, report,
                                     re.findall(r"[\w./-]+\.(?:java|xml|properties|gradle|jsp)\b", report),
                                     stage.get("title", "") if suffix else "")
        if knowledge:
            body += "\n\n" + knowledge
    body += "\n\n## Approved Versions (your organisation's list — use exactly these)\n" + _approved(run, pattern, st_idx)
    plan_item = ("Confirmed Migration Plan", run.doc_path("plan", pattern))
    if suffix and pattern == P.JAVA_8_TO_25:
        # An incremental fix repairs ONE stage: that stage's section is what it needs (the whole plan, every
        # stage's tasks, is the biggest thing it would otherwise re-read on each pass).
        section = plan_tasks.stage_section(run.read_doc("plan", pattern), stage.get("title", ""))
        if section.strip():
            part = _results(run, pattern, f"plan_{suffix}.md")
            part.write_text(f"# Plan — the '{stage['title']}' stage (an extract of the confirmed plan)\n\n{section}\n\n"
                            f"---\nThe full plan is `{run.rel(run.doc_path('plan', pattern))}`; read it only if the "
                            "errors point at work another stage owns.\n", encoding="utf-8")
            plan_item = (f"Confirmed Migration Plan — this stage's section", part)
    q = body + _files_block(run, [("Validation Report (errors to fix)",
                                   _results(run, pattern, _build_result_name(code, stage))),
                                  plan_item]) \
        + _output_rule(sid, "fix result, ending with the skill's `## Lessons` block")
    return _sub(run, sid, CODER, q, f"Fix ({spec.label}) — pass {code['iter']}", "fix", pattern=pattern)


def _complete_fix(run: Run, step: dict, output: str) -> str:
    code = run.state["code"]
    stage = code["stages"][code["si"]]
    raw = _read(_results(run, code["pattern"], _build_result_name(code, stage)))
    ctx_state = {"fix_result": output, "build_result": raw}
    fake = type("Ctx", (), {"state": ctx_state})()
    learned_fixes.make_lesson_capture_callback("fix_result", "build_result", "pending_lessons")(fake)
    run.state["pending_lessons"] = ctx_state.get("pending_lessons", "[]")
    with _results(run, code["pattern"], "fix_result.md").open("a", encoding="utf-8") as fh:
        fh.write(f"\n\n## {step['title']}\n\n{output.strip()}\n")
    code["part"] = "build"
    return "Fix recorded — validation runs again."


def _all_stages(code: dict) -> list[dict]:
    """Every stage of the pattern's run, including those done before the companions ran."""
    return code.get("earlier", []) + code["stages"]


def _stage_results_block(run: Run, code: dict) -> list[tuple[str, Path]]:
    items = []
    for stage in _all_stages(code):
        suffix = _stage_label(code, stage)
        mod = _results(run, code["pattern"], f"modify_result{'_' + suffix if suffix else ''}.md")
        build = _results(run, code["pattern"], _build_result_name(code, stage))
        label = f" — {stage['title']}" if suffix else ""
        items += [(f"Modify Result{label}", mod), (f"Final Build Result{label}", build)]
    return items


def _review_step(run: Run, code: dict, spec: P.Pattern) -> dict:
    pattern = code["pattern"]
    sid = f"review-{pattern}"
    body = ("Activate the `code-review` skill and execute it. The build/validate/fix loop has already run and either "
            "confirmed the code builds or exhausted its retry budget — your review is about correctness and quality "
            "BEYOND \"does it compile\": logic gaps, edge cases, leftover placeholders/TODOs, inconsistencies with "
            "the confirmed plan, and anything mechanical build validation cannot see. Inspect the ACTUAL current "
            "code on disk with read_file / grep_search — do not review from memory of what an earlier summary said "
            "it wrote.\n\nCall `ws_audit_changes` FIRST, then `ws_compare_plan_to_changes`, before any other tool. "
            "Both diff the pristine repository against the migrated workspace, so together they are your only "
            "evidence for what you cannot see by reading changed files alone. The audit asks whether a change is "
            "migration work at all, and whether the untouched files were genuinely irrelevant. The plan check asks "
            "whether this run did what the human actually approved. Adjudicate every candidate from both against "
            "the confirmed plan — they report deterministic evidence, not verdicts, and a file flagged by both is "
            "one finding, not two.")
    if pattern == P.JAVA_8_TO_11:
        body += ("\n\nThis is a Java 8 → Java 11 upgrade of a JSP + WildFly application. JSP files, web resources and "
                 "WildFly descriptors are FROZEN — any change to one is a CRITICAL finding, as is a `jakarta.*` "
                 "import, a Java level other than 11, a changed `<packaging>`/`<finalName>`, or Spring Boot. "
                 "Untouched JSP/WildFly files are correct by design, never coverage gaps.")
    if len(_all_stages(code)) > 1:
        body += ("\n\nThis is the FULL final codebase after every incremental stage completed — review it as one "
                 "whole, not stage by stage.")
    if requirements_block(run, "review"):
        body += "\n\n" + requirements_block(run, "review")
    q = body + _files_block(run, [("Confirmed Migration Plan", run.doc_path("plan", pattern))]
                            + _stage_results_block(run, code)) + _output_rule(sid, "code review")
    return _sub(run, sid, REVIEWER, q, f"Independent code review ({spec.label})", "review", pattern=pattern)


def _complete_review(run: Run, step: dict, output: str) -> str:
    code = run.state["code"]
    _results(run, code["pattern"], "code_review.md").write_text(output, encoding="utf-8")
    code["part"] = "report"
    return f"Code review saved to `{run.rel(_results(run, code['pattern'], 'code_review.md'))}`."


def _report_step(run: Run, code: dict, spec: P.Pattern) -> dict:
    pattern = code["pattern"]
    sid = f"report-{pattern}"
    body = (skill_steps.cli_instruction(spec.report_skill) + " to produce the final migration report. Fold the "
            "Independent Code Review's findings into a dedicated report section rather than ignoring them.")
    if requirements_block(run, "report"):
        body += "\n\n" + requirements_block(run, "report")
    if len(_all_stages(code)) > 1:
        body += " Cover every stage of this phased incremental migration."
    if run.state.get("unresolved_stages"):
        body += ("\n\n## Stages that did not build\nThe user chose to continue past these stages although their "
                 "build still failed — state this prominently in the report, and that later stages were built on "
                 "top of them:\n" + "\n".join(f"- {u}" for u in run.state["unresolved_stages"]))
    if java_preflight.module_for(pattern) and run.state.get("preflight_summary"):
        body += f"\n\n## Build Environment (preflight, before the migration)\n{run.state['preflight_summary']}"
    items = _stage_results_block(run, code) + [
        ("Independent Code Review", _results(run, pattern, "code_review.md")),
        ("Fix passes", _results(run, pattern, "fix_result.md"))]
    if pattern == P.JSP_TO_REACT:
        items.insert(0, ("Backend Generation Result", run.out_path(f"modify-{pattern}-spring-boot-bff-generate")))
        items.insert(1, ("Frontend Generation Result", run.out_path(f"modify-{pattern}-react-frontend-generate")))
    q = body + _files_block(run, items) + _output_rule(sid, "final migration report (markdown)")
    return _sub(run, sid, WRITER, q, f"Final report ({spec.label})", "report", pattern=pattern)


def _complete_report(run: Run, step: dict, output: str) -> str:
    code = run.state["code"]
    _results(run, code["pattern"], "final_report.md").write_text(output, encoding="utf-8")
    code["part"] = "done"
    return f"Report saved to `{run.rel(_results(run, code['pattern'], 'final_report.md'))}`."


# ── finish ───────────────────────────────────────────────────────────────────

def _phase_finish(run: Run, log: list[str]) -> dict | None:
    progress.stage("Finishing: comparing the repository with its baseline snapshot (changes.md, changes.patch)")
    ws, base = str(run.workspace), run.state.get("baseline_dir", "")
    for pattern in _bundle(run):
        if not scope_fence.fence_for(pattern):
            continue
        undone = scope_fence.restore_frozen(pattern, base, ws)
        if undone:
            note = ("\n\n---\n\n## Scope Fence Enforcement (automated)\n\n"
                    f"{len(undone)} frozen file(s) differed from the original after code generation and were put back "
                    "exactly as they were before the result was assembled. The delivered workspace does not contain "
                    "these changes; the independent review above saw them before they were undone.\n\n"
                    + "\n".join(f"- `{path}` — {action}" for path, action in undone))
            report = _results(run, pattern, "final_report.md")
            report.write_text(_read(report) + note, encoding="utf-8")
            log.append(f"Scope fence: put back {len(undone)} frozen file(s).")
    changed = diffing.compute_changed_files(base, ws) if base else []
    lines = ["# Changed Files", "", f"{len(changed)} file(s) differ from the repository as it was when the run "
             "started.", "", "| Status | File |", "|---|---|"]
    lines += [f"| {c['status']} | `{c['path']}` |" for c in changed]
    run.result_path("changes.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    run.result_path("changes.patch").write_text("\n".join(c["diff"] for c in changed if c.get("diff")),
                                                encoding="utf-8")
    run.state.update({"phase": "done", "changed_files": len(changed)})
    log.append(f"{len(changed)} changed file(s) listed in `.modernizer/results/changes.md` (diff in changes.patch).")
    run.save()
    return None


def _phase_done(run: Run, log: list[str]) -> dict:
    reports = "\n".join(f"- `{run.rel(_results(run, p, 'final_report.md'))}`" for p in _bundle(run))
    return _step(run, "done", "done", title="Migration complete", text=(
        f"The run is complete. Reports:\n{reports}\n- Changed files: `.modernizer/results/changes.md` "
        "(full diff: `.modernizer/results/changes.patch`).\n\nThe repository was changed in place; the "
        f"original is at `{run.state.get('baseline_dir')}`. Review the changes with git before committing."))


_PHASES = {
    "select": _phase_select, "preflight": _phase_preflight, "analysis": _phase_analysis,
    "analysis_review": _phase_analysis_review, "plan": _phase_plan, "plan_review": _phase_plan_review,
    "code": _phase_code, "finish": _phase_finish, "done": _phase_done,
}
_COMPLETE = {
    "analysis": _complete_analysis, "plan": _complete_plan, "modify": _complete_modify,
    "validate": _complete_validate, "fix": _complete_fix, "review": _complete_review,
    "report": _complete_report,
}


# ═════════════════════════════════════════════════════════════════════════════
# Human gates
# ═════════════════════════════════════════════════════════════════════════════

def confirm(run: Run, gate: str, selection: list[str] | None = None, documents: list[str] | None = None) -> str:
    if run.state["pattern"] == P.STACK_DISCOVERY:
        from . import discovery
        return discovery.confirm(run, gate, selection, documents)
    phase = run.state.get("phase")
    if gate == "companions":
        if phase != "select":
            raise RunError("Companions are chosen at the start of a run, before the analysis.")
        offered = {r["pattern"] for r in run.state.get("recommendations") or []}
        chosen = [p for p in (selection or []) if p in offered]
        unknown = [p for p in (selection or []) if p not in offered]
        if unknown:
            raise RunError(f"Not offered for this repository: {', '.join(unknown)}. Offered: {', '.join(offered)}.")
        run.state["bundle"] = [p for p in _COMPANION_PRIORITY if p in chosen] + [run.state["pattern"]]
        run.state["selection_confirmed"] = True
        run.state["current_step"] = None
        run.save()
        return f"Running: {', '.join(run.state['bundle'])}."
    if gate == "analysis":
        if phase != "analysis_review":
            raise RunError(f"The analysis is not waiting for review (phase: {phase}).")
        run.state.update({"analysis_confirmed": True, "current_step": None, "analysis_feedback": None})
        run.save()
        return "Analysis confirmed — the planner runs next."
    if gate == "plan":
        if phase != "plan_review":
            raise RunError(f"No plan is waiting for approval (phase: {phase}).")
        digest = hashlib.sha256("".join(run.read_doc("plan", p) for p in _bundle(run)).encode()).hexdigest()
        run.state.update({"plan_approved": True, "plan_sha256": digest, "current_step": None, "plan_feedback": None})
        run.save()
        return "Plan approved — code generation starts. Edits to the plan after this point are not used."
    if gate == "stage":
        code = run.state.get("code") or {}
        if phase != "code" or code.get("part") != "hold":
            raise RunError("No stage is paused on a failing build.")
        choice = (selection or [""])[0]
        if choice not in HOLD_CHOICES:
            raise RunError(f"Choose one of: {', '.join(HOLD_CHOICES)} (selection = [the choice]).")
        stage = code["stages"][code["si"]]
        run.state["current_step"] = None
        if choice == "skip":
            run.state.setdefault("unresolved_stages", []).append(
                f"{stage['title']} — its build still failed when the run continued: "
                + "; ".join(str(e) for e in (code.get("hold") or {}).get("errors", [])[:5]))
            code.pop("hold", None)
            _next_stage(code)
            run.save()
            return (f"Continuing without a passing build for {stage['title']} — the report will say so. "
                    "The next stage builds on it as it is.")
        code["extra"] = code["iter"]
        code["part"] = "build" if choice == "retry" else "fix"
        code.pop("hold", None)
        run.save()
        return (f"{stage['title']}: " + ("validating again after the user's changes." if choice == "retry"
                                          else "the fixer runs again.") + " The next stage waits for a passing build.")
    raise RunError(f"Unknown gate '{gate}'. Gates: companions, analysis, plan, stage.")


def refine(run: Run, gate: str, feedback: str) -> str:
    if run.state["pattern"] == P.STACK_DISCOVERY:
        from . import discovery
        return discovery.refine(run, gate, feedback)
    if not (feedback or "").strip():
        raise RunError("Say what should change.")
    phase = run.state.get("phase")
    if gate == "analysis":
        if phase != "analysis_review":
            raise RunError(f"The analysis is not waiting for review (phase: {phase}).")
        run.state.update({"phase": "analysis", "pi": 0, "sub": 0, "analysis_feedback": feedback,
                          "current_step": None})
    elif gate == "plan":
        if phase != "plan_review":
            raise RunError(f"No plan is waiting for approval (phase: {phase}).")
        run.state.update({"phase": "plan", "pi": 0, "plan_feedback": feedback, "current_step": None})
    else:
        raise RunError("Refine applies to the `analysis` or the `plan`.")
    run.save()
    return f"The {gate} will be revised with this feedback — call next_step."
