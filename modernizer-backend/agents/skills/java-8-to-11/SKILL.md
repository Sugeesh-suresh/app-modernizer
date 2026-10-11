---
name: java-8-to-11
description: >
  Upgrades a Java 8 JSP + WildFly monolith to Java 11 — Java sources and build files only, inside a
  scope fence that keeps the JSP tier and the WildFly deployment untouched: unit-by-unit reverse
  engineering, migration plan, task-by-task changes, build and fence validation, repair, and the final
  report — one step file per pipeline step.
---

# Java 8 → 11 (JSP + WildFly monolith)

Move a large Java 8 monolith (Java classes, APIs and JSP views, deployed as a WAR on WildFly/JBoss) to Java 11. Only `.java` sources and build files change. The **scope fence** is part of the migration, not advice: JSP files, web resources and the WildFly deployment descriptors must come out byte-for-byte unchanged, the writing tools refuse anything outside the fence, and validation checks the fence's invariants as well as packaging the WAR at release 11.

## Workflow

The pipeline runs the steps in this order, holds every change until a person approves the plan, and runs the validate → fix loop until the validation passes or its limit is reached. Your caller tells you which step is yours: load that step file with `load_skill_resource` and follow it — not the others.

| # | Step | Step file | What it does |
|---|---|---|---|
| 1 | `re-module` | `references/steps/re-module.md` | Reverse engineering of one unit (module, or part of one) into Module Findings |
| 2 | `re` | `references/steps/re.md` | Reverse engineering: the confirmed BRD, Technical Specification and Test Inventory |
| 3 | `plan` | `references/steps/plan.md` | The migration plan a person approves before anything changes |
| 4 | `modify` | `references/steps/modify.md` | Applies the approved plan (or one task of it) to the workspace |
| 5 | `validate` | `references/steps/validate.md` | Validates the workspace for real and reports pass/fail as JSON |
| 6 | `fix` | `references/steps/fix.md` | Repairs what the validation reported, inside the loop |
| 7 | `report` | `references/steps/report.md` | The final migration report |

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
| `references/java11-blockers.md` | `re-module`, `re`, `plan` |
| `references/java11-build-fixes.md` | `fix` |
| `references/java11-code-patterns.md` | `modify`, `fix` |
| `references/java11-dependency-matrix.md` | `plan`, `modify`, `fix` |
