---
name: tibco-to-springboot-plan
description: Creates a detailed migration plan (plan.md) for migrating a TIBCO BusinessWorks application to Java Spring Boot, based on the BRD and Technical Specification produced by the RE step.
---

You are a TIBCO-to-Spring Boot migration expert. Create a detailed plan.md for migrating the TIBCO BusinessWorks application to Spring Boot, using the provided BRD and Technical Specification.

Load `references/springboot-starters.md` to select the correct Spring Boot starters and dependencies for each TIBCO shared resource and integration pattern found in the codebase.

# Migration Plan: TIBCO BusinessWorks → Spring Boot

## Overview
## Pre-requisites (Java 17+, Spring Boot 3.x, Maven/Gradle, messaging infrastructure)
## Phase 1: Project Scaffolding – Spring Initializr setup, dependency selection
## Phase 2: Configuration Migration – .substvar → application.properties/yaml
## Phase 3: Inbound Triggers – HTTP @RestController, JMS @JmsListener, @Scheduled
## Phase 4: Process-by-Process Migration – each BW process → Spring @Service method
## Phase 5: Data Access – JDBC Execute → Spring Data JPA / JdbcTemplate
## Phase 6: Outbound Integrations – HTTP client (WebClient/RestTemplate), JMS template, File operations
## Phase 7: Error Handling & Dead-Letter – GlobalExceptionHandler, DLQ configuration
## Phase 8: Transaction Management – @Transactional boundaries
## Phase 9: Testing & Validation – MockMvc, embedded brokers, integration tests
## Phase 10: Deployment – Docker, Kubernetes, health checks
## Estimated Effort (story points per phase)
## File Change Manifest (BW process → Spring class mapping)

Use `- [ ]` checkboxes for every actionable item.
