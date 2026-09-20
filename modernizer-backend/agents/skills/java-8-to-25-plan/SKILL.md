---
name: java-8-to-25-plan
description: Creates a detailed, strategy-aware migration plan (plan.md) for upgrading a Java 8 application to Java 25, based on the confirmed BRD and Technical Specification.
---

You are a Java migration expert. Create a detailed `plan.md` for migrating this application from Java 8 to Java 25, using the confirmed BRD and Technical Specification provided below — you do not have direct access to the codebase, only what those documents describe.

Load `references/java8-to-java25-checklist.md` to identify every language-level, library, and tooling change needed for the full Java 8 → 25 jump.

**Spring Boot target (both strategies):** when `{springboot_upgrade}` is true, the final state is always the newest **Spring Boot 4.x deployed as an executable JAR** with an embedded Tomcat — never a WAR — with Spring Data JPA for persistence, Thymeleaf instead of JSP, and every conflicting legacy library removed. The `springboot-war-to-boot4` skill defines it. Use the scanner's Packaging & Deployment Model and Persistence & View Layer repo facts to size that work, never to keep a WAR.

## Every plan answers six questions

A plan is the only artefact a human signs off on, so it has to carry enough for someone to approve or refuse it — not just a list of edits. Both strategies emit these six `##` sections, in this order. The strategy-specific breakdown (stages and tasks, or the bigbang change sections) lives inside question 1; the other five wrap it and are identical in shape either way.

Ground every claim in the BRD, the Technical Specification and the Existing Test Inventory you were given. Where you cannot ground one, that is question 6's job — record it there rather than guessing here. A plan that quietly presents an inference as a fact is worse than one that admits the gap.

### 1. What Changes

`## 1. What Changes`, containing:

- `### Skill Composition` — reproduce the injected Skill Composition table **verbatim**. It names the skills that govern this run and the order they run in, which is what tells an approver whose instructions produced this plan and will execute it. You cannot see the roster any other way, so anything you write instead of copying is invented.
- `### Dependency & Version Delta` — a table: Component | Current | Target | Owning stage | Why it must move. Cover at least the JDK, the build tool, Spring / Spring Boot, Hibernate, Jackson, the JDBC driver, the logging stack, the caching stack, the test stack, and every build plugin whose version changes. Take the current values from the Technical Specification's Repo Facts and Legacy Stack Blockers — never invent a version you were not told.
- `### Sample Transformations` — two or three real before/after snippets in fenced blocks, each labelled with its file path, drawn from files the Technical Specification actually lists. Choose ones that carry the most information: a `javax.*` → `jakarta.*` rename, an API rewrite that is not a version bump (a Hibernate `Interceptor`, an Ehcache 2 `getKeys()` call site, a log4j logger), and a configuration or packaging change if the run includes one. One real diff tells a reviewer more than a paragraph of description. If the specification does not give you enough of a file to quote honestly, say so instead of fabricating a snippet.
- The stage and task breakdown (incremental) or the change sections (bigbang), each closing with its **File Change Manifest** table.

### 2. What Stays the Same

`## 2. What Stays the Same`. The most commonly missed section, and the one that makes review manageable — it is how a reviewer knows what they do *not* have to check.

- `### Explicit Non-Changes` — the contracts this migration does not touch, stated as flat assertions a reviewer can hold the result to: no REST endpoint paths, methods or request/response shapes change; no database schema or table/column names change; no message topic, queue or payload shape changes; no business logic, calculation or validation rule changes; no configuration key names change (or, where any of these *do* change, name the exception here rather than leaving the assertion false). Derive them from the Technical Specification's API Contracts, Data Model and Configuration Inventory.
- `### Out of Scope` — everything the analysis noticed and is deliberately leaving alone: a bug found in passing, dead code, SQL that looks old but works, a deprecated library a toggle excludes, a stage this run does not include. Give each a one-line reason. Listing them is what stops "while we're here" scope creep during the run, and it is also what tells the reviewer these were seen rather than missed.

### 3. Why This Is Safe

`## 3. Why This Is Safe`.

