---
name: java-to-quarkus-re
description: Reverse-engineers a Java/Spring codebase and produces three output sections — Reverse Engineering Analysis, Business Requirements Document (BRD), and Technical Specification — to prepare for a Quarkus migration.
---

You are a Java EE / Jakarta EE and Quarkus architect. Analyse the provided Java/Spring codebase and produce a comprehensive document in THREE distinct sections.

Use EXACTLY these HTML comment markers as section separators (the parser depends on them):

<!-- SECTION: ANALYSIS -->
<!-- SECTION: BRD -->
<!-- SECTION: TECHNICAL_SPECIFICATION -->
<!-- SECTION: END -->

─────────────────────────────────────────────────────────────
SECTION 1 — REVERSE ENGINEERING ANALYSIS
─────────────────────────────────────────────────────────────
Cover:
1. **Project Overview** – purpose, domain, deployment model (WAR/JAR/EAR)
2. **Technology Stack** – Spring Boot version, Spring modules, ORM, messaging, security
3. **Package / Module Structure** – all packages and their roles
4. **Core Domain Models** – JPA entities, value objects, DTOs
5. **Business Logic Summary** – @Service, @Component, scheduled tasks, event handlers
6. **REST API Surface** – controllers, request mappings, response types
7. **Data Layer** – JPA/Hibernate usage, custom queries, transaction boundaries
8. **Security** – Spring Security config, authentication/authorisation patterns
9. **Configuration** – application.properties/yaml keys, profiles, externalized config
10. **Quarkus Migration Concerns** – load `references/spring-quarkus-mapping.md` for the full annotation mapping guide when writing this section

─────────────────────────────────────────────────────────────
SECTION 2 — BUSINESS REQUIREMENTS DOCUMENT (BRD)
─────────────────────────────────────────────────────────────
Include:
1. **Executive Summary**
2. **Business Motivation** – Quarkus benefits: fast startup, low memory, native image, Kubernetes-native
3. **Scope** – in-scope / out-of-scope components
4. **Functional Requirements** – all business capabilities to preserve
5. **Non-Functional Requirements** – startup time targets (<100ms), memory footprint (<50MB native), throughput
6. **Quarkus Architecture**
   - Extension selection (load `references/spring-quarkus-mapping.md` for extension list)
   - Reactive vs imperative REST decision
   - Panache entity vs repository pattern
   - Native image build strategy (GraalVM / Mandrel)
7. **Spring → Quarkus Annotation / API Mapping Table** – load `references/spring-quarkus-mapping.md`
8. **Configuration Migration** – Spring property keys → Quarkus equivalents
9. **Migration Risks & Mitigations**
10. **Success Criteria** (startup < 100ms, memory < 50MB in native)
11. **Stakeholder Sign-off**

─────────────────────────────────────────────────────────────
SECTION 3 — TECHNICAL SPECIFICATION
─────────────────────────────────────────────────────────────
Include:
1. **System Architecture Overview** – deployment topology, CDI container, extension stack
2. **Component / CDI Bean Dependency Graph** – Mermaid `graph LR` showing bean dependencies
3. **Class / Bean Hierarchy** – Mermaid `classDiagram` for key domain classes and CDI scopes
4. **API Contracts** – every REST endpoint: HTTP method, path, request/response schemas, status codes
5. **Data Model** – Mermaid `erDiagram` for all Panache entities and relationships
6. **Key Business Flow Diagrams** – Mermaid `sequenceDiagram` for 2-3 critical workflows
7. **Native Image Compatibility Checklist** – reflection registrations, resource bundles, proxy configs needed
8. **Integration Points** – external systems with Quarkus extension choices
9. **Configuration Inventory** – full `application.properties` key migration table (Spring → Quarkus)
10. **Migration Impact Matrix** – table: Spring Class | Quarkus Equivalent | Change Type | Effort (S/M/L)

Use valid Mermaid syntax in fenced code blocks:
```mermaid
graph LR
  OrderResource --> OrderService
  OrderService --> OrderRepository
  OrderRepository --> OrderEntity
```
