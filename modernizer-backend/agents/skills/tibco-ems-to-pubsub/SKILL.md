---
name: tibco-ems-to-pubsub
description: >
  Migrates a TIBCO EMS integration — destinations, producers and consumers, message selectors,
  delivery semantics — to Google Cloud Pub/Sub: reverse engineering, migration plan, applying the
  plan, validation and repair, and the final report — one step file per pipeline step, sharing one
  body of messaging migration knowledge.
---

# TIBCO EMS → Google Cloud Pub/Sub

Move a TIBCO EMS integration to Google Cloud Pub/Sub: JMS producers and consumers to the Pub/Sub client library, queues and topics to topics and subscriptions, message selectors to subscription filters (or consumer-side filtering), and acknowledgement, ordering and redelivery to their Pub/Sub equivalents. Validation is a real build when the client is Java, else a deterministic topic-mapping check.

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
| `references/pubsub-code-patterns.md` | `modify`, `fix` |
| `references/pubsub-migration-checklist.md` | `plan`, `modify`, `fix` |
| `references/tibco-ems-baseline-facts.md` | `re`, `plan` |
