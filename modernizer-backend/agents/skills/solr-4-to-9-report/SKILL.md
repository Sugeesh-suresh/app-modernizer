---
name: solr-4-to-9-report
description: Produces the final human-readable migration report summarising what changed and the final validation status, from modify_result and the final build_result.
version: 0.1.0
maturity: experimental
---

You are writing the closing report for a completed Solr 4.x -> 9.x migration run. You have no tools — reason only from the Modify Result and Final Validation Result provided below.

Produce a concise markdown report:

# Migration Report: Solr 4.x → Solr 9.x

## Summary
One paragraph: what was migrated and the final outcome (validation passing or not).

## Validation Status
- Final result: PASSED or FAILED (from the Final Validation Result JSON's `passed` field)
- If FAILED: list the remaining issues verbatim, and note they need manual follow-up

## Changes Applied
Summarise the files written and skipped from the Modify Result — group by category (schema changes, solrconfig.xml changes, SolrJ client renames, dependency bumps).

## Follow-up Recommendations
- Reindexing strategy (a full reindex is almost always required across a 4→9 jump — this pipeline does not perform it)
- ZooKeeper ensemble upgrade, if SolrCloud
- A real Solr smoke test against the migrated config, since automated validation here is static only (no live Solr instance was started)

Keep it factual and grounded strictly in the two inputs.
