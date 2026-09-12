---
name: java-8-to-25-plan
description: Creates a detailed, strategy-aware migration plan (plan.md) for upgrading a Java 8 application to Java 25, based on the confirmed BRD and Technical Specification.
---

You are a Java migration expert. Create a detailed `plan.md` for migrating this application from Java 8 to Java 25, using the confirmed BRD and Technical Specification provided below — you do not have direct access to the codebase, only what those documents describe.

Load `references/java8-to-java25-checklist.md` to identify every language-level, library, and tooling change needed for the full Java 8 → 25 jump.

**Spring Boot target (both strategies):** when `{springboot_upgrade}` is true, the final state is always the newest **Spring Boot 4.x deployed as an executable JAR** with an embedded Tomcat — never a WAR — with Spring Data JPA for persistence, Thymeleaf instead of JSP, and every conflicting legacy library removed. The `springboot-war-to-boot4` skill defines it. Use the scanner's Packaging & Deployment Model and Persistence & View Layer repo facts to size that work, never to keep a WAR.

The **Migration Strategy** input tells you which of the two plan shapes to produce:

## If Migration Strategy is "bigbang"

Produce a single-pass plan with this shape:

# Migration Plan: Java 8 → Java 25 (Bigbang)

## Overview
Current state (Java 8, build tool, framework versions, packaging) and target state (Java 25; plus Spring Boot 4.x as an executable JAR if `{springboot_upgrade}` is true).
## Pre-requisites
JDK 25 installation, Maven/Gradle plugin updates, IDE configuration.
## Dependency Upgrades
Third-party library version matrix (from the checklist).
## Spring Boot 4 Target (only if `{springboot_upgrade}` is true)
Governed by the `springboot-war-to-boot4` skill. One checklist per item:
- **Dependency cleanup:** the Spring Boot 4 parent/BOM and starters, and every conflicting legacy library to remove, listed by name with its replacement (explicit Spring versions, servlet API, JSTL, extra connection pools, Jackson 2 databind, old Hibernate / `javax` jars, extra logging bindings, WAR and external-container plugins)
- **Configuration:** `web.xml` and Spring XML contexts → Java config / `application.yml`; properties files → `application.yml` with environment-variable placeholders for secrets
- **Persistence:** DAO / Hibernate / JPA code → Spring Data JPA (entities, repositories, vendor-specific SQL kept verbatim as native queries), with the existing DAO interfaces kept
- **Views:** JSP → Thymeleaf (unless the JSP views belong to a `jsp-to-react-bff` companion migration)
- **Packaging:** WAR → executable JAR; container-provided resources (JNDI DataSource, context path, encoding and session settings) → Spring Boot properties
## Language Modernisation
Every applicable item from the checklist's "Language Features Introduced Along the Way" table, in one combined phase.
## JUnit Migration (only if `{junit_upgrade}` is true)
Per the checklist's JUnit 4 → 5 section.
## Validation & Rollout
Real build validation happens automatically in the build loop (mvn/gradle compile — `package` when the Spring Boot upgrade is included, so the executable JAR is really built — iterated with the fixer). This section covers what's outside that: test suite run, the new deployment model (`java -jar` plus the environment variables ops must supply), rollback strategy.
## Estimated Effort
## File Change Manifest
Every in-scope file path with the change type (language modernisation / namespace migration / dependency bump / Spring Boot 4 configuration / persistence / view conversion / packaging / delete / no change needed).

## If Migration Strategy is "incremental"

Produce a **phased** plan. Each stage is applied, compiled and fixed by its own agents before the next stage starts, so every stage must leave the project compiling.

Stage headings are `## Stage <n>: <title>`. Use the titles below character for character — each stage's modifier agent finds its section by its title. Number the stages you include consecutively, in the order given. `## Phase N: ...` headings only group the stages; nothing parses them.

