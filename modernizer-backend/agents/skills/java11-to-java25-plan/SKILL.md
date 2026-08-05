---
name: java11-to-java25-plan
description: Creates a detailed migration plan (plan.md) for upgrading a Java 11 application to Java 25, based on the repo_facts produced by scanner_agent.
---

You are a Java migration expert. Create a detailed `plan.md` for migrating this application from Java 11 to Java 25, using the Repository Facts provided below (produced by scanner_agent — you do not have direct access to the codebase).

Load `references/java11-to-java25-checklist.md` to identify every language-level, library, and tooling change needed for the full Java 11 -> 25 jump (this spans far more ground than a single-LTS bump — Java 17's and Java 21's changes are both included).

# Migration Plan: Java 11 → Java 25

## Overview
- Current state (Java 11, build tool, framework versions) and target state (Java 25)
## Pre-requisites
- JDK 25 installation, Maven/Gradle plugin updates, IDE configuration
## Phase 1: Environment & Tooling Setup
- Bump `maven.compiler.source`/`target` (or Gradle `sourceCompatibility`) to 25
- Update the CI JDK distribution
## Phase 2: Dependency Upgrades
- Third-party library version matrix — current version -> Java 25-compatible version (reference the checklist)
- Framework version bump (e.g. Spring Boot 2.7 -> 3.x) if one is in use
- If bumping past Jakarta EE 9: every `javax.*` import (`javax.servlet`, `javax.persistence`, `javax.validation`, `javax.annotation`) must move to `jakarta.*` — list every affected file from the scanner's Namespace Check section
## Phase 3: Language Modernisation (11 → 17 ground)
- Replace anonymous inner classes with lambdas/method references where reasonable
- Convert applicable classes to records; introduce sealed hierarchies where there's a closed set of subtypes
- Adopt text blocks for multi-line strings; switch expressions and pattern-matching `instanceof`
## Phase 4: Language Modernisation (17 → 25 ground)
- Pattern matching for `switch`; sequenced collections API; unnamed variables (`_`)
- Migrate blocking-I/O thread pools to virtual threads (`Executors.newVirtualThreadPerTaskExecutor()`)
## Phase 5: Validation & Rollout
- Real build validation happens automatically in build_loop (mvn compile, iterated with the fixer) — this phase covers what's outside that: test suite run, performance benchmark plan, rollback strategy
## Estimated Effort (by phase and total story points)
## File Change Manifest
- Every file path from the scanner's "File Change Candidates" that is actually in scope, with the change type (language modernisation / namespace migration / dependency bump / no change needed)

Use markdown with task checkboxes `- [ ]` for every actionable item. The File Change Manifest is what modifier_agent will work through file-by-file, so be exhaustive and precise with paths.
