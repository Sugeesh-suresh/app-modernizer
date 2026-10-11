---
name: jsp-to-react-bff
description: >
  Transforms a JSP monolith into a React frontend and a Spring Boot 4 Backend-For-Frontend: extraction
  of the JSP application's facts, frontend/backend classification of its logic, the target design and
  file manifests, building both trees, repair, and the final report — one step file per pipeline step.
  The two trees themselves are written by the standalone `spring-boot-bff-generate` and
  `react-frontend-generate` skills.
---

# JSP → React + Spring Boot 4 BFF

Decouple a server-rendered JSP application: every page's logic is classified as a frontend (React) or backend (BFF) concern, the plan designs a `frontend/` React app calling a `backend/` Spring Boot 4 BFF packaged as a standalone JAR, the generator skills write both trees, and validation builds both for real.

## Workflow

The pipeline runs the steps in this order, holds every change until a person approves the plan, and runs the validate → fix loop until the validation passes or its limit is reached. Your caller tells you which step is yours: load that step file with `load_skill_resource` and follow it — not the others.

| # | Step | Step file | What it does |
|---|---|---|---|
| 1 | `re` | `references/steps/re.md` | Reverse engineering: the confirmed BRD, Technical Specification and Test Inventory |
| 2 | `classify` | `references/steps/classify.md` | Classifies each JSP's logic as frontend or backend |
| 3 | `plan` | `references/steps/plan.md` | The migration plan a person approves before anything changes |
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
| `references/bff-architecture-checklist.md` | `plan`, `fix` |
| `references/classification-examples.md` | `classify` |
| `references/jsp-baseline-facts.md` | `re`, `classify`, `plan` |
