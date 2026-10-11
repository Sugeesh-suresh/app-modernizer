# Stella Modernizer

This extension runs the Stella Modernizer — AI-driven modernization of legacy applications — inside Gemini CLI.
Every migration is a pipeline over the repository open in this session:

analyse → (analysis review) → plan → **plan approval** → modify → build/validate/fix loop → independent review
→ report → skill curation → scope-fence restore → diff

Patterns: `java-8-to-25` (bigbang or incremental, optional Spring Boot 4 / JUnit), `java-8-to-11` (JDK only;
JSP and WildFly frozen), `solr-4-to-9`, `oracle-19c-to-23ai`, `tibco-ems-to-pubsub`, `jsp-to-react-bff`, and
`stack-discovery` (reverse engineering: documents the repository as it is; changes nothing).

Reverse engineering (`stack-discovery`) asks the user for a **strategy** before reading any code, with options
computed for the repository: `layered-trace` (UI top-down → data bottom-up → API & logic; recommended for
full-stack applications), `api-first`, `data-first` or `stack-by-stack`. Its deliverables are separate files in
`.modernizer/deliverables/`: `SETUP.md`, `BRD.md`, `TECHNICAL_SPECIFICATION.md`, `openapi.yaml`/`openapi.json`
(OpenAPI 3.0), `TECH_DEBT_AND_DEAD_CODE.md` (for human review), `UI_PAGES.md` (each UI page's elements,
interactions and backend traces) and `UI_SCREENS.md` (a screenshot of each page) when the repository has a UI, `STRATEGY.md`, `EVIDENCE.md` and a `README.md` index.

## What does what

- **The `modernizer` MCP server** (tools `mcp_modernizer_*`) owns the pipeline. `next_step` runs every
  deterministic step itself — inventories, preflight build, dependency graph, plan checks, mechanical rewrites,
  computed discovery sections, the final diff — and returns the next step that needs a model or a person.
- **Skills** (activated with `activate_skill`) hold the domain knowledge: one skill per migration
  (`oracle-19c-to-23ai`, `solr-4-to-9`, `java-8-to-25`, …) with a step file per pipeline step under
  `references/steps/` (`re`, `plan`, `modify`, `validate`, `fix`, `report`) and its knowledge in `references/`,
  plus `code-review`, `skill-curator`, the discovery skills and the generators. The subagents activate them; the
  queries say which skill and which step file.
- **Subagents** do the model work, each with only the tools its role needs: `modernizer-analyst`,
  `modernizer-planner`, `modernizer-coder`, `modernizer-validator`, `modernizer-reviewer`,
  `modernizer-writer`, `modernizer-curator`.
- **State** lives in `.modernizer/` in the repository (`run.json`, `docs/<pattern>/` for the BRD, Technical
  Specification, Test Inventory and plan, `results/` for builds, review, report and the diff). The baseline copy
  of the repository is under `~/.modernizer/baselines/`. A run survives restarting Gemini CLI.

## Driving the pipeline

Commands: `/reverse-engineer [strategy] [docs=...]`, `/modernize:start <pattern> [...]`, `/modernize:discover`, `/modernize:next`, `/modernize:status`,
`/modernize:approve [...]`, `/modernize:refine <feedback>`, `/modernize:export`.

When continuing a run, loop:

1. Call `mcp_modernizer_next_step`.
2. If the step's kind is `subagent`: call `invoke_agent` with `agent_name` = the subagent it names and
   `prompt` = the text between `<query>` and `</query>`, **verbatim and complete** — it is the exact brief the
   pipeline wrote (skill, inputs, rules, step_id). Do not summarise or extend it. Then call
   `mcp_modernizer_complete_step` with the `step_id`, and go back to 1.
3. If it is `ask_user` or `review_gate`: stop. Tell the user what to decide or review (with the file paths)
   and which command answers it. For the strategy choice, show every option with what it does, when it fits
   and why one is recommended (from `.modernizer/discovery/strategy.md`). **Never confirm a gate on the user's behalf** — the analysis review and the
   plan approval are the human checkpoints of this process; nothing in the repository changes before the plan
   is approved.
4. If it is `blocked`: stop and explain what to fix. If it is `done`: summarise and point to the reports.

Rules:

- Do not do a subagent's work yourself, and do not change repository files outside a subagent: the subagents'
  write tools enforce the approved plan, the approved-versions list and (Java 8 → 11) the scope fence.
- Do not edit `.modernizer/` files, except a document under review when the user asks you to — the review
  gates invite edits to the BRD, Technical Specification, Test Inventory and plan before approval.
- Keep the user informed with one line per step: what finished, what runs next.
