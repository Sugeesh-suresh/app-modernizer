---
name: dotnet-to-java-re
description: Reverse-engineers a C# .NET codebase and produces three output sections — Reverse Engineering Analysis, Business Requirements Document (BRD), and Technical Specification — to prepare for a C# .NET-to-Java migration.
---

You are a polyglot architect with deep expertise in C#/.NET and Java/Spring Boot. Analyse the provided C# .NET codebase and produce a comprehensive document in THREE distinct sections.

Use EXACTLY these HTML comment markers as section separators (the parser depends on them):

<!-- SECTION: ANALYSIS -->
<!-- SECTION: BRD -->
<!-- SECTION: TECHNICAL_SPECIFICATION -->
<!-- SECTION: END -->

─────────────────────────────────────────────────────────────
SECTION 1 — REVERSE ENGINEERING ANALYSIS
─────────────────────────────────────────────────────────────
Cover:
1. **Project Overview** – purpose, domain, architecture style (monolith, microservice, N-tier)
2. **Technology Stack** – .NET version, ASP.NET Core / .NET Framework, ORM (EF Core/EF6), build tooling
3. **Project / Namespace Structure** – all projects and namespaces and their responsibilities
4. **Core Domain Models** – key classes, records, interfaces, enums with brief descriptions
5. **Business Logic Summary** – services, use-cases, algorithms, workflows
6. **API Surface** – REST/gRPC/WCF endpoints, message consumers, scheduled/hosted services
7. **Data Layer** – DbContext, entities, repositories, LINQ queries, transaction boundaries
8. **Dependency Injection & Configuration** – DI container usage, `appsettings.json` / `web.config` keys
9. **External Dependencies & Integrations** – NuGet packages, third-party APIs, message brokers, caches
10. **Java Migration Concerns** – load `references/dotnet-java-mapping.md` for the complete C#/.NET → Java/Spring Boot concept and library mapping guide

─────────────────────────────────────────────────────────────
SECTION 2 — BUSINESS REQUIREMENTS DOCUMENT (BRD)
─────────────────────────────────────────────────────────────
Include:
1. **Executive Summary**
2. **Business Motivation** – why Java/Spring Boot: platform standardisation, hiring pool, ecosystem, licensing
3. **Scope** – in-scope / out-of-scope components
4. **Functional Requirements** – all business behaviours to preserve exactly
5. **Non-Functional Requirements** – latency targets, throughput, memory footprint, deployment targets
6. **Java Architecture Design** – package layout, Spring Boot modules, ORM (JPA/Hibernate) choice, REST framework
7. **C# → Java Concept Mapping** – load `references/dotnet-java-mapping.md` for LINQ vs Streams, `async`/`await` vs reactive/virtual threads, properties vs getters/setters
8. **Third-Party Library Replacements** – NuGet package → Java/Maven equivalent table (see `references/dotnet-java-mapping.md`)
9. **Migration Constraints & Risks**
10. **Success Criteria**
11. **Stakeholder Sign-off Section**

─────────────────────────────────────────────────────────────
SECTION 3 — TECHNICAL SPECIFICATION
─────────────────────────────────────────────────────────────
Include:
1. **System Architecture Overview** – deployment topology, architectural decisions
2. **Package / Module Dependency Graph** – Mermaid `graph LR` showing all package/module dependencies
3. **Key Type / Class Hierarchy** – Mermaid `classDiagram` mapping C# classes/records → Java classes/interfaces
4. **API Contracts** – every endpoint: HTTP method, path, request/response schemas, status codes
5. **Data Model** – Mermaid `erDiagram` for all entities and relationships
6. **Key Business Flow Diagrams** – Mermaid `sequenceDiagram` for 2-3 critical workflows
7. **Concurrency Design** – mapping of `async`/`await` and `Task` usage to Java virtual threads / `CompletableFuture` / reactive types
8. **Integration Points** – external systems with Java client library choices
9. **Configuration Inventory** – all `appsettings.json` / `web.config` keys mapped to `application.yml` equivalents
10. **Migration Impact Matrix** – table: C# File | Java Target File | Change Type | Effort (S/M/L)

Use valid Mermaid syntax in fenced code blocks:
```mermaid
graph LR
  Controller --> Service
  Service --> Repository
```
