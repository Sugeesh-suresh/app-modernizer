---
name: oracle-19c-to-23ai-plan
description: Creates a detailed migration plan (plan.md) for upgrading Oracle 19c SQL/PLSQL source to be 23ai-compatible, based on the confirmed BRD and Technical Specification.
---

You are an Oracle migration expert. Create a detailed `plan.md` for migrating this SQL/PLSQL codebase from Oracle 19c to Oracle 23ai compatibility, using the confirmed BRD and Technical Specification provided below.

Load `references/oracle19c-to-23ai-checklist.md` to identify every compatibility change required and every optional 23ai feature worth proposing.

# Migration Plan: Oracle 19c → Oracle 23ai

## Overview
Current state (Oracle version markers, object counts by type) and target state (Oracle 23ai compatibility).

## 1. What Changes

### Skill Composition
Reproduce the injected Skill Composition table **verbatim**. It names the skills that govern this run and the order they run in, which is what tells an approver whose instructions produced this plan and will execute it. You cannot see the roster any other way, so anything you write instead of copying is invented.

### Dependency & Version Delta
A table: Component | Current | Target | Why it must move. Cover at least the database release, the JDBC driver, and any ORM or connection-pool version the driver change forces. Take the current values from the Technical Specification's repo facts — never invent a version you were not told.

### Sample Transformations
Two or three real before/after snippets in fenced blocks, each labelled with its file path, drawn from files the Technical Specification actually lists. Choose a `LONG`/`LONG RAW` → `CLOB`/`BLOB` column change, an optimizer-pin removal, and a driver-level change in the application. One real diff tells a reviewer more than a paragraph of description. If the specification does not give you enough of a file to quote honestly, say so instead of fabricating a snippet.

### Compatibility Fixes (required)
Every item from the checklist's "Compatibility & Deprecated Constructs" table that applies to objects actually found, with the concrete file/object it applies to.

### Optional 23ai Feature Adoption
Only include items from the checklist's optional table if the BRD's Objectives & Goals section actually calls for them — do not propose speculative rewrites nobody asked for.

### Application/Driver Changes
JDBC driver version bump if applicable.

### File Change Manifest
A table, one row per file — the thing the human reviewer actually approves, and the scope agreement the code reviewer compares against what really changed afterwards. This is also what modifier_agent works through file-by-file, so be exhaustive and precise with paths.

| File | Change Type | What Changes |
|---|---|---|
| `db/schema/orders.sql` | compatibility fix | `LONG RAW` payload column → `BLOB`; dependent `INSERT` statements unchanged |
| `db/packages/pricing.pkb` | optimizer pin removal | `optimizer_features_enable` hint dropped; logic unchanged |
| `pom.xml` | dependency bump | `ojdbc6` → `ojdbc11` |

Rules that make the table checkable rather than decorative:
- **The path is backticked and real** — copied from the repository scan, workspace-relative, never invented. An entry matching no file is reported against the plan.
- **Every in-scope file gets a row**, including the ones whose change type is `delete` or `no change needed`. A file you leave out is a file nobody approved being edited.
- **"What Changes" is specific to that file** — what will actually be different in it, not a restatement of the change type.
- Change types: compatibility fix / optimizer pin removal / 23ai feature adoption / JDBC driver bump / delete / no change needed.

Use markdown with task checkboxes `- [ ]` for every actionable item elsewhere in the plan.

Also everything the analysis noticed and is deliberately leaving alone — a bug found in passing, dead code, something that looks old but works, anything a toggle excludes. One line of reason each. Listing them is what stops "while we're here" scope creep during the run, and it tells the reviewer these were seen rather than missed.

## 2. What Stays the Same
The most commonly missed section, and the one that makes review manageable — it is how a reviewer knows what they do *not* have to check.

### Explicit Non-Changes
Flat assertions a reviewer can hold the result to: no table, column or constraint names change; no data is migrated or transformed; no business logic inside a package or trigger changes; no application API changes. Where any of these *does* change, name the exception here rather than leaving the assertion false.

### Out of Scope
Restate, from the checklist, what this plan will NOT do (database engine upgrade itself, live data migration, any `ALTER SYSTEM`/`ALTER DATABASE`).

## 3. Why This Is Safe

### Risk Tier
**Low / Medium / High**, and the factor that drove it, with evidence — never the bare word. Score three factors separately: **blast radius** (how much of the system this reaches), **novelty** (how much of the work is an API rewrite rather than a version bump, and how much of it has no worked precedent in this codebase), and **behavioural opacity** (how much behaviour has no test proving it). Say which factor set the tier and cite the evidence for it.

### Behaviour Inventory
A table of every behaviour this migration must preserve: Behaviour | Kind | Where it lives | Evidence it exists (verified or inferred). Take it from every SQL path, stored procedure, package, trigger, view and scheduled job the specification records, plus every application query that depends on vendor-specific syntax. A PL/SQL migration that compiles can still change result ordering or null handling. This is the full set of things that must still work afterwards, and question 4 is answered against it row by row — so an incomplete inventory silently shrinks the proof obligation.

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
**Rollback is not clean, and the plan must say so plainly.** Application and driver changes revert with the commit, but a DDL change applied to a database does not: a `LONG` → `CLOB` conversion rewrites stored data, and reversing it needs its own migration plus a backup taken before the change. State for every DDL item whether it is reversible, what the backup requirement is, and what the forward fix is if it goes wrong in production. An approver needs this before approving, not after.

### Escalation Triggers
The conditions under which the run stops and hands over to a person rather than continuing: a DDL change has no reversible form and no backup is confirmed, a query plan changes materially after the optimizer pin is removed, a validation step cannot run, or the plan's manifest turns out to be wrong about the schema. Each one is a stop-and-ask, not a work-around.

## 6. What the Planner Doesn't Know
The section that builds the most trust, and the one to write most honestly — you worked from the BRD and Technical Specification, not from the code itself.

### Confidence Register
A table of the plan's material claims: Claim | Confidence | Basis. Mark each **verified** (the specification states it from a file actually read) or **inferred** (deduced from a name, a convention or a dependency, without direct evidence), and put a trailing `*` on every inferred row so it is visible at a glance. An approver uses this to know exactly where to look by hand.

### Assumptions
What the plan relies on that is not proven — each one a thing that, if false, changes the plan.

### Open Questions for the SME
Behaviour that could not be determined from the SQL and needs a person: whether a result ordering without an `ORDER BY` is relied on, whether an optimizer hint was added for a real production problem, whether a trigger's side effects are depended on elsewhere, and whether any reporting job reads these tables directly. Ask each as a direct question naming the file it concerns, so it can be answered without re-reading the plan.
## Estimated Effort

