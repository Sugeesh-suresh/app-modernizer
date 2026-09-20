---
name: tibco-ems-to-pubsub-plan
description: Creates a detailed migration plan (plan.md) for migrating a TIBCO EMS integration to Google Cloud Pub/Sub, based on the confirmed BRD and Technical Specification.
version: 0.1.0
maturity: experimental
---

You are a messaging migration expert. Create a detailed `plan.md` for migrating this integration from TIBCO EMS to Google Cloud Pub/Sub, using the confirmed BRD and Technical Specification provided below.

Load `references/pubsub-migration-checklist.md` for the full destination/API/semantics mapping.

# Migration Plan: TIBCO EMS → Google Cloud Pub/Sub

## Overview
Current state (destinations, producers/consumers, EMS client library) and target state (Pub/Sub topics/subscriptions).

## 1. What Changes

### Skill Composition
Reproduce the injected Skill Composition table **verbatim**, including the note beneath it. You cannot see these versions any other way, so anything you write instead of copying is invented. A skill at 0.x has not been proven on real repositories, and the approver is entitled to see that before agreeing to the run.

### Dependency & Version Delta
A table: Component | Current | Target | Why it must move. Cover at least the EMS client library being removed, the Pub/Sub client being added, and any JMS or serialisation library the change affects. Take the current values from the Technical Specification's repo facts — never invent a version you were not told.

### Sample Transformations
Two or three real before/after snippets in fenced blocks, each labelled with its file path, drawn from files the Technical Specification actually lists. Choose a producer rewrite (`TibjmsConnectionFactory`/`MessageProducer` → `Publisher`), a consumer rewrite with explicit ack/nack, and a selector that could not be expressed as a Pub/Sub filter. One real diff tells a reviewer more than a paragraph of description. If the specification does not give you enough of a file to quote honestly, say so instead of fabricating a snippet.

### Destination → Topic/Subscription Mapping
Restate the Technical Specification's mapping table as the authoritative migration target — one row per EMS destination, with the exact Pub/Sub topic and subscription name(s) to create.

### Message Selector Translation
For every selector found: either the equivalent Pub/Sub subscription filter expression, or — if it cannot be expressed as a filter — the consumer-side filtering logic to add instead. Be explicit about which case applies to each selector.

### Delivery Semantics Reconciliation
For every flow that assumed EMS's transacted/CLIENT_ACKNOWLEDGE semantics or strict ordering: the Pub/Sub equivalent (ack/nack handling, idempotency requirements, ordering keys if needed) and any consumer-side changes required to remain correct under Pub/Sub's at-least-once delivery.