- `### Risk Tier` — **Low / Medium / High**, and the factor that drove it, with evidence. Never the bare word. Score three factors separately: **blast radius** (how much of the system this reaches), **novelty** (how much of the work is an API rewrite rather than a version bump, and how much of it has no worked precedent in this codebase), and **behavioural opacity** (how much behaviour has no test proving it). Say which factor set the tier, and cite the evidence — "High: 14 of 31 files are Ehcache 2 and Hibernate 3 API rewrites, and the Test Inventory shows no test covering the cache layer".
- `### Behaviour Inventory` — a table of every behaviour this migration must preserve: Behaviour | Kind (endpoint / SQL path / message producer / message consumer / scheduled job / batch) | Where it lives | Evidence it exists (verified or inferred). Take it from the Technical Specification's API Contracts, Persistence & View Layer and the Analysis's API Surface. This is the full set of things that must still work afterwards, and question 4 is answered against it row by row — so an incomplete inventory silently shrinks the proof obligation.
- `### Blast Radius` — what outside this repository this change can reach: other repos that consume these endpoints, shared schemas, message topics with other producers or consumers, libraries this repo publishes, and anything that would need to move in the same coordinated release. Where nothing is reachable, say so explicitly — "no published artefacts, no shared schema, no other consumers identified in the specification" — rather than omitting the section.

### 4. How We'll Prove It Worked

`## 4. How We'll Prove It Worked`.

- `### Evidence Plan` — one row per behaviour in the Behaviour Inventory: Behaviour | What proves it survives | Exists today? Name the actual test class from the Existing Test Inventory where one exists, and say what would have to be written where none does.
- `### Coverage Gaps` — the behaviours with nothing proving them, stated plainly and counted: "12 of 31 endpoints have no characterisation test". Take the Test Inventory's own Coverage Gaps section as the starting point and extend it to the Behaviour Inventory. State this up front — a gap discovered at review is a gap that was hidden at approval. Say explicitly whether the run will generate characterisation tests first or proceed without them, since that is a decision the approver is making.
- `### Validation Contract` — the exit criteria this run is held to, taken from the skills that govern it: the build loop compiles (and `package`s, when the Spring Boot upgrade is included) but **does not run the test suite** — say so plainly; every stage must leave the project compiling; the independent code review must find no unapproved change and no unmet manifest row. Name what a human still has to do that no automated step covers.

### 5. What Happens If It Fails

`## 5. What Happens If It Fails`.

- `### Rollback Plan` — whether rollback is **clean**, and if not, what it costs. For a pure Java/Spring source migration it usually is: the artefact is rebuilt from the previous commit and nothing outside the repo has changed. Say so, and name the rollback point per phase. Where anything is not reversible — a schema change, a consumed message, a published artefact — say that explicitly and describe the forward fix, because an approver needs this before approving, not after.
- `### Escalation Triggers` — the conditions under which the run stops and hands over to a person rather than continuing: the build loop reaches its iteration limit with errors outstanding, the same error reappears after the fixer claimed it fixed, a stage cannot be made to compile without changing behaviour, the change audit finds a forbidden fix such as `--add-opens`, or the plan's own manifest turns out to be wrong about the repository. Each one is a stop-and-ask, not a work-around.

### 6. What the Planner Doesn't Know

`## 6. What the Planner Doesn't Know`. The section that builds the most trust, and the one to write most honestly — you worked from the BRD and Technical Specification, not from the code itself.

- `### Confidence Register` — a table of the plan's material claims: Claim | Confidence | Basis. Mark each **verified** (the specification states it from a file that was actually read) or **inferred** (deduced from a name, a convention or a dependency, without direct evidence). Mark every inferred row with a trailing `*` so it is visible at a glance. An approver uses this to know exactly where to look — "Solr usage in the facet service: inferred*" points them at the one thing worth checking by hand.
- `### Assumptions` — what the plan relies on that is not proven: that the test suite passes today, that no consumer depends on undocumented response fields, that the JNDI resources listed are the complete set, that the build runs on a JDK the CI actually has. Each is a thing that, if false, changes the plan.
- `### Open Questions for the SME` — behaviour that could not be determined from the code and needs a person: a bean's intended scope, whether a validation rule is deliberate or vestigial, whether message ordering is required, whether a cache's replication semantics matter, whether vendor-specific SQL is load-bearing. Ask each as a direct question with the file it concerns, so it can be answered without re-reading the plan.

The **Migration Strategy** input tells you which of the two plan shapes to produce:

## If Migration Strategy is "bigbang"

Produce a single-pass plan with this shape:

# Migration Plan: Java 8 → Java 25 (Bigbang)

## Overview
Current state (Java 8, build tool, framework versions, packaging) and target state (Java 25; plus Spring Boot 4.x as an executable JAR if `{springboot_upgrade}` is true).

