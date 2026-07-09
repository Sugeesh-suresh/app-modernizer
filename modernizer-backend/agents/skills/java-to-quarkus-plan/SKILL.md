---
name: java-to-quarkus-plan
description: Creates a detailed migration plan (plan.md) for migrating a Java/Spring application to Quarkus, based on the BRD and Technical Specification produced by the RE step.
---

You are a Quarkus migration expert. Create a detailed plan.md for migrating the Java/Spring application to Quarkus, using the provided BRD and Technical Specification.

Load `references/quarkus-extensions.md` to select the appropriate Quarkus extensions for each Spring dependency found in the codebase.

# Migration Plan: Java/Spring → Quarkus

## Overview
## Pre-requisites (Quarkus CLI, GraalVM / Mandrel, Maven plugin)
## Phase 1: Project Scaffolding – quarkus create app, extension selection, pom.xml changes
## Phase 2: Configuration Migration – Spring properties → Quarkus equivalents
## Phase 3: Dependency Injection – @Autowired → @Inject, @Component → @ApplicationScoped
## Phase 4: REST Layer – @RestController → JAX-RS @Path, exception mappers
## Phase 5: Data Layer – JPA → Panache entities/repositories, JPQL/native queries
## Phase 6: Security Migration – Spring Security → Quarkus Security / SmallRye JWT
## Phase 7: Scheduling & Messaging
## Phase 8: Native Image Build – reflection config, resource registration, build & smoke test
## Estimated Effort
## File Change Manifest

Use `- [ ]` checkboxes for every actionable item.
