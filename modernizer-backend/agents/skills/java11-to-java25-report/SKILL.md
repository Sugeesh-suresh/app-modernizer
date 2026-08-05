---
name: java11-to-java25-report
description: Produces the final human-readable migration report summarising what changed and the final build status, from modify_result and the final build_result.
---

You are writing the closing report for a completed Java 11 -> Java 25 migration run. You have no tools — reason only from the Modify Result and Final Build Result provided below.

Produce a concise markdown report:

# Migration Report: Java 11 → Java 25

## Summary
One paragraph: what was migrated and the final outcome (build passing or not).

## Build Status
- Final result: PASSED or FAILED (from the Final Build Result JSON's `passed` field)
- If FAILED: list the remaining errors verbatim from the Final Build Result, and note that they will need manual follow-up

## Changes Applied
- Summarise the files written and skipped from the Modify Result — group by category (language modernisation, namespace migration, dependency bumps) rather than just repeating the raw list

## Follow-up Recommendations
- Anything the automated pipeline could not verify (e.g. test suite results, runtime behaviour, performance) and should be checked manually before this is considered production-ready

Keep it factual and grounded strictly in the two inputs — do not claim the build passed if the Final Build Result says otherwise.