### Client Code Migration
Every JMS client call site (from the checklist's Client API mapping table) and its Pub/Sub client library replacement.

### Dependency Upgrades
Add `google-cloud-pubsub` (or the current GCP client library artifact) to `pom.xml`/`build.gradle`; remove the TIBCO EMS client dependency once no longer referenced.

### File Change Manifest
A table, one row per file — the thing the human reviewer actually approves, and the scope agreement the code reviewer compares against what really changed afterwards. This is also what modifier_agent works through file-by-file, so be exhaustive and precise with paths.

| File | Change Type | What Changes |
|---|---|---|
| `src/main/java/com/acme/OrderPublisher.java` | client code migration | `TibjmsConnectionFactory`/`MessageProducer` → Pub/Sub `Publisher`; payload bytes unchanged |
| `src/main/java/com/acme/OrderListener.java` | client code migration | `MessageListener` → `Subscriber` with explicit ack/nack; at-least-once handling added |
| `src/main/resources/ems.properties` | config migration | queue names → topic/subscription resource names |

Rules that make the table checkable rather than decorative:
- **The path is backticked and real** — copied from the repository scan, workspace-relative, never invented. An entry matching no file is reported against the plan.
- **Every in-scope file gets a row**, including the ones whose change type is `delete` or `no change needed`. A file you leave out is a file nobody approved being edited.
- **"What Changes" is specific to that file** — what will actually be different in it, not a restatement of the change type.
- Change types: client code migration / selector translation / delivery-semantics change / config migration / dependency bump / delete / no change needed.

Use markdown with task checkboxes `- [ ]` for every actionable item elsewhere in the plan.

## 2. What Stays the Same
The most commonly missed section, and the one that makes review manageable — it is how a reviewer knows what they do *not* have to check.

### Explicit Non-Changes
Flat assertions a reviewer can hold the result to: no message payload shapes change; no business logic in a consumer changes; no downstream side effect changes; no API exposed to other services changes. Where any of these *does* change, name the exception here rather than leaving the assertion false.

### Out of Scope
Everything the analysis noticed and is deliberately leaving alone — a bug found in passing, dead code, something that looks old but works, anything a toggle excludes. One line of reason each. Listing them is what stops "while we're here" scope creep during the run, and it tells the reviewer these were seen rather than missed.

## 3. Why This Is Safe

### Risk Tier
**Low / Medium / High**, and the factor that drove it, with evidence — never the bare word. Score three factors separately: **blast radius** (how much of the system this reaches), **novelty** (how much is an API rewrite rather than a version bump, and how much is governed by a skill still at 0.x), and **behavioural opacity** (how much behaviour has no test proving it). Say which factor set the tier and cite the evidence for it.

### Behaviour Inventory
A table of every behaviour this migration must preserve: Behaviour | Kind | Where it lives | Evidence it exists (verified or inferred). Take it from every message producer, consumer, destination, selector, scheduled job and downstream side effect the specification records. Messaging behaviour is the least visible in code and the most expensive to get wrong. This is the full set of things that must still work afterwards, and question 4 is answered against it row by row — so an incomplete inventory silently shrinks the proof obligation.

### Blast Radius
What outside this repository the change can reach: other repos, shared schemas, topics with other producers or consumers, published libraries, and anything needing to move in the same coordinated release. Where nothing is reachable, say so explicitly rather than omitting the section.

## 4. How We'll Prove It Worked

### Evidence Plan
One row per behaviour in the Behaviour Inventory: Behaviour | What proves it survives | Exists today? Name the actual test from the Existing Test Inventory where one exists, and say what would have to be written where none does.

### Coverage Gaps
The behaviours with nothing proving them, stated plainly and counted. Take the Test Inventory's own Coverage Gaps as the starting point and extend it to the Behaviour Inventory. State this up front — a gap discovered at review is a gap that was hidden at approval — and say explicitly whether the run will generate characterisation tests first or proceed without them, since that is a decision the approver is making.

### Validation Contract
The exit criteria this run is held to, taken from the skills that govern it, and what they do **not** cover. Name what a human still has to do that no automated step covers.

## 5. What Happens If It Fails

### Rollback Plan
**Rollback is not clean, and the plan must say so plainly.** Code reverts with the commit, but messages already published to Pub/Sub, or consumed and acknowledged from EMS, cannot be un-sent or un-consumed. State what the cutover looks like, whether producers and consumers can run against both transports during it, what happens to in-flight messages if it is reversed, and whether any message loss or duplication is possible. EMS and Pub/Sub also differ in ordering and delivery guarantees — say where behaviour genuinely changes rather than presenting it as like-for-like. An approver needs all of this before approving, not after.

### Escalation Triggers
The conditions under which the run stops and hands over to a person rather than continuing: a selector has no Pub/Sub filter equivalent and consumer-side filtering would change semantics, ordering is required but not expressible, a delivery guarantee cannot be matched, or the plan's manifest turns out to be wrong about the repository. Each one is a stop-and-ask, not a work-around.

## 6. What the Planner Doesn't Know
The section that builds the most trust, and the one to write most honestly — you worked from the BRD and Technical Specification, not from the code itself.

### Confidence Register
A table of the plan's material claims: Claim | Confidence | Basis. Mark each **verified** (the specification states it from a file actually read) or **inferred** (deduced from a name, a convention or a dependency, without direct evidence), and put a trailing `*` on every inferred row so it is visible at a glance. An approver uses this to know exactly where to look by hand.

### Assumptions
What the plan relies on that is not proven — each one a thing that, if false, changes the plan.

### Open Questions for the SME
Behaviour that could not be determined from the code and needs a person: whether message ordering is actually required, whether a consumer is idempotent, whether duplicate delivery is already handled downstream, and whether any external system produces to or consumes from these destinations. Ask each as a direct question naming the file it concerns, so it can be answered without re-reading the plan.
## Operational Follow-up (outside this pipeline's automated scope)
Pub/Sub topic/subscription provisioning (Terraform/gcloud), EMS server decommissioning timeline, in-flight message drain/cutover plan.

## Estimated Effort

