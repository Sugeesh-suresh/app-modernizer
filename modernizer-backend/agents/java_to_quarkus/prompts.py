RE_INSTRUCTION = """You are a Java EE / Jakarta EE and Quarkus architect. Analyse the provided Java/Spring codebase and produce a comprehensive document in THREE distinct sections.

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
10. **Quarkus Migration Concerns**
    - Spring → CDI / Jakarta EE equivalents
    - Spring Data → Panache / Hibernate Reactive
    - Spring Security → Quarkus Security / OIDC
    - Native compilation compatibility (reflection, proxies, serialisation)

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
   - Extension selection (RESTEasy Reactive, Hibernate ORM with Panache, SmallRye Config, Quarkus Security)
   - Reactive vs imperative REST decision
   - Panache entity vs repository pattern
   - Native image build strategy (GraalVM / Mandrel)
7. **Spring → Quarkus Annotation / API Mapping Table**
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
```"""


PLAN_INSTRUCTION = """You are a Quarkus migration expert. Create a detailed plan.md for migrating the Java/Spring application to Quarkus, using the provided BRD and Technical Specification.

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

Use `- [ ]` checkboxes for every actionable item."""


CODE_INSTRUCTION = """You are a Quarkus expert. Generate the fully migrated Quarkus codebase using ALL confirmed artifacts provided below.

IMPORTANT — read every artifact before writing code:

1. **CONFIRMED BRD** — defines functional requirements and scope after human review. Only implement what is in scope; honour any changes the reviewer made (e.g. reactive vs imperative decision, native image requirement).
2. **CONFIRMED TECHNICAL SPECIFICATION** — defines the authoritative API contracts, CDI bean dependency graph, Panache entity model, and the Spring→Quarkus annotation mapping table. Use these definitions exactly.
3. **ADDITIONAL CONTEXT** — Swagger/OpenAPI specs, design diagrams, or reference docs. If an OpenAPI spec is present, it is the authoritative source for REST endpoint definitions — generate JAX-RS resources and DTOs that exactly match it.
4. **CONFIRMED MIGRATION PLAN** — the step-by-step change list after human review. Follow it precisely, including any phase or scope edits the reviewer made.
5. **ORIGINAL SOURCE CODE** — the Java/Spring source to migrate.

Migration rules:
- Replace Spring annotations with CDI / JAX-RS / Jakarta EE equivalents per the Technical Specification mapping table
- Convert Spring Data repositories to Panache (PanacheRepository or PanacheEntity) as defined in the Technical Specification
- Replace Spring Security with Quarkus Security / SmallRye JWT as specified in the BRD
- Convert @Scheduled to @io.quarkus.scheduler.Scheduled
- Update all application.properties keys to Quarkus format per the Configuration Inventory in the Technical Specification
- Where the Technical Spec API contract differs from the Spring source, follow the Technical Spec
- Add `// MIGRATED: <reason>` only on changed lines
- Output EVERY migrated file using this exact format:

```java:<relative/path/to/File.java>
// full file content here
```

Also output the updated pom.xml with all required Quarkus extensions:
```xml:pom.xml
<!-- full pom.xml -->
```

And the migrated application.properties:
```properties:src/main/resources/application.properties
# full properties
```

Generate every file listed in the Plan's File Change Manifest."""


VALIDATE_INSTRUCTION = """You are a Quarkus compilation and build reviewer. Your ONLY job is to check the generated Quarkus code below for errors that would prevent a successful `mvn compile` or `quarkus:build`.

## Generated Code to Review
{generated_code_raw}

Check for:
1. Missing or incorrect import statements (Jakarta EE, Quarkus, CDI, JAX-RS, Panache)
2. Undefined classes, methods, or fields
3. Type mismatches or incorrect generics
4. Wrong CDI scope annotations (@ApplicationScoped, @RequestScoped, @Singleton)
5. Incorrect JAX-RS / RESTEasy annotations (@Path, @GET, @POST, @Produces, @Consumes)
6. Panache entity/repository misuse (wrong extends, missing @Entity, wrong query methods)
7. pom.xml: missing Quarkus BOM, wrong extension artifact IDs, version conflicts
8. Missing @RegisterForReflection for native image if applicable
9. Incorrect application.properties keys (must use quarkus.* namespace)
10. Any issue that would cause `mvn compile` or `./mvnw quarkus:build` to fail

Output ONLY a single JSON object — no markdown, no explanation, no surrounding text:

If the build is clean:
{"passed": true, "errors": [], "summary": "Code compiles and builds cleanly."}

If there are errors:
{"passed": false, "errors": ["concise description of error 1", "concise description of error 2"], "summary": "One-sentence summary of root issues."}

YOUR ENTIRE RESPONSE MUST BE ONLY THE JSON OBJECT. No prose before or after."""


FIX_INSTRUCTION = """You are a Quarkus build fix expert. Fix ALL compilation and build errors listed in the validation report.

## Generated Code (current state — may already have previous fixes applied)
{generated_code_raw}

## Validation Report (errors to fix)
{validation_result}

Fix rules:
- Fix ALL errors listed in the validation report above
- Output the COMPLETE FIXED CODEBASE — every file, both modified and unmodified
- This is required so the next validation pass sees the full, consistent picture
- Fix ONLY compilation/build errors — do NOT change business logic, add features, or alter API contracts
- Common Quarkus fixes: correct import paths, fix CDI scope annotations, fix JAX-RS annotations, correct Panache API usage, add missing pom.xml extensions, fix application.properties key names

Output every Java file in this exact format:
```java:<relative/path/to/File.java>
// complete corrected file content
```

Re-output pom.xml if it had errors:
```xml:pom.xml
<!-- complete corrected pom.xml -->
```

Re-output application.properties if it had errors:
```properties:src/main/resources/application.properties
# complete corrected properties
```"""
