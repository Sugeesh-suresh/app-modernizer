---
name: oracle-19c-to-23ai
description: >
  Migrates Oracle 19c SQL/PL-SQL source (and the JDBC driver in the build) to be Oracle
  23ai-compatible: reverse engineering, migration plan, applying the plan, static validation and
  repair, and the final report — one step file per pipeline step, sharing one body of Oracle migration
  knowledge.
---

# Oracle 19c → 23ai

Upgrade a codebase's Oracle 19c SQL and PL/SQL — DDL, packages, procedures, triggers, views and the JDBC driver in the build — so it runs on Oracle 23ai, adopting optional 23ai features only where the approved plan calls for them. There is no live database: validation is a deterministic static check of the migrated SQL/PL-SQL.

## Workflow

The pipeline runs the steps in this order, holds every change until a person approves the plan, and runs the validate → fix loop until the validation passes or its limit is reached. Your caller tells you which step is yours: load that step file with `load_skill_resource` and follow it — not the others.

| # | Step | Step file | What it does |
|---|---|---|---|
| 1 | `re` | `references/steps/re.md` | Reverse engineering: the confirmed BRD, Technical Specification and Test Inventory |
| 2 | `plan` | `references/steps/plan.md` | The migration plan a person approves before anything changes |
| 3 | `modify` | `references/steps/modify.md` | Applies the approved plan (or one task of it) to the workspace |
| 4 | `validate` | `references/steps/validate.md` | Validates the workspace for real and reports pass/fail as JSON |
| 5 | `fix` | `references/steps/fix.md` | Repairs what the validation reported, inside the loop |
| 6 | `report` | `references/steps/report.md` | The final migration report |

Two more steps run in every migration and belong to shared skills: `code-review` (an independent review of the result against the plan) after the loop, and `skill-curator` (refines this skill from the run's evidence) at the very end.

## Rules for every step

- **Evidence before claims.** Read a file before you describe it or change it; never reconstruct a file's contents
  from memory. Cite the file (and line) for what you state.
- **Nothing changes before a person approves the plan.** The pipeline holds every write until the plan is approved;
  the analysis and plan steps only read.
- **Change only what your step is given.** The modify and fix steps apply the confirmed plan (or the one task they
  are given) and nothing else; anything more is reported, not done.
- **The validator's result is the truth.** No step reports success the validation did not show.
- **Knowledge lives in `references/`.** Each step file lists the knowledge files it needs; load them with
  `load_skill_resource` (Gemini CLI: read them from the skill's folder).

## Knowledge

| File | Used by the steps |
|---|---|
| `references/oracle19c-baseline-facts.md` | `re`, `plan` |
| `references/oracle19c-to-23ai-checklist.md` | `plan`, `modify`, `fix` |
| `references/plsql-patterns.md` | `modify`, `fix` |