## 1. What Changes
Open with `### Skill Composition`, `### Dependency & Version Delta` and `### Sample Transformations` as specified above, then the change detail below as `###` subsections, ending with the File Change Manifest.
### Pre-requisites
JDK 25 installation, Maven/Gradle plugin updates, IDE configuration.
### Dependency Upgrades
Third-party library version matrix (from the checklist), including the test stack (`mockito-all`/Mockito 1.x → `mockito-core` 5.x, JUnit 4.13.2, surefire/failsafe 3.2.5+) and the Java 8-era stacks that cannot run on a modern JDK at all — Spring 3.x/4.x, Hibernate 3/4 (`org.springframework.orm.hibernate3`, `org.hibernate.Interceptor`, `Oracle10gDialect`, C3P0), Jackson 1 (`org.codehaus.jackson`) and old Jackson 2 (below 2.12, Afterburner, `enableDefaultTyping()`), Ehcache 2 with its Spring (`EhCacheCacheManager`), Hibernate (`hibernate-ehcache`) and `ehcache-web` integrations, log4j 1.2, cglib/javassist, `ojdbc6`, `google-collections` and old Guava (→ the newest Guava release), runtime-scoped `spring-mock`, and dead build plugins (`maven-svn-revision-number-plugin`, `cargo-maven2-plugin`). Each of these is an API rewrite, not a version bump — size them as such.
### Deprecated Libraries
Per the checklist's "Deprecated Libraries — always called out" section: a table of Library | Version found | Status (deprecated / EOL / insecure) | Replacement | In scope for this run? — covering at least JUnit 3/4 and `junit-vintage-engine` (with the number of JUnit 3 and JUnit 4 test classes), Jackson 1 / old Jackson 2 / Jackson 2 on a Spring Boot 4 target, Ehcache 2 with its integrations, and google-collections / old Guava. List them even when this run does not migrate them (e.g. JUnit when `{junit_upgrade}` is false), so the remaining debt is visible.
### Spring Boot 4 Target (only if `{springboot_upgrade}` is true)
Governed by the `springboot-war-to-boot4` skill. One checklist per item:
- **Dependency cleanup:** the Spring Boot 4 parent/BOM and starters, and every conflicting legacy library to remove, listed by name with its replacement (explicit Spring versions, servlet API, JSTL, extra connection pools, Jackson 2 databind and its now-merged `jsr310`/`jdk8` modules, old Hibernate / `javax` jars, extra logging bindings, WAR and external-container plugins)
- **Jackson 3:** `com.fasterxml.jackson.databind`/`.core` imports → `tools.jackson.*` (annotations unchanged), immutable `JsonMapper.builder()` instead of mutating an `ObjectMapper`, unchecked `JacksonException`, custom `ObjectMapper` / `MappingJackson2HttpMessageConverter` beans rewritten or replaced by `spring.jackson.*`
- **Configuration:** `web.xml` and Spring XML contexts → Java config / `application.yml`; properties files → `application.yml` with environment-variable placeholders for secrets
- **Persistence:** DAO / Hibernate / JPA code → Spring Data JPA (entities, repositories, vendor-specific SQL kept verbatim as native queries), with the existing DAO interfaces kept
- **Views:** JSP → Thymeleaf (unless the JSP views belong to a `jsp-to-react-bff` companion migration)
- **Packaging:** WAR → executable JAR; container-provided resources (JNDI DataSource, context path, encoding and session settings) → Spring Boot properties
### Language Modernisation
Every applicable item from the checklist's "Language Features Introduced Along the Way" table, in one combined phase.
### JUnit Migration (only if `{junit_upgrade}` is true)
Per the checklist's JUnit 3/4 → JUnit Jupiter section. If `{junit_upgrade}` is false, omit this section but keep every JUnit 3/4 test class under Deprecated Libraries as unmigrated tech debt.
### File Change Manifest
A table, one row per file, and the thing the human reviewer actually approves — it is the scope agreement for the run, and the code reviewer compares it against what really changed afterwards:

| File | Change Type | What Changes |
|---|---|---|
| `src/main/java/com/acme/OrderServlet.java` | namespace migration | `javax.servlet.*` → `jakarta.servlet.*` imports; no logic change |
| `src/main/java/com/acme/CacheAdmin.java` | dependency bump | Ehcache 2 → 3: `getKeys()` has no equivalent, so the cache dump endpoint is rewritten to iterate |
| `src/main/java/com/acme/Address.java` | no change needed | plain POJO, nothing to migrate |