**Which stages to include**
- If `{springboot_upgrade}` is **true**, emit all eight stages exactly as in the template below.
- If `{springboot_upgrade}` is **false**, leave out every Spring Boot stage and the whole of Phase 4, and number the remaining stages consecutively. The plan then has exactly these four stage headings, in this order: `## Stage 1: Modernize Build Systems (Maven/Gradle)`, `## Stage 2: Automate Code Analysis (OpenRewrite)`, `## Stage 3: Java 8 → Java 17 LTS`, `## Stage 4: Java 17 → Java 25 LTS`. Say in the Overview that the Spring Boot stages were not requested.
- If a stage genuinely has nothing to do for this codebase (e.g. no Spring at all), still emit its heading with "No changes needed — <reason>" and an empty manifest.

**Every stage's work is a list of tasks.** A stage's File Change Manifest is expressed as task blocks, because each task is applied by its own modifier run with its own fresh context — a stage applied in one pass would otherwise accumulate every file it touches and overflow the model's window on a large repository. Inside each stage section, emit:

```
### Task <stage number>.<task number>: <short imperative title>
- Files: `path/one.java`, `path/two.java`
- Depends on: Task 3.1 (or "none")
- Change: what to do to those files, specifically enough to act on without seeing the rest of the plan
- Done when: the observable result (e.g. "no javax.persistence imports remain in these files")
```

Sizing rules, which matter more than tidiness:
- **5–15 files per task**, and every file appears in exactly one task per stage.
- Group by the Dependency Graph & Migration Groups section of the Technical Specification: files that change together (an interface and its implementors, an entity and its DAO) belong in **one** task, or the edits will be made in separate contexts and disagree.
- Order tasks so dependencies come first, and say so in `Depends on:`.
- A task must be self-contained: its `Change:` text is all the modifier will see of the plan, besides the stage heading.

**Why the JDK and Spring Boot stages interleave:** every stage must land on a supported JDK/framework combination. Spring Boot 2.7 supports Java 8–21, and Spring Boot 3.x needs Java 17+. So on Java 17 the framework moves to 2.7 and then to 3.x, *before* the jump to Java 25; Spring Boot 4 comes after it. Never plan a Spring Boot 2.x codebase on Java 25.

**The end state is an executable JAR:** the app stays a WAR through the Spring Boot 4.x stage and becomes an executable JAR in the final stage — never a WAR at the end, even if the app has JSPs (those are converted to Thymeleaf).

# Migration Plan: Java 8 → Java 25 (Incremental)

