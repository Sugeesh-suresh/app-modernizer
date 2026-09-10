---
name: solr-4-to-9-plan
description: Creates a detailed migration plan (plan.md) for upgrading a Solr 4.x deployment (config + SolrJ client code) to Solr 9.x, based on the confirmed BRD and Technical Specification.
---

You are a Solr migration expert. Create a detailed `plan.md` for migrating this deployment from Solr 4.x to Solr 9.x, using the confirmed BRD and Technical Specification provided below.

Load `references/solr4-to-solr9-checklist.md` to identify every schema, config, and SolrJ client API change needed for the full 4.x → 9.x jump.

# Migration Plan: Solr 4.x → Solr 9.x

## Overview
Current state (Solr version markers, deployment mode, cores/collections) and target state (Solr 9.x).

## Schema Migration
Every field-type/field change from the checklist's Schema Changes table that applies to this schema, with before/after per field.

## solrconfig.xml Migration
Every request-handler/search-component/lib-path change from the checklist's solrconfig.xml Changes table that applies.

## SolrJ Client Code Migration
Every client class/method rename from the checklist's SolrJ Client API Changes table, with the exact call sites found during reverse engineering.

## Dependency Upgrades
`solr-solrj`/`solr-core`/`solr-test-framework` version bumps in the build file.

## Operational Follow-up (outside this pipeline's automated scope)
Reindexing strategy, ZooKeeper ensemble upgrade if SolrCloud — call these out clearly as manual/operational steps this pipeline does not perform.

## Validation & Rollout
Static validation happens automatically in build_loop (XML well-formedness + deprecated-element scan, iterated with the fixer) — this section covers what's outside that: a real Solr smoke test against the new config, rollback strategy.

## Estimated Effort

## File Change Manifest
Every in-scope file path (schema.xml, solrconfig.xml, solr.xml, SolrJ client `.java` files) with the change type. This is what modifier_agent will work through file-by-file — be exhaustive and precise with paths.

Use markdown with task checkboxes `- [ ]` for every actionable item.
