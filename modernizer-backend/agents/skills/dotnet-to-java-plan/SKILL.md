---
name: dotnet-to-java-plan
description: Creates a detailed migration plan (plan.md) for rewriting a C# .NET application in Java/Spring Boot, based on the BRD and Technical Specification produced by the RE step.
---

You are a Java migration expert. Create a detailed `plan.md` for rewriting this C# .NET application in Java/Spring Boot, using the provided BRD and Technical Specification.

Load `references/java-project-layout.md` to apply the correct standard Maven project layout and select appropriate Java/Spring libraries for each .NET/NuGet dependency.

# Migration Plan: C# .NET → Java

## Overview
## Repository Structure (proposed Maven layout: `src/main/java`, `src/main/resources`, `src/test/java`)
## Pre-requisites & Tooling
## Phase 1: Project Scaffolding – Maven `pom.xml`, Spring Boot starter dependencies, CI/CD
## Phase 2: Data Layer – JPA entities, Spring Data repositories, Flyway migrations (from EF Core migrations)
## Phase 3: Business Logic – service layer, package-by-package breakdown mapped from C# namespaces
## Phase 4: API Layer – REST controllers, request/response DTOs, validation, exception handling (`@ControllerAdvice`)
## Phase 5: Cross-Cutting Concerns – DI wiring, configuration (`application.yml`), logging, security (Spring Security)
## Phase 6: Background Work & Scheduling – `IHostedService`/`BackgroundService` → `@Scheduled` / async listeners
## Phase 7: Integration & Deployment – Docker multi-stage build, Kubernetes manifests
## Estimated Effort (story points per phase)
## File Change Manifest (every file that needs to change, with target file name)

Use `- [ ]` checkboxes for every actionable item.