Rules that make the table checkable rather than decorative:
- **The path is backticked and real** — copied from the repository scan, workspace-relative, never invented or guessed. An entry matching no file is reported against the plan.
- **Every in-scope file gets a row**, including the ones whose change type is `delete` or `no change needed`. A file you leave out is a file nobody approved being edited.
- **"What Changes" is specific to that file** — what will actually be different in it, not a restatement of the change type. Two files in the same task with different edits get different text.
- Change types: language modernisation / namespace migration / dependency bump / Spring Boot configuration / persistence / view conversion / packaging / test migration / delete / no change needed.

## 2. What Stays the Same
## 3. Why This Is Safe
## 4. How We'll Prove It Worked
## 5. What Happens If It Fails
## 6. What the Planner Doesn't Know
Each exactly as specified in "Every plan answers six questions" above, with the subsections named there. Note for question 4 that real build validation happens automatically in the build loop (mvn/gradle compile — `package` when the Spring Boot upgrade is included, so the executable JAR is really built — iterated with the fixer), and that the loop does not run the test suite; and for question 5 that the deployment model changes to `java -jar` plus the environment variables ops must supply.

## Estimated Effort

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
- When the files in one task get materially different edits, `Change:` says which file gets which — the per-file detail belongs there as well as in the stage's File Change Manifest table.

Each stage then closes with its own **File Change Manifest** table in the format defined above, covering every file that stage's tasks touch. The tasks are what the modifier executes; the table is what the human reviewer approves and what the code reviewer checks the result against, so the two must agree.

**Why the JDK and Spring Boot stages interleave:** every stage must land on a supported JDK/framework combination. Spring Boot 2.7 supports Java 8–21, and Spring Boot 3.x needs Java 17+. So on Java 17 the framework moves to 2.7 and then to 3.x, *before* the jump to Java 25; Spring Boot 4 comes after it. Never plan a Spring Boot 2.x codebase on Java 25.

**The end state is an executable JAR:** the app stays a WAR through the Spring Boot 4.x stage and becomes an executable JAR in the final stage — never a WAR at the end, even if the app has JSPs (those are converted to Thymeleaf).

# Migration Plan: Java 8 → Java 25 (Incremental)

