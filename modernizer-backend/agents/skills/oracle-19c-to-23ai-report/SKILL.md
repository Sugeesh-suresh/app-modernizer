---
name: oracle-19c-to-23ai-report
description: Produces the final human-readable migration report summarising what changed and the final validation status, from modify_result and the final build_result.
---

You are writing the closing report for a completed Oracle 19c -> 23ai migration run. You have no tools — reason only from the Modify Result and Final Validation Result provided below.

Produce a concise markdown report:

# Migration Report: Oracle 19c → Oracle 23ai

## Summary
One paragraph: what was migrated and the final outcome (validation passing or not).

## Validation Status
- Final result: PASSED or FAILED (from the Final Validation Result JSON's `passed` field)
- If FAILED: list the remaining issues verbatim, and note they need manual follow-up
- Note explicitly that validation here is static syntax/heuristic checking, not a real database compile

## Changes Applied
Summarise the files written and skipped from the Modify Result — group by category (compatibility fixes, optional 23ai feature adoption, driver bumps).

## Follow-up Recommendations
- A real `sqlcl`/`SQL*Plus` compile check against a non-production 23ai instance before rollout
- DBA review of any object touched, since automated validation cannot connect to a live database
- The database engine upgrade itself and any live data migration remain out of scope and are separate infrastructure work

Keep it factual and grounded strictly in the two inputs.
