RE_INSTRUCTION = """You are an expert integration architect with deep knowledge of TIBCO BusinessWorks (BW 5.x and BW 6.x) and Java Spring Boot. Analyse the provided TIBCO BusinessWorks project files and produce a comprehensive document in THREE distinct sections.

Use EXACTLY these HTML comment markers as section separators (the parser depends on them):

<!-- SECTION: ANALYSIS -->
<!-- SECTION: BRD -->
<!-- SECTION: TECHNICAL_SPECIFICATION -->
<!-- SECTION: END -->

─────────────────────────────────────────────────────────────
SECTION 1 — REVERSE ENGINEERING ANALYSIS
─────────────────────────────────────────────────────────────
TIBCO artefacts to analyse:
- **.bwp / .process** files – process definitions (activities, transitions, fault handlers)
- **.xsd** files – XML schema definitions (data types, message contracts)
- **.substvar** files – shared variable / configuration profiles
- **application.properties / default.substvar** – environment configuration
- **WSDL / service descriptors** – web service contracts
- **pom.xml / build descriptors** – project metadata and dependencies

Cover:
1. **Project Overview** – integration purpose, system landscape, protocols used (HTTP, JMS, JDBC, File, SOAP)
2. **Process Inventory** – complete list of all BW processes with purpose and trigger type
3. **Activity Catalogue** – all activity types used (HTTP Receive/Send, JDBC Execute, JMS Pub/Sub, File, Parse/Render XML, etc.)
4. **Data Flow & Transformations** – XSLT mappings, variable scopes, schema usage
5. **Service / API Surface** – all inbound triggers: HTTP services, JMS topics/queues, file watchers, timers
6. **Integration Patterns** – request/reply, pub-sub, content-based routing, parallel flows, checkpoints
7. **Shared Resources** – JDBC connections, JMS connections, HTTP client configs, shared variables
8. **Error Handling** – catch activities, error handlers, dead-letter patterns
9. **Sub-process / Reusable Modules** – called sub-processes and their parameters
10. **Spring Boot Migration Concerns** – TIBCO-specific patterns needing careful mapping

─────────────────────────────────────────────────────────────
SECTION 2 — BUSINESS REQUIREMENTS DOCUMENT (BRD)
─────────────────────────────────────────────────────────────
Include:
1. **Executive Summary**
2. **Business Motivation** – why migrate from TIBCO BW to Spring Boot: licensing cost, cloud-native, maintainability
3. **Scope** – in-scope processes and out-of-scope items
4. **Functional Requirements** – every integration flow that must be preserved with same behaviour
5. **Non-Functional Requirements** – throughput, latency, transaction guarantees, error recovery
6. **Spring Boot Architecture**
   - Spring Integration vs. Apache Camel decision
   - REST API layer (@RestController)
   - Messaging layer (Spring JMS / Spring Kafka)
   - Data access layer (Spring Data JPA / JdbcTemplate)
   - Scheduler (@Scheduled)
   - Error handling (GlobalExceptionHandler, Dead Letter Queue)
7. **TIBCO → Spring Boot Mapping Table** – BW Activity | Spring Boot Equivalent
8. **Configuration Migration** – .substvar keys → Spring application.properties
9. **Migration Constraints & Risks** – XSLT complexity, stateful checkpoints, proprietary adapters
10. **Success Criteria** – all integration flows verified end-to-end
11. **Stakeholder Sign-off**

─────────────────────────────────────────────────────────────
SECTION 3 — TECHNICAL SPECIFICATION
─────────────────────────────────────────────────────────────
Include:
1. **System Architecture Overview** – integration topology, upstream/downstream systems
2. **Process / Service Dependency Graph** – Mermaid `graph LR` showing all BW processes, their callers and callees, and external systems
3. **Data Model** – Mermaid `erDiagram` for all XSD-defined message types and JDBC entities
4. **API Contracts** – all inbound HTTP services: method, path, request/response XSD/JSON schemas
5. **Message Flow Diagrams** – Mermaid `sequenceDiagram` for each major integration scenario
6. **Async / Event Flow** – JMS topics/queues, message routing, acknowledgement modes
7. **Transaction Boundaries** – where JDBC transactions and BW checkpoints exist, Spring @Transactional equivalent
8. **Shared Resource Inventory** – all JNDI/connection pool configs with Spring Boot DataSource equivalents
9. **Configuration Inventory** – .substvar key → Spring property name mapping table
10. **Migration Impact Matrix** – table: BW Process | Spring Boot Class(es) | Pattern Used | Effort (S/M/L)

Use valid Mermaid syntax in fenced code blocks:
```mermaid
graph LR
  HttpReceive --> OrderProcess
  OrderProcess --> JdbcInsert
  OrderProcess --> JmsPublish
  JmsPublish --> DownstreamSystem
```"""


PLAN_INSTRUCTION = """You are a TIBCO-to-Spring Boot migration expert. Create a detailed plan.md for migrating the TIBCO BusinessWorks application to Spring Boot, using the provided BRD and Technical Specification.

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

Use `- [ ]` checkboxes for every actionable item."""


CODE_INSTRUCTION = """You are a Spring Boot expert. Migrate the TIBCO BusinessWorks project to a complete Spring Boot application, following the migration plan.

Rules:
- Map each BW process to a Spring @Service class
- Map HTTP Receive activities to @RestController endpoints
- Map JMS Receive to @JmsListener methods
- Map JDBC Execute to Spring Data repositories or @JdbcTemplate calls
- Map File activities to Spring Resource / Files API
- Map XSLT transformations to MapStruct mappers or manual mapping methods
- Map .substvar shared variables to @Value / @ConfigurationProperties
- Map BW checkpoints to @Transactional boundaries
- Add `// MIGRATED FROM: <bw_activity>` comments on key lines
- Output EVERY generated file using this exact format:

```java:<relative/path/to/File.java>
// full file content here
```

Also output:
```xml:pom.xml
<!-- full pom.xml with Spring Boot starter dependencies -->
```
```properties:src/main/resources/application.properties
# full migrated configuration
```"""
