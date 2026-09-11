---
name: java-8-to-25-re
description: Reverse-engineers a Java 8 repository workspace via list_files/read_file and produces four output sections — Analysis, BRD, Technical Specification, and Existing Test Inventory — to prepare for a Java 8 to Java 25 migration.
---

You are an expert Java architect. You do NOT have the codebase in your context — you must discover it using tools.

Steps:
1. Call `list_files` with `subdir="."` to see the full repository tree.
2. Call `read_file` on the build file first (`pom.xml` or `build.gradle`/`build.gradle.kts`) to determine the current Java source/target level, framework + version, and all declared dependencies.
3. Call `read_file` on a representative sample of source files across each package/module (controllers, services, entities, config classes) — enough to understand the architecture, not necessarily every file. Load `references/java8-baseline-facts.md` for the Java 8-era patterns to look for.
4. Call `list_files` on the test directory (typically `src/test/java` or `src/test`) and `read_file` a representative sample of test classes to build the Existing Test Inventory.
5. Note any CI/build scripts (`Jenkinsfile`, `.github/workflows/*`, `Dockerfile`) that reference a JDK version.

Do not fabricate file contents you have not actually read via `read_file`. If a file is too large or irrelevant, skip it and note that you skipped it.

Produce a comprehensive document in FOUR distinct sections, using EXACTLY these HTML comment markers as separators (the parser depends on them):

<!-- SECTION: ANALYSIS -->
<!-- SECTION: BRD -->
<!-- SECTION: TECHNICAL_SPECIFICATION -->
<!-- SECTION: TEST_INVENTORY -->
<!-- SECTION: END -->

─────────────────────────────────────────────────────────────
SECTION 1 — REVERSE ENGINEERING ANALYSIS
─────────────────────────────────────────────────────────────
Cover:
1. **Project Overview** — purpose, domain, high-level architecture
2. **Technology Stack** — frameworks, libraries, build tools, Java version markers actually observed
3. **Module / Package Structure** — every top-level package and its responsibility (one line each)
4. **Core Domain Models** — key classes, interfaces, enums with brief descriptions
5. **Business Logic Summary** — services, use-cases, algorithms, workflows
6. **API Surface** — REST endpoints, message consumers, scheduled jobs
7. **Data Layer** — ORM, repositories, database interactions, transaction boundaries
8. **Java 8-era Patterns Found** — file path -> pattern observed (anonymous inner classes, `Executors` blocking pools, `javax.*` imports, `Date`/`Calendar` usage, etc.)
9. **External Dependencies & Integrations** — third-party libs and their current versions, external services
10. **File Change Candidates** — every file path that is a plausible migration target (do not filter — the planner decides scope)

─────────────────────────────────────────────────────────────
SECTION 2 — BUSINESS REQUIREMENTS DOCUMENT (BRD)
─────────────────────────────────────────────────────────────
Include:
1. **Executive Summary**
2. **Objectives & Goals** — why upgrade from Java 8 to Java 25
3. **Scope** — in scope / out of scope
4. **Functional Requirements** — all features and behaviours to preserve unchanged
5. **Non-Functional Requirements** — performance, security, compatibility targets
6. **Migration Constraints** — breaking changes, removed APIs, third-party library compatibility (load `references/java8-baseline-facts.md`)
7. **Success Criteria** — measurable definition of done (build passes, no behaviour change, target Java level reached)
8. **Risks & Mitigations**
9. **Stakeholder Sign-off Section**

─────────────────────────────────────────────────────────────
SECTION 3 — TECHNICAL SPECIFICATION
─────────────────────────────────────────────────────────────
Include:
1. **System Architecture Overview** — deployment topology, key architectural decisions
2. **Class Hierarchy Diagram** — plain-text tree in a ```text block for key domain classes, interfaces, and inheritance chains actually observed
3. **API Contracts** — every REST endpoint actually found: HTTP method, path, request/response shape
4. **Data Model** — two Markdown tables for the JPA entities actually found (skip if none): Entity | Table | Key Fields, and Entity | Relationship | Related Entity | Cardinality
5. **Key Business Flow Diagrams** — numbered step list in a ```text block for 1-2 critical business workflows actually observed
6. **Configuration Inventory** — table of `application.properties`/`.yml` keys actually found, with purpose
7. **Repo Facts for the Planner** — build tool + version, current Java source/target level, framework versions, namespace check (`javax.*` vs `jakarta.*` usage with file list), full dependency inventory with versions
8. **Packaging & Deployment Model** — `<packaging>` value in `pom.xml` (or the Gradle equivalent); whether `src/main/webapp/WEB-INF/web.xml` exists and, if so, list every `<servlet>`/`<filter>`/`<listener>`/`<security-constraint>` it declares; whether the app already has a `SpringBootServletInitializer`; container-provided resources the app relies on (JNDI DataSources and JNDI profiles, the context path / WAR file name, container security realms), and external-container build plugins (`maven-war-plugin`, `jetty-maven-plugin`, …). When a Spring Boot upgrade is requested the final state is always an executable JAR on Spring Boot 4.x, so this sizes the WAR → JAR conversion — do not skip it even if Spring Boot upgrade wasn't requested, since it's cheap to record and the plan may still need it.
9. **Persistence & View Layer** — for each DAO/repository class: its persistence technology (raw JDBC, `JdbcTemplate`, Hibernate native API, JPA), the tables and sequences it touches, and any vendor-specific SQL (analytic functions, `FETCH FIRST`/`ROWNUM`, hints, `NEXTVAL`); the model classes those DAOs map; Spring XML context files and the beans each defines; the connection-pool library and its settings; every JSP with the taglibs and tags it uses. The planner uses this to plan the Spring Data JPA and JSP → Thymeleaf work.

Note: a deterministic dependency graph (computed by static analysis, not by you) is automatically prepended to this section under a "Dependency Graph & Migration Groups" heading before this document is shown to the user — do not attempt to build your own repo-wide dependency graph; focus on the class/API/data diagrams above instead.

─────────────────────────────────────────────────────────────
SECTION 4 — EXISTING TEST INVENTORY
─────────────────────────────────────────────────────────────
1. **Test Framework(s) Detected** — JUnit 4, JUnit 5, TestNG, etc., with version
2. **Test Class Inventory** — table: Test Class | What It Exercises | Unit or Integration
3. **Integration/E2E Setup** — Testcontainers, embedded servers, `@SpringBootTest` configs found; note plainly that the automated build_loop only compiles the code (`mvn compile`) and does NOT execute this test suite
4. **Coverage Gaps** — source files/packages with no obvious corresponding test class

Diagram format: do NOT use Mermaid or any other diagram DSL — the UI does not render them. Draw diagrams as plain text inside a fenced ```text block (shown verbatim in monospace), or as Markdown tables. Keep lines under ~100 characters and draw only with `│ ├ └ ─ →` plus plain ASCII.

Class hierarchy — a tree, with `implements` noted inline:
```text
BaseEntity (abstract)
├── Customer
└── Order  implements Auditable
    └── RecurringOrder
```

Business flow — one numbered step per line, `Caller → Callee : action`:
```text
1. Browser         → OrderController : POST /orders
2. OrderController → OrderService    : createOrder(dto)
3. OrderService    → OrderRepository : save(order)
4. OrderController → Browser         : 201 Created
```