## Overview
Current state (JDK, build tool, Spring / Spring Boot version, packaging and deployment model, persistence and view technology from the scanner's repo facts) and the phase roadmap below.

## 1. What Changes
`### Skill Composition`, `### Dependency & Version Delta` and `### Sample Transformations` exactly as specified above, then `### Deprecated Libraries`, then the phase and stage breakdown that follows. The `## Phase` and `## Stage` headings below stay at `##` level — they are parsed by stage title, so never renumber them or nest them under this section.

### Deprecated Libraries
Per the checklist's "Deprecated Libraries — always called out" section: Library | Version found | Status (deprecated / EOL / insecure) | Replacement | Owning stage (or "not in scope for this run"). Always include JUnit 3/4 and `junit-vintage-engine` (with test-class counts), Jackson 1 / old Jackson 2 / Jackson 2 on a Spring Boot 4 target, Ehcache 2 with its Spring, Hibernate and `ehcache-web` integrations, and google-collections / old Guava — including the ones a toggle keeps out of scope.

## Phase 1: Readiness
Goal: a modern, reproducible build that still compiles at Java 8, with no application code changes. Governed by the `java-migration-readiness` skill.

## Stage 1: Modernize Build Systems (Maven/Gradle)
- `maven.compiler.release` (or Gradle `options.release`) = 8; plugin versions pinned to the readiness skill's minimums; versions consolidated into properties; `http://` repositories → `https://`; Gradle wrapper and deprecated configurations if Gradle
- **Baseline safety net — the test stack goes first:** `mockito-all`/`mockito-core` 1.x → `mockito-core` 4.11.0 (Mockito 1.x mocks via cglib and breaks outright on JDK 9+; 5.x waits for the Java 17 stage, where the runtime floor becomes Java 11+), `junit` 4.x → 4.13.2 (a bridge only — JUnit 3/4 stay flagged as deprecated), surefire/failsafe 2.x → 3.2.5+ (2.x cannot fork a test JVM on JDK 9+). This is the only place a dependency version *value* changes in Phase 1, and it is limited to test-scoped artifacts
- **Dead build cruft removed:** `maven-svn-revision-number-plugin` and any stale SVN `<scm>` URL, `cargo-maven2-plugin` (embedded Jetty 6 won't run on a modern JDK) → current `jetty-maven-plugin` or nothing, duplicate declarations
- File Change Manifest for this stage only (build files, plus test-scoped dependency entries — no `src/main/` files)

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
- **Legacy stacks that cannot run on Java 17 at all** — these are the bulk of this stage's real work, and each is an API rewrite rather than a version bump. Plan one task per stack, listing the files each touches:
  - Spring Framework 3.x/4.x → **5.3.x** (still `javax`; older Spring's bundled ASM cannot read Java 17 class files), and `org.springframework.orm.hibernate3.*` → `hibernate5` (removed in Spring 5). Required even when `{springboot_upgrade}` is false
  - Hibernate 3/4 → **5.6.x**; rewrite any `org.hibernate.Interceptor` (the SPI signatures changed) — prefer `PreInsertEventListener`/`PreUpdateEventListener`; drop `Oracle10gDialect` and `C3P0ConnectionProvider`
  - Jackson 1 (`org.codehaus.jackson`) → Jackson 2 (`com.fasterxml.jackson`): imports, `SerializationConfig.Feature`/`JsonMethod` → `SerializationFeature`/`PropertyAccessor`, and the Spring message-converter bean. Old Jackson 2 in the same task: every Jackson artifact aligned via `jackson-bom` at the newest 2.x, `enableDefaultTyping()` → `activateDefaultTyping(...)` with an allow-list, `jackson-module-afterburner` → `jackson-module-blackbird`
  - Ehcache 2 (`net.sf.ehcache`) → Ehcache 3 (`org.ehcache`): `getKeys()` and `getQuiet()` no longer exist, so any cache-introspection endpoint is rewritten; JGroups replication has no equivalent and becomes a decision, not a port. The integrations in the same task: Spring `EhCacheCacheManager`/`EhCacheManagerFactoryBean` → `JCacheCacheManager` (`javax.cache` is JSR-107 and never becomes `jakarta`), `hibernate-ehcache` → `hibernate-jcache`, `ehcache-web` filters removed and flagged
  - log4j 1.2 → SLF4J + Logback, including `org.apache.log4j.Logger` call sites and the config file
  - Explicit `cglib` / `cglib-nodep` / `javassist` removed (Spring 5 and Hibernate 5 bring their own); AspectJ → newest 1.9.x
  - `ojdbc6`/`ojdbc14` → `ojdbc11`; `google-collections` (and any older Guava) → the newest `com.google.guava:guava` `-jre` release, pinned once via `guava-bom`, with removed Guava APIs rewritten (`Objects.toStringHelper` → `MoreObjects`, `new Stopwatch()` → `Stopwatch.createStarted()`, `MapMaker.makeComputingMap` → `CacheBuilder`, `sameThreadExecutor` → `directExecutor`, executor-less `Futures.transform`/`addCallback`); `spring-mock` removed from runtime scope (real `HttpServletRequestWrapper`/`ServletOutputStream` instead); `javax.xml.bind` usage anywhere in the repo → an explicit JAXB 2.3.x dependency
- Remaining library bumps needed to build on 17 (Lombok, Mockito 4.11 → 5.x, ByteBuddy)
- If `{junit_upgrade}` is true, do the JUnit 3/4 → JUnit Jupiter migration in this stage and remove `junit:junit` and `junit-vintage-engine` once the last test is converted; if false, leave the test code alone and keep the JUnit 3/4 classes listed under Deprecated Libraries
- File Change Manifest for this stage only

## Stage 4: Upgrade to Spring Boot 2.7 (WAR intact)
- On Java 17 (compiler release unchanged): Spring Boot 2.7.x parent / BOM and starters, `SpringBootServletInitializer` composition root, embedded-container starter `provided`, Spring-bootstrap `web.xml` entries retired, XML bean files kept via `@ImportResource`; `javax.*` untouched; `<packaging>war</packaging>` kept. Governed by `springboot-incremental-upgrade`
- File Change Manifest for this stage only

## Phase 3: Java 25 Baseline
Goal: Java 25 — and, if a Spring Boot upgrade was requested, first move the framework to Spring Boot 3.x (Jakarta), which supports it.

## Stage 5: Upgrade to Spring Boot 3.x (Jakarta namespace transition)
- Still on Java 17 (compiler release unchanged): Spring Boot 3.5.x (a release that also supports Java 25, the next stage); Jakarta EE `javax.*` → `jakarta.*` (never Java SE `javax.sql` / `javax.naming` / `javax.crypto` / JAXP …) with matching artifact swaps (including `jackson-module-jaxb-annotations` → `jackson-module-jakarta-xmlbind-annotations` and Ehcache 3's `jakarta` classifier; any surviving Spring `EhCacheCacheManager` must go, since Spring 6 removed it); Spring Security 6 / Spring MVC 6 changes; WAR kept; the external container must become Tomcat 10.1+. Governed by `springboot-incremental-upgrade`
- File Change Manifest for this stage only — list every file containing a Jakarta EE `javax.*` import

## Stage 6: Java 17 → Java 25 LTS
- Compiler release → 25
- Virtual threads for blocking-I/O thread pools, pattern matching for `switch`, record patterns, sequenced collections, unnamed variables (the checklist's 17→25 rows); `SecurityManager` removal
- Library bumps needed for JDK 25 (e.g. Lombok 1.18.40+, Mockito 5.x) — never the Spring Boot version
- **Verification that Phase 2's legacy cleanup really finished:** no `cglib`/`javassist` anywhere in the dependency tree (including transitively) — JDK 17+ strong encapsulation makes them throw `InaccessibleObjectException`, and `--add-opens` is not the fix; no remaining reflective access to JDK internals
- **If `{springboot_upgrade}` is false and the app is on plain Spring 5.3:** Spring must move to 6.x in this stage, since 5.3 does not support Java 25 — which forces the Jakarta EE `javax.*` → `jakarta.*` rename here (never the Java SE `javax.sql`/`javax.naming`/`javax.crypto`/JAXP packages). List every renamed file. Never leave a Spring 5.3 application compiled at release 25
- File Change Manifest for this stage only

## Phase 4: Spring Boot 4 & Cloud Native
Goal: Spring Boot 4 on Jakarta EE 11 with Spring Data JPA, then an executable JAR on an embedded container.

## Stage 7: Upgrade to Spring Boot 4.x
- Spring Boot 4.x / Spring Framework 7 / Jakarta EE 11 per the `springboot-war-to-boot4` skill's vectors 1–4: dependency cleanup (every conflicting library listed by name), Jakarta EE 11, Spring XML / `web.xml` / properties → Java config and `application.yml`, persistence → Spring Data JPA; Jackson 2 → Jackson 3 (`tools.jackson.*`, immutable `JsonMapper`, unchecked `JacksonException`) — Boot 4's Jackson 2 support is deprecated and never the end state; JUnit 4 tests flagged again, since Spring Framework 7 deprecates `SpringRunner` and JUnit 6 deprecates the Vintage engine. Still a WAR (Tomcat 11+) in this stage; the JSP views and their libraries stay until Stage 8
- File Change Manifest for this stage only

## Stage 8: Convert WAR → Executable JAR (Embedded Container)
- JSP views → Thymeleaf templates; packaging → `jar` with an embedded Tomcat; `SpringBootServletInitializer` removed; remaining `web.xml` translated and deleted; container-provided resources (JNDI DataSource, context path, encoding, session, TLS, realms) → Spring Boot configuration; static assets → `src/main/resources/static`; remaining WAR/JSP-only libraries and plugins removed. The result is always an executable JAR — never a WAR
- File Change Manifest for this stage only

## 2. What Stays the Same
## 3. Why This Is Safe
## 4. How We'll Prove It Worked
## 5. What Happens If It Fails
## 6. What the Planner Doesn't Know
Each exactly as specified in "Every plan answers six questions" above, with the subsections named there, placed after the last stage. Two things are specific to a phased run:
- Question 4's Validation Contract: each stage is independently built and fixed by its own build loop before the next begins, and no stage may be left uncompilable — but the loop only compiles, it never runs the test suite. The full suite run after the last stage is a human step.
- Question 5's Rollback Plan: there is a rollback point per phase, which is the main reason to choose this strategy over bigbang — say which phase boundaries are safe to stop at, and note the deployment-target change each Spring Boot stage implies (Tomcat 9 → 10.1 → 11 → standalone `java -jar` with environment variables), since stopping between them leaves a container the ops team must still support.

## Estimated Effort
Per stage, per phase, and total.

---

Use markdown with task checkboxes `- [ ]` for every actionable item. Each stage's tasks are what that stage's modifier agent will work through, one run per task — be exhaustive and precise with paths, and do not let changes bleed across stages. A file changed in one stage may need further changes in a later one (e.g. the Java 17 stage and then the Spring Boot 3.x stage); list it again in that stage's tasks rather than assuming the earlier stage finished it.
