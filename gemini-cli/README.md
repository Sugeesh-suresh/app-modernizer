# Stella Modernizer for Gemini CLI

Runs every Stella Modernizer pattern from a Gemini CLI session, with no Google ADK pipeline and no web
server. The skills, the deterministic checks and the human review gates are the same ones the web app uses.

| Web app (ADK) | Gemini CLI |
|---|---|
| ADK `LlmAgent` per role, wired in `agents/<pattern>/agents.py` | 7 role subagents in `agents/*.md` |
| `SkillToolset` loading `agents/skills/*/SKILL.md` | Gemini CLI skills: the same files, through the `skills` link |
| ADK `FunctionTool`s (`list_files`, `write_file`, `run_command`, validators, audit, ...) | Gemini's own read tools + the `modernizer` MCP server (`modernizer-backend/cli/mcp_server.py`), which calls the same Python functions |
| `main.py` orchestration + `SequentialAgent` / `LoopAgent` | `cli/pipeline.py` / `cli/discovery.py`: a state machine in `.modernizer/run.json` |
| ADK session state | `.modernizer/` in the repository (documents, plan, results) |
| Upload, review screens, SSE | `/modernize:*` commands; the documents are Markdown files you review in your editor |

## Install

Requirements: Node 20+ (for Gemini CLI), Python 3.10+, and the build tools of the pattern you run (JDK +
Maven/Gradle for the Java patterns, Node/npm for JSP → React).

```bash
node gemini-cli/install.mjs                 # Python env (modernizer-backend/.venv-cli) + skills link
gemini extensions link "$(pwd)/gemini-cli"  # once; use link, not install
```

`install.mjs --link` runs the second command for you. The extension has to be **linked**, not installed: it
runs the Python code and the skills in this repository, and a skill curator run updates the skills in place.

Settings come from `modernizer-backend/.env`, as for the web backend (see `.env.example`): `MIGRATION_JAVA_HOME`,
`BASELINE_JAVA_HOME`, `MAVEN_SETTINGS`, `APPROVED_VERSIONS_FILE`, `BUILD_LOOP_MAX_ITERATIONS`, `JAVA11_ANALYSIS`,
`MIGRATION_ANALYSIS`, `RULES_EXTRACTION`, and the rest. Model settings (`GEMINI_MODEL`, `MODEL_PLAN`, ...) do not
apply: the models are Gemini CLI's. To give a role its own model, add `model: gemini-2.5-flash` (for example) to
that subagent's front matter in `agents/`.

## Use

Open the repository to modernize (a clean git working tree is recommended — a migration changes it in place
once you approve the plan) and start Gemini CLI there:

```text
/modernize:start java-8-to-11
/modernize:start java-8-to-25 incremental springboot
/modernize:start solr-4-to-9 context=docs/search-api.yaml
/modernize:discover                       # stack discovery: documents only, changes nothing
```

The run goes as far as it can and stops at each human gate:

| Gate | What you do |
|---|---|
| Companion migrations (Java 8 → 25 with Oracle / Solr / TIBCO in the repository) | `/modernize:approve oracle-19c-to-23ai` (or `/modernize:approve none`) |
| Analysis review (only when an agent wrote the analysis: JSP → React, or `*_ANALYSIS=agent`) | Review/edit `.modernizer/docs/<pattern>/brd.md`, `technical_spec.md`, `test_inventory.md`; then `/modernize:approve` or `/modernize:refine <feedback>` |
| **Plan approval** — nothing changes before it | Review/edit `.modernizer/docs/<pattern>/plan.md`; then `/modernize:approve` or `/modernize:refine <feedback>` |
| Stack discovery: stacks and documents | `/modernize:approve java thymeleaf oracle` (+ which documents) |
| Stack discovery: final review | `/modernize:approve`, or `/modernize:refine brd <feedback>` (re-runs only that writer) |

`/modernize:next` continues a run (also after restarting Gemini CLI), `/modernize:status` shows where it is,
`/modernize:export` writes Word copies to `.modernizer/export/`.

After the plan is approved the run goes on by itself: modifier per plan task (per stage for Java 8 → 25
incremental), the real build in a validate/fix loop, the independent code review, the report, skill curation,
the scope-fence restore (Java 8 → 11) and the diff. Results are in `.modernizer/results/<pattern>/`
(`final_report.md`, `code_review.md`, `build_result*.json`) and `.modernizer/results/changes.md` /
`changes.patch`. The repository as it was is kept under `~/.modernizer/baselines/` (`MODERNIZER_HOME`).

## How a step runs

`next_step` (MCP) runs every deterministic step it reaches — the inventories, the preflight build, the plan
completeness and path checks, the Mockito rewrite, discovery's computed sections, grounding and assembly, the
diff — and returns the next step that needs a model, with the subagent and its exact brief: the skill to
activate, the inputs to read, the rules, the approved versions and a `step_id`. Gemini calls the subagent
(`invoke_agent`), the subagent saves its result with `save_output`, and `complete_step` does what the ADK
callbacks did: splits the analysis into its sections, checks the plan, sends a task back once for listed files
it left unchanged, routes a failed build to the fixer, publishes verified lessons to the skills.

The subagents only have the tools of their role. The coder writes through `ws_write_file` /
`ws_replace_in_file`, which refuse any write before the plan is approved, any write to `.modernizer/`, and —
for Java 8 → 11 — anything outside the scope fence. The validator can only build and check; success is
recorded only through `ws_signal_build_success`, which refuses while an approved-versions or fence check fails.
The reviewer gets the change audit and plan conformance; the curator can write only its pattern's skills.

## Without Gemini CLI

The pipeline is plain Python; `python -m cli` (in `modernizer-backend/`, with the `.venv-cli` Python) drives it
from a terminal — `start`, `next`, `status`, `complete <step_id>`, `confirm <gate>`, `refine`, `export`, `serve`.
Any agent that can follow a brief and write `.modernizer/out/<step_id>.md` can do the model steps.

## Differences from the web pipeline

- Runs in place on the repository you opened, not on an uploaded copy; ingestion limits do not apply.
- Steps run one at a time (`RE_CONCURRENCY` does not apply); pacing, masking and model fallback are
  Gemini CLI's own (its context compression and model routing).
- Stack discovery: evidence too large for one writer request is given to the writer in full (paged with
  read_file) instead of being merged by an extra agent.
- UX design uploads (JSP → React) are not offered; describe the designs in a context file instead.
