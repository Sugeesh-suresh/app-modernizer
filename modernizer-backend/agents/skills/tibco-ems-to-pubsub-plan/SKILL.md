---
name: tibco-ems-to-pubsub-plan
description: Creates a detailed migration plan (plan.md) for migrating a TIBCO EMS integration to Google Cloud Pub/Sub, based on the confirmed BRD and Technical Specification.
---

You are a messaging migration expert. Create a detailed `plan.md` for migrating this integration from TIBCO EMS to Google Cloud Pub/Sub, using the confirmed BRD and Technical Specification provided below.

Load `references/pubsub-migration-checklist.md` for the full destination/API/semantics mapping.

# Migration Plan: TIBCO EMS → Google Cloud Pub/Sub

## Overview
Current state (destinations, producers/consumers, EMS client library) and target state (Pub/Sub topics/subscriptions).

## Destination → Topic/Subscription Mapping
Restate the Technical Specification's mapping table as the authoritative migration target — one row per EMS destination, with the exact Pub/Sub topic and subscription name(s) to create.

## Message Selector Translation
For every selector found: either the equivalent Pub/Sub subscription filter expression, or — if it cannot be expressed as a filter — the consumer-side filtering logic to add instead. Be explicit about which case applies to each selector.

## Delivery Semantics Reconciliation
For every flow that assumed EMS's transacted/CLIENT_ACKNOWLEDGE semantics or strict ordering: the Pub/Sub equivalent (ack/nack handling, idempotency requirements, ordering keys if needed) and any consumer-side changes required to remain correct under Pub/Sub's at-least-once delivery.

## Client Code Migration
Every JMS client call site (from the checklist's Client API mapping table) and its Pub/Sub client library replacement.

## Dependency Upgrades
Add `google-cloud-pubsub` (or the current GCP client library artifact) to `pom.xml`/`build.gradle`; remove the TIBCO EMS client dependency once no longer referenced.

## Operational Follow-up (outside this pipeline's automated scope)
Pub/Sub topic/subscription provisioning (Terraform/gcloud), EMS server decommissioning timeline, in-flight message drain/cutover plan.

## Validation & Rollout
Validation happens automatically in build_loop (a real `mvn`/`gradle` compile if the output is a Java/Spring client, or a deterministic topic-mapping config check otherwise) — this section covers what's outside that: an end-to-end smoke test against real Pub/Sub topics, rollback strategy.

## Estimated Effort

## File Change Manifest
Every in-scope file path with the change type. This is what modifier_agent will work through file-by-file — be exhaustive and precise with paths.

Use markdown with task checkboxes `- [ ]` for every actionable item.
