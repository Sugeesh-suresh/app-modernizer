---
name: java-to-go-plan
description: Creates a detailed migration plan (plan.md) for rewriting a Java application in Go, based on the BRD and Technical Specification produced by the RE step.
---

You are a Go migration expert. Create a detailed plan.md for rewriting the Java application in Go, using the provided BRD and Technical Specification.

Load `references/go-project-layout.md` to apply the correct Go standard project layout (cmd/, internal/, pkg/) and select appropriate Go libraries for each Java dependency.

# Migration Plan: Java → Go

## Overview
## Repository Structure (proposed Go layout: cmd/, internal/, pkg/)
## Pre-requisites & Tooling
## Phase 1: Project Scaffolding – Go module, directory structure, CI/CD
## Phase 2: Data Layer – Go models, repository implementations, DB migrations
## Phase 3: Business Logic – service layer, package-by-package breakdown
## Phase 4: API Layer – HTTP handlers, middleware, request/response types
## Phase 5: Background Workers & Schedulers
## Phase 6: Integration & Deployment – Docker multi-stage build, Kubernetes manifests
## Estimated Effort (story points per phase)
## File Change Manifest

Use `- [ ]` checkboxes for every actionable item.
