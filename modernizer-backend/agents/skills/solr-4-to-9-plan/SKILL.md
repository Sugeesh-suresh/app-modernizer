---
name: solr-4-to-9-plan
description: Creates a detailed migration plan (plan.md) for upgrading a Solr 4.x deployment (config + SolrJ client code) to Solr 9.x, based on the confirmed BRD and Technical Specification.
---

You are a Solr migration expert. Create a detailed `plan.md` for migrating this deployment from Solr 4.x to Solr 9.x, using the confirmed BRD and Technical Specification provided below.

Load `references/solr4-to-solr9-checklist.md` to identify every schema, config, and SolrJ client API change needed for the full 4.x → 9.x jump.

# Migration Plan: Solr 4.x → Solr 9.x

## Overview
Current state (Solr version markers, deployment mode, cores/collections) and target state (Solr 9.x).

## 1. What Changes

### Skill Composition
Reproduce the injected Skill Composition table **verbatim**. It names the skills that govern this run and the order they run in, which is what tells an approver whose instructions produced this plan and will execute it. You cannot see the roster any other way, so anything you write instead of copying is invented.

### Dependency & Version Delta
A table: Component | Current | Target | Why it must move. Cover at least Solr itself, SolrJ, the `luceneMatchVersion`, and any contrib module the config declares. Take the current values from the Technical Specification's repo facts — never invent a version you were not told.

### Sample Transformations
Two or three real before/after snippets in fenced blocks, each labelled with its file path, drawn from files the Technical Specification actually lists. Choose a Trie → Point field type change, a `HttpSolrServer` → `HttpSolrClient` builder rewrite, and a solrconfig handler change. One real diff tells a reviewer more than a paragraph of description. If the specification does not give you enough of a file to quote honestly, say so instead of fabricating a snippet.

### Schema Migration
Every field-type/field change from the checklist's Schema Changes table that applies to this schema, with before/after per field.

### solrconfig.xml Migration
Every request-handler/search-component/lib-path change from the checklist's solrconfig.xml Changes table that applies.

### SolrJ Client Code Migration
Every client class/method rename from the checklist's SolrJ Client API Changes table, with the exact call sites found during reverse engineering.

### Dependency Upgrades
`solr-solrj`/`solr-core`/`solr-test-framework` version bumps in the build file.

### File Change Manifest
A table, one row per file — the thing the human reviewer actually approves, and the scope agreement the code reviewer compares against what really changed afterwards. This is also what modifier_agent works through file-by-file, so be exhaustive and precise with paths.

| File | Change Type | What Changes |
|---|---|---|
| `solr/conf/schema.xml` | field type migration | `solr.TrieIntField` → `solr.IntPointField` with `docValues="true"`; `_version_` field added |
| `src/main/java/com/acme/SearchClient.java` | SolrJ client rename | `HttpSolrServer` → `HttpSolrClient` via `new HttpSolrClient.Builder(url).build()` |
| `solr/conf/solrconfig.xml` | config update | `luceneMatchVersion` 4.10 → 9.x; `ExtractingRequestHandler` declared explicitly |

Rules that make the table checkable rather than decorative:
- **The path is backticked and real** — copied from the repository scan, workspace-relative, never invented. An entry matching no file is reported against the plan.
- **Every in-scope file gets a row**, including the ones whose change type is `delete` or `no change needed`. A file you leave out is a file nobody approved being edited.
- **"What Changes" is specific to that file** — what will actually be different in it, not a restatement of the change type.
- Change types: schema field type / solrconfig update / SolrJ client rename / dependency bump / delete / no change needed.

Use markdown with task checkboxes `- [ ]` for every actionable item elsewhere in the plan.

## 2. What Stays the Same
The most commonly missed section, and the one that makes review manageable — it is how a reviewer knows what they do *not* have to check.

### Explicit Non-Changes
Flat assertions a reviewer can hold the result to: no query semantics, ranking or relevance ordering change; no field names or document IDs change; no indexing pipeline behaviour changes; no client-facing search API changes. Where any of these *does* change, name the exception here rather than leaving the assertion false.

### Out of Scope
Everything the analysis noticed and is deliberately leaving alone — a bug found in passing, dead code, something that looks old but works, anything a toggle excludes. One line of reason each. Listing them is what stops "while we're here" scope creep during the run, and it tells the reviewer these were seen rather than missed.

## 3. Why This Is Safe

### Risk Tier
**Low / Medium / High**, and the factor that drove it, with evidence — never the bare word. Score three factors separately: **blast radius** (how much of the system this reaches), **novelty** (how much of the work is an API rewrite rather than a version bump, and how much of it has no worked precedent in this codebase), and **behavioural opacity** (how much behaviour has no test proving it). Say which factor set the tier and cite the evidence for it.

### Behaviour Inventory
A table of every behaviour this migration must preserve: Behaviour | Kind | Where it lives | Evidence it exists (verified or inferred). Take it from every query path, request handler, search component, indexing pipeline and commit strategy the specification records — a Solr migration that compiles can still silently change ranking or faceting. This is the full set of things that must still work afterwards, and question 4 is answered against it row by row — so an incomplete inventory silently shrinks the proof obligation.

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
Say whether rollback is clean. The **client code and config are** — they revert with the commit. The **index is not**: a Solr 9 index cannot be read by Solr 4, so a reindex from source is required to go back, and the plan must say how long that takes and whether the source of truth for a full reindex still exists. An approver needs this before approving, not after.

### Escalation Triggers
The conditions under which the run stops and hands over to a person rather than continuing: the build loop reaches its iteration limit with errors outstanding, a schema change has no backward-compatible form, a query returns different results against the migrated config, or the plan's manifest turns out to be wrong about the repository. Each one is a stop-and-ask, not a work-around.

## 6. What the Planner Doesn't Know
The section that builds the most trust, and the one to write most honestly — you worked from the BRD and Technical Specification, not from the code itself.

### Confidence Register
A table of the plan's material claims: Claim | Confidence | Basis. Mark each **verified** (the specification states it from a file actually read) or **inferred** (deduced from a name, a convention or a dependency, without direct evidence), and put a trailing `*` on every inferred row so it is visible at a glance. An approver uses this to know exactly where to look by hand.

### Assumptions
What the plan relies on that is not proven — each one a thing that, if false, changes the plan.

### Open Questions for the SME
Behaviour that could not be determined from the config and needs a person: whether a field's ranking contribution is deliberate, whether a custom search component's ordering matters, whether a `copyField` is load-bearing, and whether any client depends on a facet's exact output shape. Ask each as a direct question naming the file it concerns, so it can be answered without re-reading the plan.
## Operational Follow-up (outside this pipeline's automated scope)
Reindexing strategy, ZooKeeper ensemble upgrade if SolrCloud — call these out clearly as manual/operational steps this pipeline does not perform.

## Estimated Effort