## Overview
Current state (JDK, build tool, Spring / Spring Boot version, packaging and deployment model, persistence and view technology from the scanner's repo facts) and the phase roadmap below.

## Phase 1: Readiness
Goal: a modern, reproducible build that still compiles at Java 8, with no application code changes. Governed by the `java-migration-readiness` skill.

## Stage 1: Modernize Build Systems (Maven/Gradle)
- `maven.compiler.release` (or Gradle `options.release`) = 8; plugin versions pinned to the readiness skill's minimums; versions consolidated into properties; `http://` repositories → `https://`; Gradle wrapper and deprecated configurations if Gradle
- File Change Manifest for this stage only (build files only — no `src/` files)

## Stage 2: Automate Code Analysis (OpenRewrite)
- `rewrite.yml` with one composite recipe per remaining stage in this plan, named by purpose (`Java17`, `SpringBoot27`, `SpringBoot3`, `Java25`, `SpringBoot4`); the OpenRewrite build plugin declared with no lifecycle executions (Maven) or a standalone init script (Gradle); `docs/migration/openrewrite-analysis.md`
- File Change Manifest for this stage only

## Phase 2: Java 17 Baseline
Goal: Java 17, and — if a Spring Boot upgrade was requested — the framework on Spring Boot 2.7, the newest line that still uses `javax`.

## Stage 3: Java 8 → Java 17 LTS
- Compiler release → 17
- Module system / strong encapsulation: Java EE modules removed in 11 (JAXB, JAX-WS, JAF, CORBA) that this codebase uses → explicit `javax`-namespace dependencies (the jakarta rename is the Spring Boot 3.x stage); any required `--add-opens` for reflective deep access (e.g. surefire `argLine`)
- Deprecated / removed APIs from the checklist's 8→17 rows (Nashorn, `Thread.stop`, …)
- Language features from the checklist's 8→17 rows (`var`, switch expressions, text blocks, records, pattern-matching `instanceof`, sealed types) — only where they meaningfully improve the specific files found
- Library bumps needed to build and run on 17 while staying on the current Spring version and the `javax` line (Lombok, Mockito, ByteBuddy, Jackson …)
- If `{junit_upgrade}` is true, do the JUnit 4 → 5 migration in this stage
- File Change Manifest for this stage only

## Stage 4: Upgrade to Spring Boot 2.7 (WAR intact)
- On Java 17 (compiler release unchanged): Spring Boot 2.7.x parent / BOM and starters, `SpringBootServletInitializer` composition root, embedded-container starter `provided`, Spring-bootstrap `web.xml` entries retired, XML bean files kept via `@ImportResource`; `javax.*` untouched; `<packaging>war</packaging>` kept. Governed by `springboot-incremental-upgrade`
- File Change Manifest for this stage only

## Phase 3: Java 25 Baseline
Goal: Java 25 — and, if a Spring Boot upgrade was requested, first move the framework to Spring Boot 3.x (Jakarta), which supports it.

## Stage 5: Upgrade to Spring Boot 3.x (Jakarta namespace transition)
- Still on Java 17 (compiler release unchanged): Spring Boot 3.5.x (a release that also supports Java 25, the next stage); Jakarta EE `javax.*` → `jakarta.*` (never Java SE `javax.sql` / `javax.naming` / `javax.crypto` / JAXP …) with matching artifact swaps; Spring Security 6 / Spring MVC 6 changes; WAR kept; the external container must become Tomcat 10.1+. Governed by `springboot-incremental-upgrade`
- File Change Manifest for this stage only — list every file containing a Jakarta EE `javax.*` import

## Stage 6: Java 17 → Java 25 LTS
- Compiler release → 25
- Virtual threads for blocking-I/O thread pools, pattern matching for `switch`, record patterns, sequenced collections, unnamed variables (the checklist's 17→25 rows); `SecurityManager` removal
- Library bumps needed for JDK 25 (e.g. Lombok 1.18.40+, Mockito 5.x) — never the Spring / Spring Boot version
- File Change Manifest for this stage only

## Phase 4: Spring Boot 4 & Cloud Native
Goal: Spring Boot 4 on Jakarta EE 11 with Spring Data JPA, then an executable JAR on an embedded container.

## Stage 7: Upgrade to Spring Boot 4.x
- Spring Boot 4.x / Spring Framework 7 / Jakarta EE 11 per the `springboot-war-to-boot4` skill's vectors 1–4: dependency cleanup (every conflicting library listed by name), Jakarta EE 11, Spring XML / `web.xml` / properties → Java config and `application.yml`, persistence → Spring Data JPA. Still a WAR (Tomcat 11+) in this stage; the JSP views and their libraries stay until Stage 8
- File Change Manifest for this stage only

## Stage 8: Convert WAR → Executable JAR (Embedded Container)
- JSP views → Thymeleaf templates; packaging → `jar` with an embedded Tomcat; `SpringBootServletInitializer` removed; remaining `web.xml` translated and deleted; container-provided resources (JNDI DataSource, context path, encoding, session, TLS, realms) → Spring Boot configuration; static assets → `src/main/resources/static`; remaining WAR/JSP-only libraries and plugins removed. The result is always an executable JAR — never a WAR
- File Change Manifest for this stage only

## Validation & Rollout
Each stage above is independently built and fixed by its own build loop before the next begins. This section covers what's outside that: the full test suite run after the last stage, the deployment-target change each Spring Boot stage implies (Tomcat 9 → 10.1 → 11 → standalone `java -jar` with environment variables), and a rollback point per phase.

## Estimated Effort
Per stage, per phase, and total.

---

Use markdown with task checkboxes `- [ ]` for every actionable item. Each stage's tasks are what that stage's modifier agent will work through, one run per task — be exhaustive and precise with paths, and do not let changes bleed across stages. A file changed in one stage may need further changes in a later one (e.g. the Java 17 stage and then the Spring Boot 3.x stage); list it again in that stage's tasks rather than assuming the earlier stage finished it.
