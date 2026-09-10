---
name: tibco-ems-to-pubsub-report
description: Produces the final human-readable migration report summarising what changed and the final validation status, from modify_result and the final build_result.
---

You are writing the closing report for a completed TIBCO EMS -> Google Cloud Pub/Sub migration run. You have no tools — reason only from the Modify Result and Final Validation Result provided below.

Produce a concise markdown report:

# Migration Report: TIBCO EMS → Google Cloud Pub/Sub

## Summary
One paragraph: what was migrated (which destinations, how many producers/consumers) and the final outcome (validation passing or not).

## Validation Status
- Final result: PASSED or FAILED (from the Final Validation Result JSON's `passed` field)
- Note which check ran (real `mvn`/`gradle` build, or static config check) — the summary field should say so
- If FAILED: list the remaining errors/issues verbatim, and note they need manual follow-up

## Changes Applied
Summarise the files written and skipped from the Modify Result — group by category (client code migration, selector translation, delivery-semantics reconciliation, config/dependency changes).

## Follow-up Recommendations
- Provisioning the actual GCP topics/subscriptions (Terraform/gcloud) — not performed by this pipeline
- An end-to-end smoke test against real Pub/Sub topics before cutover
- The EMS decommissioning and in-flight-message-drain plan — operational, not automated here
- Any selector that could not be expressed as a Pub/Sub filter and now relies on consumer-side filtering — call these out by name

Keep it factual and grounded strictly in the two inputs.
