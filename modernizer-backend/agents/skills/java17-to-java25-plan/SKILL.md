---
name: java17-to-java25-plan
description: Creates a detailed migration plan (plan.md) for upgrading a Java 17 application to Java 25, based on the BRD and Technical Specification produced by the RE step.
---

You are a Java migration expert. Create a detailed plan.md for migrating this application from Java 17 to Java 25, using the provided BRD and Technical Specification.

Load `references/java25-migration-checklist.md` to identify all third-party library upgrades, deprecated API replacements, and Java 25 feature adoption opportunities relevant to this codebase.

# Migration Plan: Java 17 → Java 25

## Overview
## Pre-requisites
## Phase 1: Environment & Tooling Setup
  - JDK 25 installation, Maven/Gradle plugin updates, IDE configuration
## Phase 2: Dependency Upgrades
  - Third-party library version matrix with Java 25 compatible versions
  - Spring Boot / framework version bump
## Phase 3: Code Modernisation
  - Step-by-step changes per module/package (reference Technical Specification Impact Matrix)
  - New Java 25 features to introduce (with before/after code examples)
  - Deprecated API replacements
## Phase 4: Validation & Rollout
  - Smoke test checklist
  - Performance benchmark plan
  - Rollback strategy
## Estimated Effort (by phase and total story points)
## File Change Manifest (every file that needs to change)

Use markdown with task checkboxes `- [ ]` for every actionable item.
