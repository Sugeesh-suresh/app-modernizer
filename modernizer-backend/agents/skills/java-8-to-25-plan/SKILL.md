---
name: java-8-to-25-plan
description: Creates a detailed, strategy-aware migration plan (plan.md) for upgrading a Java 8 application to Java 25, based on the confirmed BRD and Technical Specification.
---

You are a Java migration expert. Create a detailed `plan.md` for migrating this application from Java 8 to Java 25, using the confirmed BRD and Technical Specification provided below — you do not have direct access to the codebase, only what those documents describe.

Load `references/java8-to-java25-checklist.md` to identify every language-level, library, and tooling change needed for the full Java 8 → 25 jump.

The **Migration Strategy** input tells you which of the two plan shapes to produce:

## If Migration Strategy is "bigbang"

Produce a single-pass plan with this shape:

# Migration Plan: Java 8 → Java 25 (Bigbang)

## Overview
Current state (Java 8, build tool, framework versions) and target state (Java 25).
## Pre-requisites
JDK 25 installation, Maven/Gradle plugin updates, IDE configuration.
## Dependency Upgrades
Third-party library version matrix (from the checklist). If `{springboot_upgrade}` is true, add a framework version bump following the checklist's Spring Boot Version Bump section — state explicitly which path applies (Path A: embedded-server JAR, staying on Spring Boot 3.x; or Path B: WAR on an external servlet container, jumping to Spring Boot 4 / Jakarta EE 11 per the `springboot-war-to-boot4` skill) based on the scanner's Packaging & Deployment Model repo fact.
## Language Modernisation
Every applicable item from the checklist's "Language Features Introduced Along the Way" table, in one combined phase.
## JUnit Migration (only if `{junit_upgrade}` is true)
Per the checklist's JUnit 4 → 5 section.
## Validation & Rollout
Real build validation happens automatically in build_loop (mvn/gradle compile, iterated with the fixer) — this section covers what's outside that: test suite run, rollback strategy.
## Estimated Effort
## File Change Manifest
Every in-scope file path with the change type (language modernisation / namespace migration / dependency bump / no change needed).

## If Migration Strategy is "incremental"

Produce a **phased** plan. Each stage is applied, compiled and fixed by its own agents before the next stage starts, so every stage must leave the project compiling.

Stage headings are `## Stage <n>: <title>`. Use the titles below character for character — each stage's modifier agent finds its section by its title. Number the stages you include consecutively, in the order given. `## Phase N: ...` headings only group the stages; nothing parses them.

**Which stages to include**
- If `{springboot_upgrade}` is **true**, emit all eight stages exactly as in the template below.
- If `{springboot_upgrade}` is **false**, leave out every Spring Boot stage and the whole of Phase 4, and number the remaining stages consecutively. The plan then has exactly these four stage headings, in this order: `## Stage 1: Modernize Build Systems (Maven/Gradle)`, `## Stage 2: Automate Code Analysis (OpenRewrite)`, `## Stage 3: Java 8 → Java 17 LTS`, `## Stage 4: Java 17 → Java 25 LTS`. Say in the Overview that the Spring Boot stages were not requested.
- If a stage genuinely has nothing to do for this codebase (e.g. no Spring at all), still emit its heading with "No changes needed — <reason>" and an empty manifest.

**Why the JDK and Spring Boot stages interleave:** every stage must land on a supported JDK/framework combination. Spring Boot 2.7 supports Java 8–21, and Spring Boot 3.x needs Java 17+. So on Java 17 the framework moves to 2.7 and then to 3.x, *before* the jump to Java 25; Spring Boot 4 comes after it. Never plan a Spring Boot 2.x codebase on Java 25.

**WAR → JAR is deliberate:** for the incremental strategy, the checklist's Path A / Path B choice does **not** apply. The app stays a WAR through the Spring Boot 4.x stage and becomes an executable JAR in the final stage, whatever the Packaging & Deployment Model fact says. Use that fact to size the Spring Boot stages, not to skip them.

# Migration Plan: Java 8 → Java 25 (Incremental)

## Overview
Current state (JDK, build tool, Spring / Spring Boot version, packaging and deployment model from the scanner's repo facts) and the phase roadmap below.

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
- On Java 17 (compiler release unchanged): Spring Boot 2.7.x parent / BOM and starters, `SpringBootServletInitializer` composition root, embedded-container starter `provided`, Spring-bootstrap `web.xml` entries retired; `javax.*` untouched; `<packaging>war</packaging>` kept. Governed by `springboot-incremental-upgrade`
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
Goal: Spring Boot 4 on Jakarta EE 11, then leave the external container behind.

## Stage 7: Upgrade to Spring Boot 4.x
- Spring Boot 4.x / Spring Framework 7 / Jakarta EE 11 per the `springboot-war-to-boot4` skill's packaging, namespace and configuration vectors — still a WAR (Tomcat 11+) in this stage
- File Change Manifest for this stage only

## Stage 8: Convert WAR → Executable JAR (Embedded Container)
- Packaging → `jar`, embedded container, `SpringBootServletInitializer` removed, remaining `web.xml` translated and deleted, container-provided resources (JNDI DataSource, context path, TLS, realms) → Spring Boot configuration; static assets → `src/main/resources/static`. If JSPs exist, plan an executable WAR instead and say why
- File Change Manifest for this stage only

## Validation & Rollout
Each stage above is independently built and fixed by its own build loop before the next begins. This section covers what's outside that: the full test suite run after the last stage, the deployment-target change each Spring Boot stage implies (Tomcat 9 → 10.1 → 11 → standalone `java -jar`), and a rollback point per phase.

## Estimated Effort
Per stage, per phase, and total.

---

Use markdown with task checkboxes `- [ ]` for every actionable item. Each stage's File Change Manifest is what that stage's modifier agent will work through file by file — be exhaustive and precise with paths, and do not let changes bleed across stages. A file changed in one stage may need further changes in a later one (e.g. the Java 17 stage and then the Spring Boot 3.x stage); list it again there rather than assuming the earlier stage finished it.
