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

Requirements: Node 20+ (for Gemini CLI), Python 3.10+ on PATH, and the build tools of the pattern you run (JDK +
Maven/Gradle for the Java patterns, Node/npm for JSP → React). Gemini CLI loads every enabled extension side by
side, so this one installs next to any you already have.

### Option A — install from git (users)

```bash
gemini extensions install https://github.com/sugeesh-suresh/app-modernizer.git --ref=stable --auto-update
# or, with SSH keys:  gemini extensions install git@github.com:sugeesh-suresh/app-modernizer.git --ref=stable --auto-update
node ~/.gemini/extensions/stella-modernizer/launch.mjs --setup     # optional: build the Python env now
```

`stable` is the release branch: the extension at the root, the skills as files, and only the part of
`modernizer-backend` the CLI runs (see [Publishing a release](#publishing-a-release)). On the first start the
extension creates its Python environment inside its folder (about 20 s, once per release; `--setup` does it ahead
of time so the first Gemini session does not wait). `--auto-update` (or `gemini extensions update
stella-modernizer`) replaces the copy with the branch's latest release.

Settings go in `~/.modernizer/.env` (the same keys as `modernizer-backend/.env.example`): an update replaces the
installed folder, so a `.env` inside it would be lost. The skill curator's edits to an installed copy are lost on
update as well — skills are improved in a checkout (option B) and released.

### Option B — link a checkout (development)

```bash
git clone -b CLI-modernizer https://github.com/sugeesh-suresh/app-modernizer.git && cd app-modernizer
node gemini-cli/install.mjs --link          # Python env (modernizer-backend/.venv-cli) + skills link + gemini extensions link
```

Linked, the extension runs this checkout's code and skills directly: edits are live, and a skill curator run
updates the skills in place. Settings come from `modernizer-backend/.env` (then `~/.modernizer/.env` for keys it
does not set). Use `link` for a checkout — `gemini extensions install <path>` would copy it and leave the skills
link behind.

Settings (either option): `MIGRATION_JAVA_HOME`, `MIGRATION_JAVA_HOMES`, `BASELINE_JAVA_HOME`, `MAVEN_SETTINGS`,
`PREFLIGHT`, `APPROVED_VERSIONS_FILE`, `BUILD_LOOP_MAX_ITERATIONS`, `JAVA11_ANALYSIS`, `MIGRATION_ANALYSIS`,
`RULES_EXTRACTION`, and the rest of `.env.example`. Model settings (`GEMINI_MODEL`, `MODEL_PLAN`, ...) do not
apply: the models are Gemini CLI's. To give a role its own model, add `model: gemini-2.5-flash` (for example) to
that subagent's front matter in `agents/`.

Check it: `gemini extensions list` shows `stella-modernizer` with the `modernizer` MCP server and its skills; in a
session, `/mcp` lists the server and the `/modernize:*` and `/reverse-engineer` commands autocomplete. Remove it
with `gemini extensions uninstall stella-modernizer`.

### Publishing a release

From a clean checkout of the branch to release:

```bash
node gemini-cli/build-release.mjs --push                  # builds and pushes the `stable` branch to origin
node gemini-cli/build-release.mjs --push --branch beta    # another channel; install it with --ref=beta
node gemini-cli/build-release.mjs                         # build only, into dist/gemini-extension
```

Each release is one commit on the release branch, named after the source commit it was built from
(`RELEASE.json` records it); a rebuild of the same source changes nothing. Installed copies pick it up with
`gemini extensions update stella-modernizer` (or automatically, when installed with `--auto-update`).

## Use

Open the repository to modernize (a clean git working tree is recommended — a migration changes it in place
once you approve the plan) and start Gemini CLI there:

```text
/modernize:start java-8-to-11
/modernize:start java-8-to-25 incremental springboot
/modernize:start solr-4-to-9 context=docs/search-api.yaml
/reverse-engineer                         # reverse engineering: documents only, changes nothing
/reverse-engineer layered-trace docs=brd,technical_spec,openapi,ui_pages   # strategy and documents up front
/modernize:discover                       # the same run, without arguments
```

The run goes as far as it can and stops at each human gate:

| Gate | What you do |
|---|---|
| Companion migrations (Java 8 → 25 with Oracle / Solr / TIBCO in the repository) | `/modernize:approve oracle-19c-to-23ai` (or `/modernize:approve none`) |
| Analysis review (only when an agent wrote the analysis: JSP → React, or `*_ANALYSIS=agent`) | Review/edit `.modernizer/docs/<pattern>/brd.md`, `technical_spec.md`, `test_inventory.md`; then `/modernize:approve` or `/modernize:refine <feedback>` |
| **Plan approval** — nothing changes before it | Review/edit `.modernizer/docs/<pattern>/plan.md`; then `/modernize:approve` or `/modernize:refine <feedback>` |
| Stack discovery: stacks and documents | `/modernize:approve java thymeleaf oracle` (+ which documents: brd, technical_spec, test_inventory, setup, openapi, tech_debt, ui_pages, ui_screens) |
| Stack discovery: reverse-engineering strategy | `/modernize:approve layered-trace` (or `api-first`, `data-first`, `stack-by-stack`) — the options and the recommendation are in `.modernizer/discovery/strategy.md` |
| Stack discovery: final review | `/modernize:approve`, or `/modernize:refine brd <feedback>` / `technical_spec` / `setup` (re-runs only that writer) |

Stack discovery writes its deliverables as separate files to `.modernizer/deliverables/` — `README.md` (index),
`SETUP.md`, `BRD.md`, `TECHNICAL_SPECIFICATION.md`, `openapi.yaml` / `openapi.json` (OpenAPI 3.0.3),
`TECH_DEBT_AND_DEAD_CODE.md`, `UI_PAGES.md` (every page's HTML elements, interactive elements and their traces
to the backend, page by page), `UI_SCREENS.md` (a screenshot of each page, same order), `STRATEGY.md`, `EVIDENCE.md`. With the layered strategy the code is traced
layer by layer: the API and business logic first (`layer-api-logic`, each endpoint traced once down to the data
store), then the UI top-down (`layer-ui-trace`: the UI side only, linking each control to its endpoint's trace), then
the data bottom-up (`layer-data-trace`).

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
for Java 8 → 11 — anything outside the scope fence. Java 8 → 25 also removes files its stages make obsolete
(`web.xml`, Spring XML contexts) with `ws_delete_file`, one file per call. `ws_run_command` builds on the JDK the
preflight assigned to the running stage's Java release. The validator can only build and check; success is
recorded only through `ws_signal_build_success`, which refuses while an approved-versions or fence check fails.
The reviewer gets the change audit and plan conformance; the curator can write only its pattern's skills.


### Parallel batches

Reverse engineering cuts its work into independent batches: the batches of a layer pass, the units of a large
stack, the business-rules batches and the UI-contract batches. `next_step` hands out up to
`DISCOVERY_CONCURRENCY` (default 4) of them as one `parallel` step; Gemini calls one subagent per batch in the
same response, and Gemini CLI runs those calls at the same time. Each batch gets exactly the request and the
checks it gets when run alone, its result is recorded when it completes (in any order), and whatever depends
on a group — a pass's merge, the rules finalisation, the writers — waits until every batch of it is in. Set
`DISCOVERY_CONCURRENCY=1` to run one at a time, or lower it if Gemini reports rate limits (429).

### Progress while the pipeline works

Some steps need no model and can still take minutes: the Java preflight builds the code as uploaded with
Maven (the first build downloads every dependency), the inventories scan every file, discovery computes its
sections. `next_step` runs that work in the background and, instead of leaving Gemini on "Thinking…",
answers after `PROGRESS_FIRST_REPORT_SECONDS` (default 20) and then every `PROGRESS_REPORT_SECONDS` (default
60) with what is running:

```text
## Still working — no step for you yet

**The run is working through its deterministic steps** — running for 4m10s (no model involved).

- **Now:** Environment check: baseline build of `rest` (2 of 3) on JDK 8 — `mvn -fae -DskipTests clean package` … — 2m05s
  - Maven: building `security-rest 1.0 [2/5]`; step `maven-compiler-plugin:compile`; 412 artifact(s) downloaded, last `spring-core-3.2.18.RELEASE.jar`
  - Last output (2m05s in, 1830 lines): `[INFO] Compiling 214 source files to …/target/classes`

Finished so far:
- Environment check: finding the JDKs (…) (6s)
- Environment check: baseline build of `.` (1 of 3) on JDK 8 — … (1m52s)
```

Gemini relays the **Now:** line and calls `next_step` again; that call re-attaches to the same work, so
pressing Esc and resuming never restarts a build. `/modernize:status` shows the same report while it runs.
`python -m cli next` prints each stage to stderr as it starts.
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
