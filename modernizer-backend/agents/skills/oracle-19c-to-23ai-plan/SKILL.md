---
name: oracle-19c-to-23ai-plan
description: Creates a detailed migration plan (plan.md) for upgrading Oracle 19c SQL/PLSQL source to be 23ai-compatible, based on the confirmed BRD and Technical Specification.
---

You are an Oracle migration expert. Create a detailed `plan.md` for migrating this SQL/PLSQL codebase from Oracle 19c to Oracle 23ai compatibility, using the confirmed BRD and Technical Specification provided below.

Load `references/oracle19c-to-23ai-checklist.md` to identify every compatibility change required and every optional 23ai feature worth proposing.

# Migration Plan: Oracle 19c → Oracle 23ai

## Overview
Current state (Oracle version markers, object counts by type) and target state (Oracle 23ai compatibility).

## Compatibility Fixes (required)
Every item from the checklist's "Compatibility & Deprecated Constructs" table that applies to objects actually found, with the concrete file/object it applies to.

## Optional 23ai Feature Adoption
Only include items from the checklist's optional table if the BRD's Objectives & Goals section actually calls for them — do not propose speculative rewrites nobody asked for.

## Application/Driver Changes
JDBC driver version bump if applicable.

## Explicitly Out of Scope
Restate, from the checklist, what this plan will NOT do (database engine upgrade itself, live data migration, any `ALTER SYSTEM`/`ALTER DATABASE`).

## Validation & Rollout
Static validation happens automatically in build_loop (balanced-block + terminator + deprecated-construct scan, iterated with the fixer) — this section covers what's outside that: a real `sqlcl`/`SQL*Plus` compile check and DBA review before production rollout.

## Estimated Effort

## File Change Manifest
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
