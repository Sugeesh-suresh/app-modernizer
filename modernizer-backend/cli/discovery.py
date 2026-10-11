"""
"Discover & Reverse Engineer My Stack" for Gemini CLI.

The same stages as main.py's stack-discovery workflow, as a job queue in
`.modernizer/run.json`:

    dependency mapper (agent) -> HUMAN: confirm stacks + documents
    -> evidence per stack (agent; units for a large stack)      reading
    -> business-rules ledger (agent per batch, checked in code)
    -> UI screens (no model) -> computed sections (no model)
    -> Product Owner BRD, Enterprise Architect spec / UI contracts / diagrams (agents, no code reading)
    -> grounding, scrubbing, evidence check, assembly (no model)
    -> HUMAN: review -> done

Every check between the agents is the shared code the web pipeline uses:
evidence numbering (evidence_pack), grounding, the migration-language scrubber
(current_state), the plain-language BRD backstop, the rules ledger, the UI
contracts and the architecture diagrams.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

from agents import config
from agents.shared import (
    arch_diagrams, config_matrix, current_state, dependency_graph, evidence_pack, existing_tests, external_rules,
    grounding, interfaces, plain_language, repo_fingerprint, rule_candidates, rules_ledger, stack_detector,
    code_health, deliverables, openapi_spec, re_strategy, setup_facts, system_inventory, ui_contracts, ui_page_traces, ui_pages, ui_screens,
)
from agents.shared.pipeline_text import (
    DISCOVERY_GRAPHS, ELIDED_SPEC, ELIDED_TESTS, ELIDED_UI, SPEC_DIAGRAMS_BEFORE, SPEC_UI_CONTRACTS_BEFORE,
    WRITER_RULES_INDEX_CHARS,
    clip_findings, current_state_only, diagram_facts, diagram_refs, file_units, for_writer,
    inject_dependency_graph, merge_mapper_result, module_names, rule_languages, stack_files, unit_label,
    without_result_block,
)

from .pipeline import ANALYST, WRITER, _output_rule, _step, _sub
from .runstate import Run, RunError

DOCUMENTS = ("brd", "technical_spec", "test_inventory", "setup", "openapi", "tech_debt", "ui_pages", "ui_screens")
DEFAULT_DOCUMENTS = ("brd", "technical_spec", "test_inventory", "setup", "openapi", "tech_debt", "ui_pages")
#: The final deliverables, one file each, in `.modernizer/deliverables/`.
DELIVERABLES_DIR = "deliverables"
TITLE = "Technology Stack Discovery"


def _d(run: Run, *parts: str) -> Path:
    path = run.dir.joinpath("discovery", *parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _label(run: Run, stack_id: str) -> str:
    info = next((s for s in run.state.get("recommendations", []) if s["pattern"] == stack_id), {})
    return info.get("label") or stack_detector.STACK_LABELS.get(stack_id) or current_state.neutral_ids(stack_id)


def _stacks(run: Run) -> list[dict]:
    chosen = run.state.get("selection") or []
    return [s for s in run.state.get("recommendations", []) if s["pattern"] in chosen]


def _documents(run: Run) -> set[str]:
    return set(run.state.get("documents") or DEFAULT_DOCUMENTS)


def _keep(run: Run) -> frozenset:
    return current_state.targets_in_repo(run.state.get("stack_fingerprint", "") + "\nstacks: "
                                         + " ".join(s["pattern"] for s in run.state.get("recommendations", [])))


# ═════════════════════════════════════════════════════════════════════════════
# Start, next_step, complete_step
# ═════════════════════════════════════════════════════════════════════════════

def init(run: Run) -> None:
    ws = str(run.workspace)
    prescan = stack_detector.detect_stacks(ws)
    fingerprint = repo_fingerprint.fingerprint(ws)
    run.state.update({
        "phase": "discovery",
        "prescan": prescan,
        "recommendations": prescan,
        "stack_fingerprint": repo_fingerprint.to_prompt(fingerprint)[:20000],
        "jobs": [{"kind": "mapper"}],
    })


def next_step(run: Run) -> tuple[dict, list[str]]:
    log: list[str] = []
    current = run.state.get("current_step")
    if current and current["kind"] == "subagent":
        return current, log
    for _ in range(10_000):
        jobs = run.state.get("jobs") or []
        if not jobs:
            return _step(run, "done", "done", title="Discovery complete", text=_done_text(run)), log
        job = jobs[0]
        step = _JOBS[job["kind"]](run, job, log)
        if step is not None:
            return step, log
        run.state["jobs"] = run.state["jobs"][1:]      # a deterministic job finished
        run.save()
    raise RunError("Discovery did not reach a step — report this as a bug with .modernizer/run.json.")


def complete_step(run: Run, step_id: str) -> str:
    current = run.state.get("current_step") or {}
    if current.get("id") != step_id:
        raise RunError(f"The run is waiting on `{current.get('id', 'nothing')}`, not `{step_id}`.")
    if current["kind"] != "subagent":
        raise RunError(f"`{step_id}` is a {current['kind']} step — answer it with the command it names.")
    output = run.read_out(step_id)
    if not output.strip():
        raise RunError(f"Nothing was saved for `{step_id}` — the subagent must call save_output first.")
    job = run.state["jobs"][0]
    run.state["jobs"] = run.state["jobs"][1:]
    message = _DONE[job["kind"]](run, job, output)
    run.state["current_step"] = None
    run.save()
    return message


def _push_front(run: Run, *jobs: dict) -> None:
    run.state["jobs"] = list(jobs) + run.state.get("jobs", [])


# ── dependency mapper ────────────────────────────────────────────────────────

def _job_mapper(run: Run, job: dict, log: list[str]) -> dict:
    request = _write(_d(run, "requests", "mapper.md"), (
        "## Repository Fingerprint (parsed manifests, imports, script includes, languages)\n"
        f"{run.state.get('stack_fingerprint', '')}\n\n"
        "## Pre-scan Findings (stacks derived from the fingerprint, already run)\n"
        f"{stack_detector.to_markdown(run.state['prescan']) or 'No stacks detected by the pre-scan.'}\n\n"
        "## Stack Identifiers\nUse one of these exact `pattern` values in your JSON block wherever it fits. Any "
        "other stack you find gets a short kebab-case identifier of your own and is documented the same way, so "
        "report every stack the application is built on — do not squeeze one into an identifier that does not "
        "fit.\n" + "\n".join(f"- `{s.pattern}` — {s.label} ({s.kind})" for s in stack_detector.CATALOG)))
    sid = "mapper"
    q = ("Activate the `dependency-mapper` skill and execute it on this repository (the workspace root; ignore "
         "`.modernizer/`), reading build files, dependency declarations, descriptors and configuration with "
         "read_file / glob / grep_search / list_directory. Map every technology stack in this repository: confirm, "
         "reject or extend the pre-scan findings in the request file, and end with the machine-readable JSON block."
         f"\n\n## Request\nRead `{run.rel(request)}` first." + _output_rule(sid, "stack inventory, ending with the JSON block"))
    return _sub(run, sid, ANALYST, q, "Map the technology stacks", "mapper")


def _done_mapper(run: Run, job: dict, raw: str) -> str:
    ws = str(run.workspace)
    stacks, notes = merge_mapper_result(run.state["prescan"], raw, ws)
    inventory = stack_detector.to_markdown(stacks, source="deterministic scan + dependency mapper")
    import re
    prose = re.sub(r"^(#{1,4})(?=\s)", lambda m: "#" * min(len(m.group(1)) + 2, 6), without_result_block(raw),
                   flags=re.M)
    if prose:
        inventory += "\n\n" + prose
    if notes:
        inventory += "\n\n### Mapper Reconciliation Notes\n\n" + "\n".join(f"- {n}" for n in notes)
    inventory += "\n\n" + repo_fingerprint.to_markdown(repo_fingerprint.fingerprint(ws), None, None)
    _write(_d(run, "stack_inventory.md"), inventory)
    run.state["recommendations"] = stacks
    run.state["screens_offer"] = ui_screens.offer(stacks)
    _push_front(run, {"kind": "select"})
    return f"{len(stacks)} stack(s) mapped" + (f"; {len(notes)} reconciliation note(s)" if notes else "") + "."


def _job_select(run: Run, job: dict, log: list[str]) -> dict:
    rows = "\n".join(f"- `{s['pattern']}` — {s.get('label', '')} ({s.get('kind', '')})"
                     + "".join(f"\n    - {e}" for e in (s.get("evidence") or [])[:3])
                     for s in run.state["recommendations"])
    offer = run.state.get("screens_offer")
    screens = ""
    if offer:
        screens = ("\n\nUI Screens (`ui_screens`) can also be produced" if offer.get("available")
                   else "\n\nUI Screens are not available") + (f": {offer['reason']}" if offer.get("reason") else ".")
    return _step(run, "select-stacks", "ask_user", title="Confirm the stacks to document", text=(
        f"The dependency mapper found these stacks (inventory: `.modernizer/discovery/stack_inventory.md`):\n\n{rows}"
        f"\n\nDocuments: `brd` (BRD.md), `technical_spec` (TECHNICAL_SPECIFICATION.md), `test_inventory`, `setup` "
        f"(SETUP.md), `openapi` (openapi.yaml / openapi.json), `tech_debt` (TECH_DEBT_AND_DEAD_CODE.md), `ui_pages` "
        f"(UI_PAGES.md: every page's HTML elements, interactive elements and their traces to the backend; produced "
        f"when the repository has a UI) — default: all of these — and `ui_screens` (UI_SCREENS.md: a screenshot of "
        f"each page).{screens}\n\n"
        "Ask the user which stacks to document and which documents to produce, then call `confirm` with "
        "gate=`stacks`, `selection` = the stack ids and `documents` = the document ids. The reverse-engineering "
        "strategy is offered next, before anything is read."))


def confirm(run: Run, gate: str, selection: list[str] | None, documents: list[str] | None) -> str:
    jobs = run.state.get("jobs") or []
    if gate == "stacks":
        if not jobs or jobs[0]["kind"] != "select":
            raise RunError("The stacks are confirmed once, after the dependency mapper.")
        known = {s["pattern"] for s in run.state["recommendations"]}
        unknown = [s for s in selection or [] if s not in known]
        if unknown:
            raise RunError(f"Not found in this repository: {', '.join(unknown)}. Found: {', '.join(sorted(known))}.")
        docs = list(documents or DEFAULT_DOCUMENTS)
        bad = [d for d in docs if d not in DOCUMENTS]
        if bad:
            raise RunError(f"Unknown document(s): {', '.join(bad)}. Choose from {', '.join(DOCUMENTS)}.")
        offer = run.state.get("screens_offer") or {}
        if "ui_screens" in docs and not offer.get("available"):
            raise RunError("UI Screens are not available for this repository: "
                           + (offer.get("reason") or "no renderable UI was found."))
        chosen = set(selection or [])
        run.state.update({"selection": [s["pattern"] for s in run.state["recommendations"] if s["pattern"] in chosen],
                          "documents": docs, "current_step": None})
        run.state["jobs"] = [{"kind": "computed"}, {"kind": "strategy"}] + jobs[1:]
        run.save()
        return (f"Documenting {len(run.state['selection'])} stack(s); producing {', '.join(docs)}. The "
                "reverse-engineering strategy options come next.")
    if gate == "strategy":
        if not jobs or jobs[0]["kind"] != "strategy":
            raise RunError("The strategy is chosen once, after the stacks are confirmed.")
        if not selection or len(selection) != 1:
            raise RunError("Choose exactly one strategy id.")
        try:
            chosen = re_strategy.get(selection[0], run.state.get("strategy_options") or [])
        except ValueError as exc:
            raise RunError(str(exc))
        run.state.update({"strategy": chosen["id"], "current_step": None})
        run.state["jobs"] = _plan_jobs(run) + jobs[1:]
        _write(_d(run, "strategy.md"), re_strategy.to_markdown(run.state["strategy_options"])
               + f"\n**Chosen:** {chosen['name']} (`{chosen['id']}`).\n")
        run.save()
        return f"Strategy: {chosen['name']}."
    if gate == "documents":
        if not jobs or jobs[0]["kind"] != "review":
            raise RunError("Nothing is waiting for review.")
        run.state["jobs"] = jobs[1:]
        run.state["current_step"] = None
        run.save()
        return "Documents confirmed."
    raise RunError("Discovery gates: `stacks` (after the mapper), `strategy` (before reverse engineering) and "
                   "`documents` (the final review).")


def refine(run: Run, gate: str, feedback: str) -> str:
    """Re-run one writer from the stored evidence, without reading the code again."""
    jobs = run.state.get("jobs") or []
    if not jobs or jobs[0]["kind"] != "review":
        raise RunError("Refine applies once the documents are waiting for review.")
    target = {"brd": "po_brd", "technical_spec": "ea_spec", "test_inventory": "ea_spec", "setup": "setup"}.get(gate)
    if not target:
        raise RunError("Refine the `brd`, the `technical_spec`, the `test_inventory` or the `setup` guide.")
    run.state["feedback"] = {"target": target, "text": feedback}
    new = [{"kind": "writer", "writer": target}]
    if target == "ea_spec" and "technical_spec" in _documents(run):
        new.append({"kind": "writer", "writer": "ea_diagrams"})
    run.state["jobs"] = new + [{"kind": "assemble"}, {"kind": "review"}] + jobs[1:]
    run.state["current_step"] = None
    run.save()
    return f"The {gate} will be rewritten with this feedback — call next_step."


def _strategy(run: Run) -> dict:
    sid = run.state.get("strategy") or re_strategy.STACK_BY_STACK
    return next((s for s in run.state.get("strategy_options") or [] if s["id"] == sid),
                {"id": sid, "passes": [], "name": sid})


def _plan_jobs(run: Run) -> list[dict]:
    """The work after the strategy is chosen (the computed sections already ran)."""
    docs = _documents(run)
    jobs: list[dict] = []
    if docs & {"brd", "technical_spec", "test_inventory", "setup", "tech_debt", "ui_pages"}:
        passes = _strategy(run)["passes"]
        if passes:
            jobs += [{"kind": "layer", "pass": p} for p in passes]
        else:
            jobs += [{"kind": "evidence", "stack": s["pattern"]} for s in _stacks(run)]
        jobs.append({"kind": "ground"})
        if "brd" in docs and config.RULES_EXTRACTION == "on":
            jobs.append({"kind": "rules_prepare"})
    if "ui_screens" in docs:
        jobs.append({"kind": "screens"})
    if "tech_debt" in docs:
        jobs.append({"kind": "health"})
    if "brd" in docs:
        jobs.append({"kind": "writer", "writer": "po_brd"})
    if docs & {"technical_spec", "test_inventory"}:
        jobs.append({"kind": "writer", "writer": "ea_spec"})
    if docs & {"technical_spec", "ui_pages"}:
        jobs.append({"kind": "ui_prepare"})
    if "technical_spec" in docs:
        jobs.append({"kind": "writer", "writer": "ea_diagrams"})
    if "setup" in docs:
        jobs.append({"kind": "writer", "writer": "setup"})
    jobs += [{"kind": "assemble"}, {"kind": "review"}]
    return jobs


# ── strategy ─────────────────────────────────────────────────────────────────

def _job_strategy(run: Run, job: dict, log: list[str]) -> dict:
    inv = json.loads(_computed(run, "interfaces.json") or "{}")
    ui_result = json.loads(_computed(run, "ui_contracts.json") or "{}")
    sysinv = json.loads(_computed(run, "system_inventory.json") or "{}")
    signals = re_strategy.signals_for(str(run.workspace), inv, ui_result, sysinv.get("database"))
    offered = re_strategy.options(_stacks(run), signals)
    run.state["strategy_options"] = offered
    run.state["strategy_signals"] = signals
    _write(_d(run, "strategy.md"), re_strategy.to_markdown(offered))
    rows = "\n".join(f"- `{s['id']}` — {s['name']}" + (" **(recommended)**" if s["recommended"] else "")
                      + ("" if s["available"] else " (not available)") for s in offered)
    return _step(run, "select-strategy", "ask_user", title="Choose the reverse-engineering strategy", text=(
        "Before any code is read, choose how this repository is reverse engineered. The options, with what each "
        f"does, when it fits and why one is recommended here, are in `.modernizer/discovery/strategy.md`:\n\n{rows}"
        f"\n\nComputed signals: {', '.join(f'{k} {v}' for k, v in signals.items() if v) or 'none'}.\n\n"
        "Show the user the options (read the file for the details) and ask which to use, then call `confirm` with "
        "gate=`strategy` and `selection` = [the strategy id]."))


# ── layered passes ───────────────────────────────────────────────────────────

def _layer_batches(run: Run, pass_id: str) -> list[dict]:
    ws = str(run.workspace)
    inv = json.loads(_computed(run, "interfaces.json") or "{}")
    ui_result = json.loads(_computed(run, "ui_contracts.json") or "{}")
    sysinv = json.loads(_computed(run, "system_inventory.json") or "{}")
    layer_stacks = [s for s in _stacks(run) if re_strategy.LAYER_OF_KIND.get(s.get("kind", "")) == pass_id]
    files = sorted({f for s in layer_stacks for f in (stack_files(ws, s) or [])})
    return re_strategy.pass_batches(pass_id, files, inv, ui_result, sysinv.get("database") or {}, ws,
                                    config.UI_CONTRACTS_BATCH_ELEMENTS, config.UI_CONTRACTS_BATCH_CHARS,
                                    config.DISCOVERY_UNIT_MAX_FILES)


def _job_layer(run: Run, job: dict, log: list[str]) -> dict | None:
    pass_id = job["pass"]
    spec = re_strategy.PASSES[pass_id]
    if "batches" not in job:
        batches = _layer_batches(run, pass_id)
        for i, b in enumerate(batches, 1):
            _write(_d(run, "layers", pass_id, f"request-{i:04d}.md"), f"# {spec.label}: {b['title']}\n\n{b['request']}")
        job.update({"batches": [b["title"] for b in batches], "done": 0})
        log.append(f"{spec.label}: {len(batches)} batch(es) to trace.")
        run.save()
        if not batches:
            _write(_d(run, "evidence", f"{pass_id}.md"), re_strategy.empty_pass_pack(pass_id))
            return None
    i = job["done"]
    request = _d(run, "layers", pass_id, f"request-{i + 1:04d}.md")
    sid = f"layer-{pass_id}-{i + 1}"
    q = (f"Activate the `{spec.skill}` skill and execute it on the request in `{run.rel(request)}` (read the whole "
         f"file). {spec.summary} Explore the repository with read_file / glob / grep_search / list_directory (the "
         "workspace root; ignore `.modernizer/`). Do not assume any file contents you have not read. Describe the "
         "system as it is; record debt and dead code as observed facts in their own section."
         + _output_rule(sid, "Evidence Pack, in the thirteen sections the skill specifies"))
    return _sub(run, sid, ANALYST, q, f"{spec.label}: {job['batches'][i]}", "layer")


def _done_layer(run: Run, job: dict, output: str) -> str:
    pass_id = job["pass"]
    spec = re_strategy.PASSES[pass_id]
    i = job["done"]
    per_unit = min(config.RE_FINDINGS_MAX_CHARS * 2, max(config.RE_SYNTHESIS_MAX_CHARS, 2) // 2)
    _write(_d(run, "layers", pass_id, f"pack-{i + 1:04d}.md"),
           clip_findings(output, per_unit, f"{spec.label}, batch {i + 1}"))
    job["done"] = i + 1
    if job["done"] < len(job["batches"]):
        _push_front(run, job)
        return f"{spec.label}: batch {i + 1}/{len(job['batches'])} recorded."
    text = "\n\n".join(_read(_d(run, "layers", pass_id, f"pack-{n + 1:04d}.md")) for n in range(len(job["batches"])))
    text = evidence_pack.assign_ids(text, pass_id)
    _write(_d(run, "evidence", f"{pass_id}.md"), text)
    return f"{spec.label}: {len(evidence_pack.ids(text))} numbered evidence item(s)."


# ── tech debt and dead code ──────────────────────────────────────────────────

def _job_health(run: Run, job: dict, log: list[str]) -> None:
    ui_result = json.loads(_computed(run, "ui_contracts.json") or "{}")
    sysinv = json.loads(_computed(run, "system_inventory.json") or "{}")
    found = code_health.scan(str(run.workspace), ui_result, sysinv.get("database"), sysinv.get("observability"),
                             sysinv.get("security"))
    observations = re_strategy.debt_observations(_packs(run))
    _write(_d(run, "tech_debt.md"), code_health.to_markdown(found, observations, TITLE, _strategy(run)["name"]))
    log.append(f"Tech debt & dead code: {len(found['dead'])} dead-code candidate(s), {len(found['debt'])} debt "
               f"finding(s), {len(observations)} observation(s) from the passes.")


# ── evidence ─────────────────────────────────────────────────────────────────

def _job_evidence(run: Run, job: dict, log: list[str]) -> dict | None:
    stack_id = job["stack"]
    info = next(s for s in run.state["recommendations"] if s["pattern"] == stack_id)
    label = _label(run, stack_id)
    reference = info.get("reference") or stack_detector.reference_for(stack_id, info.get("kind", ""))
    if "units" not in job:
        files = None if stack_id in stack_detector.DEDICATED_RUNNERS else stack_files(str(run.workspace), info)
        job["units"] = file_units(files, config.DISCOVERY_UNIT_MAX_FILES) \
            if files and len(files) > config.DISCOVERY_CHUNK_MIN_FILES else []
        job["done"] = 0
        if job["units"]:
            log.append(f"{label}: {len(files):,} files, gathered in {len(job['units'])} units of at most "
                       f"{config.DISCOVERY_UNIT_MAX_FILES} files.")
        run.save()
    no_advice = ("Describe only what the repository contains — no migration, upgrade, modernisation, "
                 "target-version or other change suggestions of any kind.")
    if job["units"]:
        i = job["done"]
        unit = job["units"][i]
        sid = f"evidence-{evidence_pack.slug(stack_id)}-unit-{i + 1}"
        q = (f"Activate the `stack-discovery-unit` skill (and `stack-discovery-re` for its checklist "
             f"`references/{reference}`) and execute it for the unit below. Read every listed file with read_file.\n\n"
             f"## Stack\n{label} (id `{stack_id}`, kind {info.get('kind') or 'unspecified'})\n\n"
             f"## Unit {i + 1}/{len(job['units'])}: {unit_label(unit)}\nRead every one of these {len(unit)} files:\n"
             + "\n".join(f"- `{f}`" for f in unit) + f"\n\n{no_advice}" + _output_rule(sid, "Evidence Pack for this unit"))
        return _sub(run, sid, ANALYST, q, f"Evidence: {label}, unit {i + 1}/{len(job['units'])}", "evidence")
    sid = f"evidence-{evidence_pack.slug(stack_id)}"
    cited = "\n".join(f"- {e}" for e in info.get("evidence", [])) or "- (none recorded)"
    if stack_id in stack_detector.DEDICATED_RUNNERS:
        skill = stack_detector.DEDICATED_RUNNERS[stack_id][0] + "-re"
        lead = (f"Activate the `{skill}` skill and execute it on this repository. Produce the Analysis, BRD, Technical "
                "Specification and Existing Test Inventory sections with the exact SECTION markers the skill specifies.")
    else:
        lead = (f"Activate the `stack-discovery-re` skill for the stack below and read its reference checklist "
                f"`references/{reference}`. Return the skill's Evidence Pack — evidence only, no documents.")
    q = (f"{lead} Explore the repository with read_file / glob / grep_search / list_directory, starting from the "
         "evidence paths below. Do not assume any file contents you have not read.\n\n"
         f"## Stack\n{label} (id `{stack_id}`, kind {info.get('kind') or 'unspecified'})\n\n"
         f"## Evidence that identified it\n{cited}\n\nConfine yourself to this stack — other stacks in this repository "
         f"are covered separately — but record where it connects to them. {no_advice}"
         + _output_rule(sid, "Evidence Pack"))
    return _sub(run, sid, ANALYST, q, f"Evidence: {label}", "evidence")


def _done_evidence(run: Run, job: dict, output: str) -> str:
    stack_id = job["stack"]
    label = _label(run, stack_id)
    if job["units"]:
        i = job["done"]
        per_unit = min(config.RE_FINDINGS_MAX_CHARS, max(config.RE_SYNTHESIS_MAX_CHARS, 2) // 2)
        _write(_d(run, "evidence", "units", f"{evidence_pack.slug(stack_id)}-{i + 1:04d}.md"),
               clip_findings(output, per_unit, f"{label} unit {i + 1} ({unit_label(job['units'][i])})"))
        job["done"] = i + 1
        if job["done"] < len(job["units"]):
            _push_front(run, job)          # more units of this stack
            return f"Unit {i + 1}/{len(job['units'])} of {label} recorded."
        output = "\n\n".join(_read(_d(run, "evidence", "units", f"{evidence_pack.slug(stack_id)}-{n + 1:04d}.md"))
                             for n in range(len(job["units"])))
    text = evidence_pack.assign_ids(output, stack_id)
    _write(_d(run, "evidence", f"{evidence_pack.slug(stack_id)}.md"), text)
    return f"Evidence Pack for {label}: {len(evidence_pack.ids(text))} numbered item(s)."


def _pack_ids(run: Run) -> list[tuple[str, str]]:
    """(pack id, label): one per layer pass for a layered strategy, else one per stack."""
    passes = _strategy(run)["passes"]
    if passes:
        return [(p, re_strategy.PASSES[p].label) for p in passes]
    return [(s["pattern"], _label(run, s["pattern"])) for s in _stacks(run)]


def _packs(run: Run, grounded: bool = True) -> list[tuple[str, str, str]]:
    folder = "grounded" if grounded else "evidence"
    out = []
    for pid, label in _pack_ids(run):
        text = _read(_d(run, folder, f"{evidence_pack.slug(pid)}.md"))
        if text:
            out.append((pid, label, text))
    return out


def _job_ground(run: Run, job: dict, log: list[str]) -> None:
    """Only evidence traceable to the repository reaches the writers."""
    ws = str(run.workspace)
    files = grounding.files_index(ws)
    withheld = []
    for stack_id, _label_, text in _packs(run, grounded=False):
        kept, rejected = grounding.verify_pack(text, ws, files)
        _write(_d(run, "grounded", f"{evidence_pack.slug(stack_id)}.md"), kept)
        withheld += rejected
    _write(_d(run, "withheld.json"), json.dumps(withheld))
    if withheld:
        log.append(f"Grounding: withheld {len(withheld)} evidence item(s) not traceable to the code.")


# ── business-rules ledger ────────────────────────────────────────────────────

def _rules_store(run: Run) -> Path:
    return _d(run, "rules", "state.pkl")


def _rules_load(run: Run) -> dict:
    with _rules_store(run).open("rb") as fh:
        return pickle.load(fh)


def _rules_save(run: Run, data: dict) -> None:
    with _rules_store(run).open("wb") as fh:
        pickle.dump(data, fh)


def _job_rules_prepare(run: Run, job: dict, log: list[str]) -> None:
    ws = str(run.workspace)
    languages = rule_languages(_stacks(run))
    scanned = rule_candidates.scan(ws, config.RULES_CANDIDATE_MAX_LINES)
    candidates = [c for c in scanned.candidates if c.language in languages]
    ledger = rules_ledger.new_ledger(candidates)
    pending = [c for c in candidates if c.status == "pending"]
    batches = rules_ledger.batches(pending, config.RULES_BATCH_MAX_CANDIDATES, config.RULES_BATCH_MAX_CHARS)
    _rules_save(run, {"scan": scanned, "candidates": {c.id: c for c in candidates}, "ledger": ledger,
                      "excluded": len(scanned.candidates) - len(candidates), "repo_text": grounding.repo_text(ws)})
    log.append(f"Business rules: {len(candidates):,} candidates found by parsing ({len(candidates) - len(pending):,} "
               f"technical without the model); {len(pending):,} to classify in {len(batches):,} batch(es).")
    jobs = [{"kind": "rules_batch", "n": i + 1, "total": len(batches), "ids": [c.id for c in b], "mode": "classify",
             "attempt": 0} for i, b in enumerate(batches)]
    run.state["jobs"] = run.state["jobs"][:1] + jobs + [{"kind": "rules_finalize"}] + run.state["jobs"][1:]


def _job_rules_batch(run: Run, job: dict, log: list[str]) -> dict:
    data = _rules_load(run)
    batch = [data["candidates"][i] for i in job["ids"]]
    if job["mode"] == "account":
        text = rules_ledger.render_batch(batch, account=job["extra"])
        ask = "Account for every listed decision point."
    elif job["mode"] == "reword":
        text = rules_ledger.render_batch(batch, job["extra"])
        ask = "Restate the rules of these candidates in plain English."
    else:
        text = rules_ledger.render_batch(batch)
        ask = "Classify every candidate and extract its business rules."
    tag = f"{job['n']:04d}-{job['mode']}-{job['attempt']}"
    request = _write(_d(run, "rules", f"batch-{tag}.md"), "## Candidates\n" + text)
    sid = f"rules-{tag}"
    q = (f"Activate the `business-rules-extract` skill and execute it on the candidates in `{run.rel(request)}` "
         f"(read the whole file). {ask} The file holds the exact numbered source of every candidate — read nothing else."
         + _output_rule(sid, "answer in the exact format the skill specifies"))
    return _sub(run, sid, WRITER, q, f"Business rules: batch {job['n']}/{job['total']} ({job['mode']})", "rules")


def _done_rules(run: Run, job: dict, output: str) -> str:
    data = _rules_load(run)
    ledger, repo_text = data["ledger"], data["repo_text"]
    batch = [data["candidates"][i] for i in job["ids"]]
    follow: list[dict] = []
    base = {k: job[k] for k in ("kind", "n", "total")}
    if job["mode"] == "classify":
        missing = rules_ledger.apply_answer(batch, rules_ledger.parse_answer(output), ledger, repo_text=repo_text)
        if missing and job["attempt"] == 0:
            follow.append({**base, "ids": [c.id for c in missing], "mode": "classify", "attempt": 1,
                           "original": job.get("original", job["ids"])})
        else:
            if missing:
                rules_ledger.mark_unclassified(missing, ledger, "the agent's answer did not cover it (asked twice)")
            original = [data["candidates"][i] for i in job.get("original", job["ids"])]
            open_points = rules_ledger.unaccounted(original, ledger)
            if open_points:
                follow.append({**base, "ids": [c.id for c in original if c.id in open_points], "mode": "account",
                               "attempt": 0, "extra": open_points, "original": job.get("original", job["ids"])})
            else:
                follow += _reword_job(base, original, ledger, job)
    elif job["mode"] == "account":
        rules_ledger.apply_answer(batch, rules_ledger.parse_answer(output), ledger, repo_text=repo_text)
        original = [data["candidates"][i] for i in job.get("original", job["ids"])]
        follow += _reword_job(base, original, ledger, job)
    else:
        rules_ledger.apply_answer(batch, rules_ledger.parse_answer(output), ledger, replace=True, repo_text=repo_text)
    _rules_save(run, data)
    if follow:
        _push_front(run, *follow)
    return f"Business rules batch {job['n']}/{job['total']} ({job['mode']}) applied."


def _reword_job(base: dict, original: list, ledger: dict, job: dict) -> list[dict]:
    reword = rules_ledger.needs_rewording(original, ledger)
    if not reword:
        return []
    return [{**base, "ids": [c.id for c in original if c.id in reword], "mode": "reword", "attempt": 0,
             "extra": reword, "original": job.get("original", job["ids"])}]


def _job_rules_finalize(run: Run, job: dict, log: list[str]) -> None:
    data = _rules_load(run)
    ledger, scanned = data["ledger"], data["scan"]
    rules_ledger.finalize(ledger, str(run.workspace), scanned.test_files)
    cov = rules_ledger.coverage(ledger, {
        "languages": scanned.files_by_language, "unparsed": scanned.unparsed, "parse_errors": scanned.parse_errors,
        "excluded": data["excluded"], "parser_error": scanned.tree_sitter_error})
    markdown = (rules_ledger.catalog_markdown(ledger, config.RULES_CATALOG_MAX_IN_DOCUMENT)
                + "\n\n" + rules_ledger.coverage_markdown(cov) + "\n\n" + rules_ledger.decisions_markdown(ledger))
    try:
        markdown += "\n\n" + external_rules.to_markdown(external_rules.scan(str(run.workspace)))
    except Exception as exc:                                  # noqa: BLE001 — a heuristic section, reported
        markdown += f"\n\n> External rules scan failed: {type(exc).__name__}: {exc}"
    ledger.pop("raw_rules", None)
    _write(_d(run, "rules", "ledger.json"), json.dumps(ledger))
    _write(_d(run, "rules", "rules.md"), markdown)
    log.append(f"Business rules: {cov['candidates']} candidates, {cov['rules']} rules.")


def _ledger(run: Run) -> dict | None:
    path = _d(run, "rules", "ledger.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


# ── computed sections, screens ───────────────────────────────────────────────

def _job_screens(run: Run, job: dict, log: list[str]) -> None:
    ws = str(run.workspace)
    out_dir = _d(run, "screens", "x").parent
    try:
        manifest = ui_screens.capture_in_own_loop(ws, interfaces.scan(ws), str(out_dir))
    except Exception as exc:                                  # noqa: BLE001 — reported in the document
        manifest = {"screens": [], "not_rendered": [], "pages": 0, "failed": True,
                    "notes": [f"Screenshots could not be produced: {ui_screens.describe(exc)[:300]}"]}
    _write(_d(run, "screens.json"), json.dumps(manifest))
    log.append(f"UI screens: {len(manifest['screens'])} screen(s), {len(manifest['not_rendered'])} not rendered.")


def _job_computed(run: Run, job: dict, log: list[str]) -> None:
    ws = str(run.workspace)
    docs = _documents(run)
    inv = interfaces.scan(ws)
    _write(_d(run, "computed", "interfaces.json"), json.dumps(inv))
    _write(_d(run, "computed", "interfaces.md"), interfaces.to_markdown(inv))
    _write(_d(run, "computed", "config_matrix.md"), config_matrix.to_markdown(config_matrix.scan(ws), None) or "")
    sysinv = system_inventory.scan(ws)
    _write(_d(run, "computed", "system_inventory.json"), json.dumps(sysinv))
    _write(_d(run, "computed", "system_inventory.md"), system_inventory.to_markdown(sysinv))
    _write(_d(run, "computed", "setup_facts.md"), setup_facts.to_markdown(setup_facts.scan(ws)))
    ui_result = {"screens": [], "contracts": [], "unmatched": [], "uncalled": [], "pages": []}
    pages_md, covered = "", {}
    try:
        # Needed by every document: the strategy signals, the UI pass, the OpenAPI file, the debt scan.
        ui_result = ui_contracts.scan(ws, inv)
    except Exception as exc:                                  # noqa: BLE001 — the documents do not depend on it
        log.append(f"UI contracts scan failed: {type(exc).__name__}: {exc}")
    if docs & {"technical_spec", "ui_pages"}:
        try:
            pages = ui_pages.scan(ws, inv, ui_result)
            pages_md, covered = ui_pages.to_markdown(pages), ui_pages.covered(pages)
        except Exception as exc:                              # noqa: BLE001
            log.append(f"UI pages scan failed: {type(exc).__name__}: {exc}")
    _write(_d(run, "computed", "ui_contracts.json"), json.dumps(ui_result))
    _write(_d(run, "computed", "endpoint_contracts.md"), ui_contracts.contracts_markdown(ui_result))
    _write(_d(run, "computed", "ui_pages.md"), pages_md)
    _write(_d(run, "computed", "ui_to_backend.md"), ui_contracts.to_markdown(ui_result, covered))
    tests = existing_tests.scan(ws) if "test_inventory" in docs else []
    _write(_d(run, "computed", "test_files.md"), existing_tests.to_markdown(tests))
    _write(_d(run, "computed", "modules.json"), json.dumps(module_names(ws)))
    log.append(f"Computed sections: {len(inv.get('endpoints', []))} endpoint(s), "
               f"{len(ui_contracts.ids(ui_result))} UI control(s), {len(tests)} test file(s).")


def _computed(run: Run, name: str) -> str:
    return _read(_d(run, "computed", name)).strip()


def _facts(run: Run) -> arch_diagrams.Facts:
    inv = json.loads(_computed(run, "interfaces.json") or "{}")
    ui_result = json.loads(_computed(run, "ui_contracts.json") or "{}")
    return diagram_facts(list(run.state.get("selection") or []), inv.get("endpoints", []),
                         json.loads(_computed(run, "modules.json") or "[]"), _computed(run, "config_matrix.md"),
                         ui_result, "\n".join([_read(_d(run, "stack_inventory.md")), _computed(run, "interfaces.md"),
                                               _computed(run, "endpoint_contracts.md"),
                                               _computed(run, "ui_to_backend.md"), _computed(run, "config_matrix.md")]))


# ── writers ──────────────────────────────────────────────────────────────────

_WRITER_SKILLS = {"po_brd": "as-is-brd", "ea_spec": "current-state-architecture", "ea_diagrams": "architecture-diagrams",
                  "setup": "setup-guide"}
_WRITER_TITLES = {"po_brd": "Product Owner: as-is BRD", "ea_spec": "Enterprise Architect: Technical Specification",
                  "ea_diagrams": "Enterprise Architect: architecture diagrams",
                  "setup": "Lead engineer: Setup & Deployment guide"}
_SETUP_SECTIONS = ("Components", "Integrations & Configuration", "Security", "Logging, Monitoring & Auditing",
                   "Tests", "Limitations")


def _writer_request(run: Run, writer: str, retry_note: str = "") -> str:
    packs = _packs(run)
    stack_info = {s["pattern"]: s for s in run.state["recommendations"]}
    stacks = "\n".join(f"- {_label(run, s['pattern'])} (id `{s['pattern']}`, kind "
                       f"{stack_info.get(s['pattern'], {}).get('kind') or 'unspecified'})" for s in _stacks(run))
    strategy = _strategy(run)
    if strategy["passes"]:
        stacks += ("\n\n## How the evidence was gathered\nStrategy: " + strategy["name"] + ". The evidence is "
                   "organised by pass — " + "; ".join(f"{re_strategy.PASSES[p].label}: {re_strategy.PASSES[p].summary}"
                                                     for p in strategy["passes"])
                   + " Use the Flow Traces for end-to-end flows.")
    docs = _documents(run)
    if writer == "po_brd":
        extra = ("## Business-Rules Catalog (brief)\n"
                 + evidence_pack.rules_index(_ledger(run), WRITER_RULES_INDEX_CHARS) + "\n\n")
        sections = evidence_pack.PO_SECTIONS
    elif writer == "ea_spec":
        extra = ("" if "technical_spec" in docs else
                 "## Only the Existing Test Inventory is wanted\nThe reviewer chose not to generate the Technical "
                 "Specification: under its marker write only \"Not requested.\" and put your work into the Test "
                 "Inventory.\n\n")
        config_md = _computed(run, "config_matrix.md")
        extra += ("## Repository Facts (computed by the pipeline)\nThe Interface & Job Inventory, Endpoint Contracts, "
                  "UI-to-Backend Contracts, Configuration Matrix and Test Files are printed in the specification in "
                  "full; they are given here for your overview — do not re-list them.\n\n"
                  + for_writer(_read(_d(run, "stack_inventory.md")), 60000) + for_writer(_computed(run, "interfaces.md"), 40000)
                  + (for_writer(config_md, 30000) + "Use the matrix for per-environment behaviour; never print a value "
                     "it shows as redacted.\n\n" if config_md else "")
                  + for_writer(_computed(run, "ui_to_backend.md"), 30000)
                  + for_writer(_computed(run, "system_inventory.md"), 120000)
                  + for_writer(_computed(run, "test_files.md"), 30000))
        sections = evidence_pack.EA_SECTIONS
    elif writer == "setup":
        extra = ("## Repository Facts (computed by the pipeline)\n"
                 + for_writer(_computed(run, "setup_facts.md"), 80000)
                 + for_writer(_computed(run, "system_inventory.md"), 60000)
                 + for_writer(_computed(run, "config_matrix.md"), 30000))
        sections = _SETUP_SECTIONS
    else:
        extra = ("## Repository Facts (computed by the pipeline)\n" + for_writer(_read(_d(run, "stack_inventory.md")), 40000)
                 + for_writer(_computed(run, "interfaces.md"), 40000) + for_writer(_computed(run, "ui_to_backend.md"), 20000)
                 + for_writer(_computed(run, "config_matrix.md"), 15000)
                 + for_writer(_computed(run, "system_inventory.md"), 40000) + for_writer(diagram_refs(_facts(run)), 40000)
                 + retry_note)
        sections = evidence_pack.EA_SECTIONS
    request = f"## Confirmed Stacks\n{stacks}\n\n{extra}"
    fb = run.state.get("feedback") or {}
    if fb.get("target") == writer or (writer == "ea_diagrams" and fb.get("target") == "ea_spec"):
        previous = _read(_d(run, "writers", f"{writer}.md"))
        if previous:
            request += f"## Your Previous Document (revise it)\n{previous[:30000]}\n\n"
        request += f"## Reviewer Feedback\n{fb['text']}\n\n"
    pieces = evidence_pack.view(packs, sections)
    budget = max(config.RE_SYNTHESIS_MAX_CHARS, 2)
    pieces = [p for piece in pieces for p in evidence_pack.split_piece(piece, max(budget // 2, 1))]
    view = "\n\n---\n\n".join(pieces)
    if len(view) > budget:
        # The web pipeline merges oversize evidence with an agent; here every item stays and
        # the request is longer — read_file pages it. Stated so a reviewer knows.
        request += (f"> Note: the evidence below is {len(view):,} characters (over the {budget:,} one-request budget); "
                    "read the whole file in pages.\n\n")
    return request + "## Evidence\n" + view


def _job_writer(run: Run, job: dict, log: list[str]) -> dict:
    writer = job["writer"]
    skill = _WRITER_SKILLS[writer]
    request = _write(_d(run, "requests", f"{writer}.md"), _writer_request(run, writer, job.get("retry_note", "")))
    sid = writer + ("-retry" if job.get("retry_note") else "")
    what = {"po_brd": "BRD (markdown)", "ea_spec": "Technical Specification and Test Inventory, as the skill specifies",
            "ea_diagrams": "JSON object only", "setup": "Setup & Deployment guide (markdown)"}[writer]
    q = (f"Activate the `{skill}` skill and execute it on the request in `{run.rel(request)}` (read the whole file; it "
         "may take several read_file calls). Write the document from the evidence in that file — do not read the "
         "repository's code." + _output_rule(sid, what))
    return _sub(run, sid, WRITER, q, _WRITER_TITLES[writer], "writer")


def _done_writer(run: Run, job: dict, output: str) -> str:
    writer = job["writer"]
    if writer == "ea_diagrams" and not job.get("retry_note"):
        raw, problem = arch_diagrams.parse(output)
        if problem or not raw:
            _push_front(run, {**job, "retry_note": f"## Your previous answer could not be used\n"
                                                   f"{problem or 'it declared no diagrams'}; answer with the JSON "
                                                   "object only.\n\n"})
            return "The diagrams answer could not be parsed — asking once more."
    _write(_d(run, "writers", f"{writer}.md"), output)
    return f"{_WRITER_TITLES[writer]} saved."


def _job_ui_prepare(run: Run, job: dict, log: list[str]) -> None:
    ui_result = json.loads(_computed(run, "ui_contracts.json") or "{}")
    if not ui_result.get("screens"):
        _write(_d(run, "writers", "ea_ui.json"), json.dumps({"intros": {}, "blocks": {}}))
        return
    batches = ui_contracts.batches(ui_result, config.UI_CONTRACTS_BATCH_ELEMENTS, config.UI_CONTRACTS_BATCH_CHARS)
    _write(_d(run, "writers", "ea_ui.json"), json.dumps({"intros": {}, "blocks": {}}))
    log.append(f"UI interaction contracts: {len(ui_contracts.ids(ui_result))} controls in {len(batches)} batch(es).")
    jobs = [{"kind": "ui_batch", "n": i + 1, "total": len(batches), "ids": ui_contracts.batch_ids(b), "attempt": 0}
            for i, b in enumerate(batches)]
    run.state["jobs"] = run.state["jobs"][:1] + jobs + run.state["jobs"][1:]


def _job_ui_batch(run: Run, job: dict, log: list[str]) -> dict:
    ui_result = json.loads(_computed(run, "ui_contracts.json"))
    wanted = set(job["ids"])
    batch = [dict(screen, elements=[e for e in screen["elements"] if e["id"] in wanted])
             for screen in ui_result.get("screens", [])]
    batch = [s for s in batch if s["elements"]]
    evidence: dict[str, str] = {}
    for _, _, text in _packs(run):
        evidence.update(evidence_pack.items(text))
    names = ui_contracts.batch_names(batch)
    related, size = [], 0
    for eid, text in evidence.items():
        if any(n in text for n in names) and size + len(text) <= config.UI_CONTRACTS_EVIDENCE_CHARS:
            related.append(f"- [{eid}] {text}")
            size += len(text)
    ids = ui_contracts.batch_ids(batch)
    request = (f"## Batch {job['n']} of {job['total']}\nDescribe every one of these {len(ids)} controls: {', '.join(ids)}.\n\n"
               + ui_contracts.batch_request(batch, ui_result)
               + "\n\n## Evidence\n" + ("\n".join(related) or "No evidence item names these screens."))
    path = _write(_d(run, "requests", f"ea_ui-{job['n']:03d}-{job['attempt']}.md"), request)
    sid = f"ea-ui-{job['n']:03d}-{job['attempt']}"
    q = (f"Activate the `ui-interaction-contracts` skill and execute it on the request in `{run.rel(path)}` (read the "
         "whole file). Describe every control it lists — do not read the repository's code."
         + _output_rule(sid, "answer in the format the skill specifies"))
    return _sub(run, sid, WRITER, q, f"UI interaction contracts: batch {job['n']}/{job['total']}", "ui")


def _done_ui(run: Run, job: dict, output: str) -> str:
    ui_result = json.loads(_computed(run, "ui_contracts.json"))
    store = json.loads(_read(_d(run, "writers", "ea_ui.json")) or '{"intros": {}, "blocks": {}}')
    text = current_state_only(output, f"UI interaction contracts (batch {job['n']})", _keep(run))
    intros, blocks = ui_contracts.parse_answer(text, ui_result)
    for k, v in intros.items():
        store["intros"].setdefault(k, v)
    for k, v in blocks.items():
        if k in job["ids"]:
            store["blocks"].setdefault(k, v)
    _write(_d(run, "writers", "ea_ui.json"), json.dumps(store))
    missing = [i for i in job["ids"] if i not in store["blocks"]]
    if missing and job["attempt"] == 0:
        _push_front(run, {**job, "ids": missing, "attempt": 1})
        return f"Batch {job['n']}: {len(missing)} control(s) not described — asking once more."
    return f"UI contracts batch {job['n']}/{job['total']} recorded."


# ── assembly ─────────────────────────────────────────────────────────────────

def _job_assemble(run: Run, job: dict, log: list[str]) -> None:
    """main._run_discovery_documents' assembly: scrub, ground, place the computed
    sections, draw the diagrams, check the citations, write the documents."""
    ws = str(run.workspace)
    keep = _keep(run)
    docs = _documents(run)
    packs = _packs(run)
    evidence_ids = set().union(*(evidence_pack.ids(t) for _, _, t in packs)) if packs else set()
    ledger = _ledger(run)
    rule_ids = {r["id"] for r in rules_ledger.verified_rules(ledger)}
    ui_result = json.loads(_computed(run, "ui_contracts.json") or "{}") or {"screens": []}
    endpoint_contracts_md, contracts_md = _computed(run, "endpoint_contracts.md"), _computed(run, "ui_to_backend.md")
    inventory_md, pages_md = _computed(run, "interfaces.md"), _computed(run, "ui_pages.md")
    config_md, test_files_md = _computed(run, "config_matrix.md"), _computed(run, "test_files.md")
    system_md = _computed(run, "system_inventory.md")

    po_brd = current_state_only(_read(_d(run, "writers", "po_brd.md")), "BRD (Product Owner)", keep)
    spec, tests = evidence_pack.split_spec(_read(_d(run, "writers", "ea_spec.md")))
    ea_spec = current_state_only(spec, "Technical Specification (Enterprise Architect)", keep) \
        if "technical_spec" in docs else ""
    ea_tests = current_state_only(tests, "Test Inventory (Enterprise Architect)", keep)
    ea_diagrams = current_state_only(_read(_d(run, "writers", "ea_diagrams.md")), "Architecture diagrams", keep)
    ea_ui = json.loads(_read(_d(run, "writers", "ea_ui.json")) or "{}")

    inventory = current_state_only(_read(_d(run, "stack_inventory.md")), "inventory", keep)
    evidence_text: dict[str, str] = {}
    for _, _, text in packs:
        evidence_text.update(evidence_pack.items(text))
    rules_text = {r["id"]: " ".join([r["statement"], *(s for key in rules_ledger.SCENARIO_FIELDS
                                                      for s in r.get(key, []))])
                  for r in rules_ledger.verified_rules(ledger)}
    checked_brd, untraced = grounding.check_brd(po_brd, evidence_text, rules_text, {float(len(packs))}) \
        if po_brd else ("", [])
    spec_untraced: list = []
    ui_filled: list[str] = []
    elisions: list[str] = []
    ui_intros: dict[str, str] = {}
    ui_blocks: dict[str, str] = {}
    if ui_result.get("screens") and (ea_spec or ("ui_pages" in docs and ea_ui.get("blocks"))):
        raw_section, _ = ui_contracts.assemble(ui_result, ea_ui.get("intros", {}), ea_ui.get("blocks", {}), fill=False)
        raw_section, elisions = grounding.replace_elisions(raw_section, ELIDED_UI)
        raw_section, _tables = ui_contracts.strip_schema_tables(raw_section)
        checked_section, spec_untraced = grounding.check_ui_section(
            raw_section, contracts_md + "\n" + endpoint_contracts_md, set(ui_contracts.ids(ui_result)),
            ui_contracts.calls(ui_result), evidence_text, placeholder=False)
        intros, blocks = ui_contracts.parse_answer(checked_section, ui_result)
        ui_intros, ui_blocks = intros, blocks
        ui_section, ui_filled = ui_contracts.assemble(ui_result, intros, blocks)
        if ea_spec:
            ea_spec = plain_language.place_section(ea_spec, ui_section, ui_contracts.SECTION_HEADING,
                                                   before=SPEC_UI_CONTRACTS_BEFORE)
    facts = _facts(run)
    raw_diagrams, diagram_problem = arch_diagrams.parse(ea_diagrams)
    diagrams, diagram_rejected = arch_diagrams.validate(raw_diagrams, evidence_text, facts)
    if ea_diagrams and diagram_problem:
        diagram_rejected.append(("the architecture diagrams", diagram_problem))
    diagrams_dir = _d(run, "diagrams", "x").parent
    for old in diagrams_dir.glob("*.png"):
        old.unlink()
    arch_diagrams.render(diagrams, str(diagrams_dir))
    diagrams_md = arch_diagrams.to_markdown(diagrams, image_prefix="../../discovery/diagrams/")
    if ea_spec and diagrams_md:
        ea_spec = plain_language.place_section(ea_spec, diagrams_md, arch_diagrams.HEADING,
                                               before=SPEC_DIAGRAMS_BEFORE)
    ea_spec, cut = grounding.replace_elisions(ea_spec, ELIDED_SPEC)
    elisions += cut
    ea_tests, cut = grounding.replace_elisions(ea_tests, ELIDED_TESTS)
    elisions += cut
    business_brd, citations, _removed = plain_language.business_only(checked_brd) if checked_brd else ("", [], 0)
    check_md = ""
    if packs:
        if ledger:
            business_brd = plain_language.place_section(
                business_brd, rules_ledger.business_rules_markdown(ledger, config.RULES_CATALOG_MAX_IN_DOCUMENT),
                rules_ledger.BUSINESS_RULES_HEADING)
        parts = [business_brd]
        check_md = evidence_pack.check_markdown(evidence_pack.check(po_brd, evidence_ids, rule_ids),
                                                evidence_pack.check(ea_spec + "\n" + ea_tests, evidence_ids, rule_ids),
                                                evidence_ids, None, ui_filled if ui_result.get("screens") else None)
    elif docs & {"brd", "technical_spec", "test_inventory"}:
        parts = ["> **No stacks were documented.** Either nothing was detected, or every detected part of the "
                 "system was left out at the confirmation step."]
    else:
        parts = []
    brd = "\n\n---\n\n".join(p for p in parts if p) if "brd" in docs else ""
    withheld = json.loads(_read(_d(run, "withheld.json")) or "[]")
    evidence_md = evidence_pack.evidence_markdown(
        TITLE, inventory, citations, packs, _read(_d(run, "rules", "rules.md")), check_md, "",
        grounding.report_markdown([tuple(w) for w in withheld], ledger, untraced,
                                  spec_untraced if contracts_md else None, elisions,
                                  diagram_rejected if ea_diagrams else None))
    graphs = []
    for stack_id in run.state.get("selection") or []:
        label = _label(run, stack_id)
        graph_pattern = DISCOVERY_GRAPHS.get(stack_id)
        if graph_pattern:
            graph_json = json.dumps(dependency_graph.build_dependency_graph(ws, graph_pattern))
            section = inject_dependency_graph("", graph_json, stack_id, True).strip()
            if section:
                graphs.append(section.replace("## Dependency Graph & Build Order",
                                              f"## Dependency Graph & Build Order — {label}", 1))
    tech_spec = "\n\n".join(graphs + [md for md in (inventory_md, endpoint_contracts_md, contracts_md, pages_md,
                                                    config_md, system_md) if md] + ([ea_spec] if ea_spec else [])) \
        if "technical_spec" in docs else ""
    test_inventory = "\n\n".join(md for md in (test_files_md, ea_tests) if md) if "test_inventory" in docs else ""
    out = {"brd": brd, "technical_spec": tech_spec, "test_inventory": test_inventory, "evidence": evidence_md}
    manifest = _read(_d(run, "screens.json")) if "ui_screens" in docs else ""
    traced_pages = []
    if docs & {"ui_pages", "ui_screens"}:
        try:
            traced_pages = ui_page_traces.build(ws, ui_result)
        except Exception as exc:                              # noqa: BLE001 — the other documents do not depend on it
            log.append(f"UI pages document failed: {type(exc).__name__}: {exc}")
    if "ui_screens" in docs:
        out["ui_screens"] = ui_screens.to_markdown(json.loads(manifest), ledger,
                                                   image_prefix="../../discovery/screens/",
                                                   page_titles=ui_page_traces.page_order(traced_pages)) \
            if manifest else ""
    if "ui_pages" in docs:
        out["ui_pages"] = ui_page_traces.to_markdown(
            traced_pages, ui_result, ui_blocks, evidence_text,
            ui_page_traces.screenshot_index(json.loads(manifest) if manifest else None), run.workspace.name,
            pages_md, ui_intros) if any(not p["fragment"] for p in traced_pages) else ""
    for name, text in out.items():
        if text or name == "evidence":
            run.write_doc(name, text, "stack-discovery")
    log.append("Documents assembled: " + ", ".join(f"`{run.rel(run.doc_path(n, 'stack-discovery'))}`"
                                                   for n, t in out.items() if t))
    if untraced or spec_untraced or withheld or elisions:
        log.append(f"Grounding: {len(withheld)} evidence item(s) withheld, {len(untraced)} BRD and "
                   f"{len(spec_untraced)} UI statement(s) removed, {len(elisions)} abbreviated list(s) replaced — "
                   "details under Grounding Checks in evidence.md.")
    if "setup" in docs:
        setup_md = current_state_only(_read(_d(run, "writers", "setup.md")), "Setup & Deployment guide", keep)
        setup_md = setup_md or ("> The setup guide was not written; the computed facts follow.\n\n"
                                + _computed(run, "setup_facts.md"))
        run.write_doc("setup", setup_md.rstrip() + "\n\n---\n\n" + _computed(run, "setup_facts.md") + "\n",
                      "stack-discovery")
    if "openapi" in docs:
        settings = system_inventory._settings(system_inventory._files(Path(ws)))
        spec = openapi_spec.build(ui_result.get("contracts", []), f"{run.workspace.name} — as-is HTTP interface",
                                  servers=openapi_spec.servers_from_config(settings))
        _write(_d(run, "openapi.yaml"), openapi_spec.to_yaml(spec))
        _write(_d(run, "openapi.json"), openapi_spec.to_json(spec))
        log.append(f"OpenAPI 3.0: {len(spec['paths'])} path(s), {sum(len(v) for v in spec['paths'].values())} "
                   "operation(s).")
    if "tech_debt" in docs:
        run.write_doc("tech_debt", _read(_d(run, "tech_debt.md")), "stack-discovery")
    written = export_deliverables(run)
    log.append(f"Deliverables in `.modernizer/{DELIVERABLES_DIR}/`: " + ", ".join(written))
    run.state.pop("feedback", None)


def export_deliverables(run: Run) -> list[str]:
    """The final documents as separate files in `.modernizer/deliverables/`, with an index."""
    out = run.dir / DELIVERABLES_DIR
    out.mkdir(parents=True, exist_ok=True)
    docs = {d: run.read_doc(d, "stack-discovery").replace("../../discovery/", "../discovery/")
            for d in ("setup", "brd", "technical_spec", "test_inventory", "tech_debt", "ui_pages", "ui_screens",
                      "evidence")}
    spec_file = _d(run, "openapi.json")
    spec = json.loads(spec_file.read_text(encoding="utf-8")) if spec_file.is_file() else None
    files = deliverables.build(docs, spec, _read(_d(run, "strategy.md")), run.workspace.name, _strategy(run)["name"],
                               [f"{_label(run, s)} (`{s}`)" for s in run.state.get("selection") or []])
    for old in out.glob("*"):
        if old.is_file() and old.name not in files:
            old.unlink()
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    return list(files)


def _job_review(run: Run, job: dict, log: list[str]) -> dict:
    out = run.dir / DELIVERABLES_DIR
    docs = "\n".join(f"- `{run.rel(p)}`" for p in sorted(out.glob("*")) if p.is_file())
    return _step(run, "documents-review", "review_gate", title="Review the reverse-engineering deliverables", text=(
        f"Ask the user to review the deliverables (edit the sources under `.modernizer/docs/stack-discovery/` if "
        f"needed):\n{docs}\n\n(The code references behind the BRD — traceability, the "
        "rules catalog, coverage and the evidence check — are in "
        f"`{run.rel(run.doc_path('evidence', 'stack-discovery'))}`.)\n\nThen either `/modernize:approve` (calls "
        "`confirm` with gate=`documents`) or `/modernize:refine <brd|technical_spec|test_inventory|setup> <feedback>` "
        "(calls `refine`; only that document's writer runs again, from the stored evidence). "
        "`/modernize:export` writes Word copies."))


def _done_text(run: Run) -> str:
    out = run.dir / DELIVERABLES_DIR
    docs = "\n".join(f"- `{run.rel(p)}`" for p in sorted(out.glob("*")) if p.is_file())
    return f"Discovery is complete. Nothing in the repository was changed. Deliverables:\n{docs}"


_JOBS = {
    "mapper": _job_mapper, "select": _job_select, "evidence": _job_evidence, "ground": _job_ground,
    "rules_prepare": _job_rules_prepare, "rules_batch": _job_rules_batch, "rules_finalize": _job_rules_finalize,
    "screens": _job_screens, "computed": _job_computed, "writer": _job_writer, "ui_prepare": _job_ui_prepare,
    "ui_batch": _job_ui_batch, "assemble": _job_assemble, "review": _job_review, "strategy": _job_strategy,
    "layer": _job_layer, "health": _job_health,
}
_DONE = {"mapper": _done_mapper, "evidence": _done_evidence, "layer": _done_layer, "rules_batch": _done_rules,
         "writer": _done_writer,
         "ui_batch": _done_ui}
