---
name: solr-4-to-9
description: >
  Migrates a Solr 4.x deployment — schema, solrconfig and SolrJ client code — to Solr 9.x:
  migration plan, applying the plan, static validation and repair, and the final report —
  one step file per pipeline step, sharing one body of Solr migration knowledge.
---

# Solr 4 → 9

Upgrade a Solr 4.x deployment to Solr 9.x: the cores' schema (Trie → Point fields, docValues, `_version_`), `solrconfig.xml` (handlers, components, `luceneMatchVersion`, `<lib>` paths) and the SolrJ client code (`*SolrServer` → `*SolrClient`, builders), with the dependency versions. Validation is a deterministic check of the migrated configuration.

## Workflow

The pipeline runs the steps in this order, holds every change until a person approves the plan, and runs the validate → fix loop until the validation passes or its limit is reached. Your caller tells you which step is yours: load that step file with `load_skill_resource` and follow it — not the others.

| # | Step | Step file | What it does |
|---|---|---|---|
| 1 | `plan` | `references/steps/plan.md` | The migration plan a person approves before anything changes |
| 2 | `modify` | `references/steps/modify.md` | Applies the approved plan (or one task of it) to the workspace |
| 3 | `validate` | `references/steps/validate.md` | Validates the workspace for real and reports pass/fail as JSON |
| 4 | `fix` | `references/steps/fix.md` | Repairs what the validation reported, inside the loop |
| 5 | `report` | `references/steps/report.md` | The final migration report |

One more step runs in every migration and belongs to a shared skill: `code-review` (an independent review of the result against the plan) after the loop.

## Rules for every step

- **Evidence before claims.** Read a file before you describe it or change it; never reconstruct a file's contents
  from memory. Cite the file (and line) for what you state.
- **Nothing changes before a person approves the plan.** The pipeline holds every write until the plan is approved;
  the plan step only reads.
- **Change only what your step is given.** The modify and fix steps apply the confirmed plan (or the one task they
  are given) and nothing else; anything more is reported, not done.
- **The validator's result is the truth.** No step reports success the validation did not show.
- **Knowledge lives in `references/`.** Each step file lists the knowledge files it needs; load them with
  `load_skill_resource` (Gemini CLI: read them from the skill's folder).

## Knowledge

| File | Used by the steps |
|---|---|
| `references/solr-code-patterns.md` | `modify`, `fix` |
| `references/solr4-baseline-facts.md` | `plan` |
| `references/solr4-to-solr9-checklist.md` | `plan`, `modify`, `fix` |
