# Migration Plan: Java 8 → Java 25 (Incremental)

## Overview
`acme-orders` is a Java 8 order-management web application: Maven, Spring Framework 4.3.30, Hibernate 3.6, packaged as a WAR and deployed to an external Tomcat 7 with a JNDI DataSource. Persistence is Hibernate native API behind hand-written DAOs; views are 14 JSPs with JSTL. Caching is Ehcache 2 with JGroups replication; logging is log4j 1.2; JSON is Jackson 1 (`org.codehaus.jackson`).

Target state: Java 25, Spring Boot 4.x as an executable JAR on an embedded Tomcat, Spring Data JPA, Thymeleaf views. A Spring Boot upgrade **was** requested; a JUnit upgrade **was not**, so the 41 JUnit 4 test classes stay as-is and are carried as tech debt.

Roadmap: Phase 1 readiness (build, still Java 8) → Phase 2 Java 17 + Spring Boot 2.7 → Phase 3 Spring Boot 3.x + Java 25 → Phase 4 Spring Boot 4 + executable JAR.

## 1. What Changes

### Skill Composition

| # | Skill | What it governs in this run |
|---|---|---|
| 1 | `java-8-to-25-re` | Reverse-engineered this repository into the confirmed BRD, Technical Specification and Test Inventory |
| 2 | `java-8-to-25-plan` | Produces this plan |
| 3 | `java-migration-readiness` | Incremental only — Stages 1-2: build modernisation, the test-stack safety net and OpenRewrite setup |
| 4 | `springboot-incremental-upgrade` | Incremental only, and only when a Spring Boot upgrade was requested — Stages 4-5: Spring Boot 2.7, then 3.x with the Jakarta rename |
| 5 | `springboot-war-to-boot4` | Only when a Spring Boot upgrade was requested — the Spring Boot 4.x target and the WAR to executable-JAR conversion |
| 6 | `java-8-to-25-modify` | Applies each task's file changes to the workspace |
| 7 | `java-8-to-25-validate` | Compiles (and packages) the workspace after each stage |
| 8 | `java-8-to-25-fix` | Repairs build errors inside the build loop |
| 9 | `code-review` | Independent review of the result against this plan's manifest |
| 10 | `java-8-to-25-report` | Produces the final migration report |

### Dependency & Version Delta

| Component | Current | Target | Owning stage | Why it must move |
|---|---|---|---|---|
| JDK (`maven.compiler.release`) | 1.8 | 25 | Stages 3, 6 | The goal of the migration |
| Spring Framework | 4.3.30 | 7.x (via Boot 4) | Stages 3, 4, 5, 7 | 4.3's bundled ASM cannot read Java 17 class files |
| Spring Boot | none | 4.x | Stages 4, 5, 7 | Requested; ends as an executable JAR |
| Hibernate ORM | 3.6.10 | 7.x (via Spring Data JPA) | Stages 3, 7 | `orm.hibernate3` was removed in Spring 5 |
| Jackson | 1.9.13 (`org.codehaus.jackson`) | 3.x (`tools.jackson`) | Stages 3, 7 | Jackson 1 is EOL; Boot 4 ships Jackson 3 |
| Ehcache | 2.10.6 (`net.sf.ehcache`) | 3.10.x (`org.ehcache`) | Stage 3 | EOL; `getKeys()`/`getQuiet()` do not exist in 3 |
| Logging | log4j 1.2.17 | SLF4J 2.x + Logback | Stage 3 | log4j 1.2 is EOL |
| Oracle JDBC | `ojdbc6` | `ojdbc11` | Stage 3 | `ojdbc6` will not run on a modern JDK |
| Guava | `google-collections` 1.0 | newest `guava` `-jre` | Stage 3 | Abandoned; same packages as Guava |
| Bytecode | `cglib-nodep` 2.2, `javassist` 3.12 | **removed** | Stage 3 | `InaccessibleObjectException` under JDK 17+ |
| Mockito | `mockito-all` 1.9.5 | `mockito-core` 4.11.0 → 5.x | Stages 1, 3 | 1.x mocks via cglib, breaks on JDK 9+ |
| Surefire / Failsafe | 2.12 | 3.2.5+ | Stage 1 | 2.x cannot fork a test JVM on JDK 9+ |
| Servlet container | Tomcat 7 (external) | embedded Tomcat 11 | Stages 4, 5, 7, 8 | Tracks the Boot line; ends embedded |
| JUnit | 4.8.2 (41 classes) | 4.13.2 only | Stage 1 | JUnit upgrade **not** requested — bridge bump only |

### Sample Transformations

`src/main/java/com/acme/orders/web/OrderServlet.java` — namespace, Stage 5:

```java
// before
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
// after
import jakarta.servlet.http.HttpServlet;
import jakarta.servlet.http.HttpServletRequest;
```

`src/main/java/com/acme/orders/cache/CacheAdminController.java` — an API rewrite, not a version bump, Stage 3:

```java
// before — Ehcache 2: getKeys() returns every key
List keys = cache.getKeys();
for (Object k : keys) { Element e = cache.getQuiet(k); report.add(k, e.getObjectValue()); }

// after — Ehcache 3 has no key listing; the Cache is Iterable<Cache.Entry<K,V>>
for (Cache.Entry<String, OrderSummary> e : cache) { report.add(e.getKey(), e.getValue()); }
```

This one changes observable behaviour: Ehcache 2's `getQuiet()` read without touching statistics or TTL; the Ehcache 3 iteration does not offer that guarantee. Flagged under Open Questions.

`src/main/resources/log4j.properties` → `src/main/resources/logback.xml` — Stage 3. Parameterised messages replace concatenation: `log.debug("order=" + id)` becomes `log.debug("order={}", id)`.

### Deprecated Libraries

| Library | Version found | Status | Replacement | Owning stage |
|---|---|---|---|---|
| JUnit 4 | 4.8.2, 41 test classes | Deprecated | JUnit Jupiter | **Not in scope for this run** (toggle off) |
| Jackson 1 | 1.9.13 | EOL | Jackson 2 → 3 | Stage 3, then 7 |
| Ehcache 2 | 2.10.6 | EOL | Ehcache 3 | Stage 3 |
| `hibernate-ehcache` | 3.6.10 | Removed in Hibernate 6 | `hibernate-jcache` | Stage 3 |
| `ehcache-web` | 2.0.4 | No equivalent | Removed, flagged | Stage 3 |
| google-collections | 1.0 | Abandoned | Newest Guava | Stage 3 |
| log4j 1.2 | 1.2.17 | EOL | SLF4J + Logback | Stage 3 |
| `mockito-all` | 1.9.5 | Removed | `mockito-core` | Stage 1 |
| `cargo-maven2-plugin` | 1.4.5 | Dead | Removed | Stage 1 |

### File Change Manifest

Every file this migration touches, across all eight stages. One row per file; a file touched by two stages carries both.

**Build and analysis files**

| File | Change Type | Owning Stage | What Changes |
|---|---|---|---|
| `pom.xml` | dependency bump, packaging | Stages 1, 2, 3, 4, 5, 6, 7, 8 | S1: `release`=8, plugins pinned, versions to properties, test stack bumped (`mockito-all`→`mockito-core` 4.11.0, JUnit 4.13.2, surefire/failsafe 3.2.5), `maven-svn-revision-number-plugin` and `cargo-maven2-plugin` deleted. S2: `rewrite-maven-plugin`, no executions bound. S3: Spring 5.3.39, Hibernate 5.6.15, Jackson 2.17 via BOM, Ehcache 3, Logback, Guava BOM, `ojdbc11`, Mockito 5, `release`=17; cglib/javassist/google-collections/log4j removed. S4: Boot 2.7.18 parent, container starter `provided`. S5: Boot 3.5.x, Jakarta modules. S6: `release`=25. S7: Boot 4.x parent, conflicting libs removed, `data-jpa` starter. S8: `<packaging>jar</packaging>`, `spring-boot-maven-plugin`, Thymeleaf starter; JSP/JSTL and WAR plugins removed |
| `rewrite.yml` | language modernisation | Stage 2 | New. Five composite recipes — `Java17`, `SpringBoot27`, `SpringBoot3`, `Java25`, `SpringBoot4` — one per remaining stage |
| `docs/migration/openrewrite-analysis.md` | language modernisation | Stage 2 | New. Per-recipe expected touch points and the exact dry-run command for each |

**Configuration and composition root**

| File | Change Type | Owning Stage | What Changes |
|---|---|---|---|
| `src/main/java/com/acme/orders/Application.java` | Spring Boot configuration, packaging | Stages 4, 8 | S4: new — `SpringBootServletInitializer` composition root. S8: initializer removed, plain `SpringApplication.run` |
| `src/main/java/com/acme/orders/config/AppConfig.java` | dependency bump | Stage 3 | Spring 5.3 configuration API changes |
| `src/main/java/com/acme/orders/config/HibernateConfig.java` | dependency bump | Stage 3 | `orm.hibernate3.LocalSessionFactoryBean`/`HibernateTransactionManager`/`HibernateTemplate` → `orm.hibernate5.*`; `Oracle10gDialect` setting dropped; audit `Integrator` registered |
| `src/main/java/com/acme/orders/config/CacheConfig.java` | dependency bump | Stage 3 | `EhCacheCacheManager`/`EhCacheManagerFactoryBean` → `JCacheCacheManager` over Ehcache 3's JSR-107 provider |
| `src/main/java/com/acme/orders/config/WebConfig.java` | dependency bump, Spring Boot configuration | Stages 3, 7 | S3: `MappingJacksonHttpMessageConverter` bean rewritten as `MappingJackson2HttpMessageConverter`. S7: custom `ObjectMapper` bean dropped in favour of `spring.jackson.*` properties |
| `src/main/java/com/acme/orders/config/JndiConfig.java` | no change needed | — | Uses `javax.sql.DataSource` and `javax.naming.InitialContext` — Java SE, never part of the Jakarta rename. Its JNDI lookup is replaced by configuration in Stage 8, but this file is not edited |

**Web tier**

| File | Change Type | Owning Stage | What Changes |
|---|---|---|---|
| `src/main/java/com/acme/orders/web/OrderServlet.java` | dependency bump, namespace migration | Stages 3, 5 | S3: `org.apache.log4j.Logger` → `org.slf4j.Logger`, concatenation → `{}` parameters. S5: `javax.servlet.*` → `jakarta.servlet.*`. No logic change in either; all 5 routes keep their paths and payloads |
| `src/main/java/com/acme/orders/web/OrderFilter.java` | namespace migration | Stage 5 | `javax.servlet.Filter`/`FilterChain` → `jakarta.servlet.*` |
| `src/main/java/com/acme/orders/web/OrderJsonController.java` | dependency bump | Stages 3, 7 | S3: `org.codehaus.jackson.*` → `com.fasterxml.jackson.*`; `SerializationConfig.Feature` → `SerializationFeature`; `JsonMethod` → `PropertyAccessor`. S7: → `tools.jackson.*`; `JsonProcessingException` → unchecked `JacksonException`. JSON field names unchanged throughout |
| `src/main/java/com/acme/orders/web/ProductJsonController.java` | dependency bump | Stages 3, 7 | Same Jackson 1 → 2 → 3 path as `OrderJsonController`; field names unchanged |
| `src/main/java/com/acme/orders/cache/CacheAdminController.java` | dependency bump | Stage 3 | Ehcache 2 → 3: `getKeys()` and `getQuiet()` have no equivalent, so the `GET /admin/cache/dump` endpoint is rewritten to iterate `Cache.Entry`. **Behavioural change** — the Ehcache 2 read did not touch statistics or TTL; the Ehcache 3 iteration gives no such guarantee. Response shape unchanged |

**Domain, persistence and services**

| File | Change Type | Owning Stage | What Changes |
|---|---|---|---|
| `src/main/java/com/acme/orders/model/Order.java` | namespace migration | Stage 5 | `javax.persistence.*` → `jakarta.persistence.*`; no mapping or column change |
| `src/main/java/com/acme/orders/model/OrderLine.java` | namespace migration | Stage 5 | `javax.persistence.*` → `jakarta.persistence.*` |
| `src/main/java/com/acme/orders/model/Product.java` | namespace migration | Stage 5 | `javax.persistence.*` and `javax.validation.*` → `jakarta.*`; constraint annotations keep their messages |
| `src/main/java/com/acme/orders/model/Address.java` | no change needed | — | Plain POJO, no legacy API, no JPA annotations |
| `src/main/java/com/acme/orders/dao/OrderDao.java` | namespace migration | Stage 5 | `javax.persistence.EntityManager` → `jakarta.persistence.EntityManager`. The interface itself is kept in Stage 7 so callers are untouched |
| `src/main/java/com/acme/orders/dao/OrderDaoImpl.java` | persistence | Stage 7 | Hibernate native API → Spring Data JPA behind `OrderRepository`. The three Oracle-specific queries (`ROWNUM`, `FETCH FIRST`, `seq_order.NEXTVAL`) are kept **byte-identical** as `@Query(nativeQuery = true)` |
| `src/main/java/com/acme/orders/dao/ProductDao.java` | persistence | Stage 7 | Interface kept; implementation delegates to `ProductRepository` |
| `src/main/java/com/acme/orders/dao/ProductDaoImpl.java` | persistence | Stage 7 | Hibernate native API → Spring Data JPA. The `RANK() OVER` analytic query kept byte-identical as a native query |
| `src/main/java/com/acme/orders/repository/OrderRepository.java` | persistence | Stage 7 | New. `JpaRepository<Order, Long>` behind the existing `OrderDao` interface |
| `src/main/java/com/acme/orders/repository/ProductRepository.java` | persistence | Stage 7 | New. `JpaRepository<Product, Long>` behind the existing `ProductDao` interface |
| `src/main/java/com/acme/orders/audit/AuditInterceptor.java` | dependency bump | Stage 3 | `org.hibernate.Interceptor`'s `onSave`/`onFlushDirty` signatures changed across 3 → 5. Replaced by `PreInsertEventListener` + `PreUpdateEventListener` registered via an `Integrator`. The `modified_by` thread-local mechanism and the audit columns written are preserved exactly |
| `src/main/java/com/acme/orders/cache/OrderCacheService.java` | dependency bump | Stage 3 | Ehcache 2 `Element` wrapper API → Ehcache 3 `get`/`put` returning the value directly |
| `src/main/java/com/acme/orders/service/OrderService.java` | language modernisation | Stage 6 | `get(0)`/`get(size()-1)` → sequenced-collection accessors. No behaviour change |
| `src/main/java/com/acme/orders/service/PricingService.java` | language modernisation | Stage 6 | Discount dispatch `if/else` chain → pattern matching for `switch`. Every branch outcome identical |
| `src/main/java/com/acme/orders/batch/NightlyReconciliation.java` | language modernisation | Stage 6 | Fixed thread pool blocking on JDBC → virtual threads. Schedule (02:00) and logic unchanged |
| `src/main/java/com/acme/orders/util/OrderKeys.java` | dependency bump | Stage 3 | `Objects.toStringHelper` → `MoreObjects.toStringHelper` (removed from modern Guava) |
| `src/main/java/com/acme/orders/util/Timing.java` | dependency bump | Stage 3 | `new Stopwatch()` → `Stopwatch.createStarted()`; `elapsedMillis()` → `elapsed(TimeUnit.MILLISECONDS)` |
| _23 files under_ `src/main/java/com/acme/orders/` | dependency bump | Stage 3 | `org.apache.log4j.Logger` → `org.slf4j.Logger` + `LoggerFactory.getLogger(X.class)`; `"order=" + id` → `"order={}", id`. Logger names and levels preserved. Listed individually in Task 3.5 |

**Resources and webapp**

| File | Change Type | Owning Stage | What Changes |
|---|---|---|---|
| `src/main/resources/ehcache.xml` | dependency bump, namespace migration | Stages 3, 5 | S3: Ehcache 3 schema; cache names, sizes and TTLs carried over; **the JGroups replication block is removed with no replacement** — see Open Questions. S5: `jakarta` classifier variant of the schema |
| `src/main/resources/log4j.properties` | delete | Stage 3 | Replaced by `logback.xml` |
| `src/main/resources/logback.xml` | dependency bump | Stage 3 | New. Appenders, levels and the rolling policy carried over from `log4j.properties` unchanged |
| `src/main/resources/application.properties` | Spring Boot configuration, delete | Stages 4, 7 | S4: new — DataSource, JPA and server properties. S7: replaced by `application.yml` |
| `src/main/resources/application.yml` | Spring Boot configuration, packaging | Stages 7, 8 | S7: new — every key name from `application.properties` preserved, secrets become env-var placeholders. S8: JNDI DataSource → `spring.datasource.*`, plus context path, encoding, session timeout, TLS and security realm |
| `src/main/webapp/WEB-INF/web.xml` | dependency bump, namespace migration, delete | Stages 3, 4, 5, 8 | S3: the two `ehcache-web` page-caching filters removed. S4: Spring bootstrap servlet/listener entries retired. S5: schema → `jakarta.ee` namespace, `version="6.0"`. S8: fully translated into Spring Boot configuration and deleted |
| _14 files_ `src/main/webapp/WEB-INF/jsp/*.jsp` | delete | Stage 8 | Replaced by Thymeleaf templates |
| _14 files_ `src/main/resources/templates/*.html` | view conversion | Stage 8 | New. Markup, form field names and validation messages preserved exactly; JSTL → `th:each`/`th:if`/`th:text` |
| _9 files_ `src/main/webapp/static/` | packaging | Stage 8 | Moved to `src/main/resources/static/`; contents unchanged |

**Not touched, and deliberately so** — see question 2 for the reasoning: `src/main/java/com/acme/orders/legacy/XmlExportService.java` (possible dead code, external caller unconfirmed), and all 41 JUnit 4 test classes under `src/test/java/` (JUnit upgrade not requested).

## Phase 1: Readiness
Goal: a modern, reproducible build that still compiles at Java 8, with no application code changes.

## Stage 1: Modernize Build Systems (Maven/Gradle)

### Task 1.1: Pin plugin versions and consolidate properties
- Files: `pom.xml`
- Depends on: none
- Change: set `maven.compiler.release` = 8; pin compiler/surefire/failsafe/war plugins to the readiness minimums; move every version literal into `<properties>`; rewrite the two `http://` repository URLs to `https://`
- Done when: `mvn -q validate` succeeds and no plugin is left unversioned

### Task 1.2: Modernise the test stack (the safety net)
- Files: `pom.xml`
- Depends on: Task 1.1
- Change: `mockito-all` 1.9.5 → `mockito-core` 4.11.0 (test scope); `junit` 4.8.2 → 4.13.2; surefire and failsafe → 3.2.5. Test-scoped artifacts only — no `src/main/` file changes in this stage
- Done when: `mvn -q test-compile` succeeds on JDK 8 and no `mockito-all` remains

### Task 1.3: Delete dead build cruft
- Files: `pom.xml`
- Depends on: Task 1.1
- Change: remove `maven-svn-revision-number-plugin` and the stale SVN `<scm>` URL; remove `cargo-maven2-plugin` (embedded Jetty 6); de-duplicate the two `commons-lang` declarations
- Done when: no removed plugin appears in `mvn dependency:tree`


## Stage 2: Automate Code Analysis (OpenRewrite)

### Task 2.1: Declare the OpenRewrite recipes and the analysis doc
- Files: `pom.xml`, `rewrite.yml`, `docs/migration/openrewrite-analysis.md`
- Depends on: Task 1.1
- Change: add `rewrite.yml` with one composite recipe per remaining stage (`Java17`, `SpringBoot27`, `SpringBoot3`, `Java25`, `SpringBoot4`); declare `rewrite-maven-plugin` with no lifecycle executions; write the analysis doc naming each recipe's expected touch points and its dry-run command
- Done when: `mvn rewrite:dryRun -Drewrite.activeRecipe=Java17` runs and writes a patch without modifying sources


## Phase 2: Java 17 Baseline
Goal: Java 17, with the framework on Spring Boot 2.7 — the newest line that still uses `javax`.

## Stage 3: Java 8 → Java 17 LTS

### Task 3.1: Raise Spring Framework to 5.3.x and Hibernate to 5.6.x
- Files: `pom.xml`, `src/main/java/com/acme/orders/config/HibernateConfig.java`, `src/main/java/com/acme/orders/config/AppConfig.java`
- Depends on: none
- Change: every `org.springframework:spring-*` → 5.3.39 (still `javax`); `hibernate-core` → 5.6.15; rewrite `org.springframework.orm.hibernate3.LocalSessionFactoryBean` / `HibernateTransactionManager` / `HibernateTemplate` onto `org.springframework.orm.hibernate5`; delete the explicit `cglib-nodep` and `javassist` dependencies. Never go past Spring 5.3 in this stage
- Done when: no `org.springframework.orm.hibernate3` import remains and `cglib` is absent from `mvn dependency:tree`

### Task 3.2: Rewrite the Hibernate Interceptor onto event listeners
- Files: `src/main/java/com/acme/orders/audit/AuditInterceptor.java`, `src/main/java/com/acme/orders/config/HibernateConfig.java`
- Depends on: Task 3.1
- Change: `org.hibernate.Interceptor`'s `onSave`/`onFlushDirty` signatures changed across 3 → 5. Replace `AuditInterceptor` with `PreInsertEventListener` + `PreUpdateEventListener` registered via an `Integrator`, preserving the audit columns written today. Drop the `Oracle10gDialect` setting and let Hibernate auto-detect from the connection
- Done when: `AuditInterceptor` no longer implements `org.hibernate.Interceptor` and audit columns are still written on insert and update

### Task 3.3: Jackson 1 → Jackson 2
- Files: `src/main/java/com/acme/orders/web/OrderJsonController.java`, `src/main/java/com/acme/orders/web/ProductJsonController.java`, `src/main/java/com/acme/orders/config/WebConfig.java`, `pom.xml`
- Depends on: Task 3.1
- Change: `org.codehaus.jackson.*` → `com.fasterxml.jackson.*`; `SerializationConfig.Feature` → `SerializationFeature`, `JsonMethod` → `PropertyAccessor`; rewrite the `MappingJacksonHttpMessageConverter` bean as `MappingJackson2HttpMessageConverter`; align every Jackson artifact via `jackson-bom` 2.17.x. The converter bean is a full rewrite — the enums have no 1:1 replacement
- Done when: no `org.codehaus.jackson` import remains and the JSON endpoints still serialise the same field names

### Task 3.4: Ehcache 2 → Ehcache 3 and its integrations
- Files: `src/main/java/com/acme/orders/cache/CacheAdminController.java`, `src/main/java/com/acme/orders/cache/OrderCacheService.java`, `src/main/java/com/acme/orders/config/CacheConfig.java`, `src/main/resources/ehcache.xml`, `pom.xml`, `src/main/webapp/WEB-INF/web.xml`
- Depends on: Task 3.1
- Change: `net.sf.ehcache` → `org.ehcache` 3.10.x; `CacheAdminController` rewritten to iterate the cache (no `getKeys()`/`getQuiet()`); Spring `EhCacheCacheManager` → `JCacheCacheManager` over the JSR-107 provider with `javax.cache:cache-api` (`javax.cache` is JSR-107 and never becomes `jakarta`); `hibernate-ehcache` → `hibernate-jcache` with `hibernate.cache.region.factory_class=jcache`; remove the two `ehcache-web` filters from `web.xml` and flag them. **JGroups replication has no Ehcache 3 equivalent** — see Open Questions
- Done when: no `net.sf.ehcache` import remains and the app starts with a working cache

### Task 3.5: log4j 1.2 → SLF4J + Logback
- Files: `src/main/java/com/acme/orders/**` (23 files importing `org.apache.log4j`), `src/main/resources/log4j.properties`, `pom.xml`
- Depends on: none
- Change: `org.apache.log4j.Logger` → `org.slf4j.Logger` + `LoggerFactory.getLogger(X.class)`; convert concatenated messages to `{}` parameters; `log4j.properties` → `logback.xml` preserving the current appenders, levels and rolling policy; remove `log4j:log4j`
- Done when: no `org.apache.log4j` import remains and no `log4j:log4j` is on the classpath

### Task 3.6: Guava, Oracle driver and remaining bumps
- Files: `pom.xml`, `src/main/java/com/acme/orders/util/OrderKeys.java`, `src/main/java/com/acme/orders/util/Timing.java`
- Depends on: none
- Change: remove `com.google.collections:google-collections`, pin the newest `com.google.guava:guava` `-jre` via `guava-bom`; rewrite `Objects.toStringHelper` → `MoreObjects.toStringHelper` and `new Stopwatch()` → `Stopwatch.createStarted()`; `ojdbc6` → `ojdbc11`; `mockito-core` 4.11.0 → 5.x; Lombok → 1.18.40+
- Done when: `mvn -q compile` succeeds at `release` 17

### Task 3.7: Set the compiler release to 17
- Files: `pom.xml`
- Depends on: Tasks 3.1–3.6
- Change: `maven.compiler.release` = 17, not further. Add `--add-opens` to the surefire `argLine` **only** if a test genuinely needs deep reflective access — never to silence an `InaccessibleObjectException` from a stale library, which is a signal that Task 3.1's cglib removal is incomplete
- Done when: `mvn -q -DskipTests package` succeeds at release 17


## Stage 4: Upgrade to Spring Boot 2.7 (WAR intact)

### Task 4.1: Introduce the Spring Boot 2.7 parent and composition root
- Files: `pom.xml`, `src/main/java/com/acme/orders/Application.java`, `src/main/webapp/WEB-INF/web.xml`, `src/main/resources/application.properties`
- Depends on: Stage 3
- Change: Spring Boot 2.7.18 parent and starters (`web`, `data-jpa` not yet); add `SpringBootServletInitializer`; scope the embedded container starter `provided`; retire the Spring-bootstrap entries from `web.xml`; keep the XML bean files via `@ImportResource`. `javax.*` untouched, `<packaging>war</packaging>` kept, compiler release stays 17
- Done when: `mvn -q -DskipTests package` produces a WAR that still deploys to Tomcat 9


## Phase 3: Java 25 Baseline
Goal: Java 25 — reached only after the framework moves to Spring Boot 3.x, which supports it.

## Stage 5: Upgrade to Spring Boot 3.x (Jakarta namespace transition)

### Task 5.1: Spring Boot 3.5 and the Jakarta EE rename
- Files: `pom.xml`, `src/main/java/com/acme/orders/web/OrderServlet.java`, `src/main/java/com/acme/orders/web/OrderFilter.java`, `src/main/java/com/acme/orders/model/Order.java`, `src/main/java/com/acme/orders/model/OrderLine.java`, `src/main/java/com/acme/orders/model/Product.java`, `src/main/java/com/acme/orders/dao/OrderDao.java`, `src/main/webapp/WEB-INF/web.xml`
- Depends on: Stage 4
- Change: Boot 3.5.x (a line that also supports Java 25); Jakarta EE `javax.servlet.*`, `javax.persistence.*`, `javax.validation.*`, `javax.annotation.*` → `jakarta.*`. **Never** rename Java SE `javax.sql`, `javax.naming`, `javax.crypto`, JAXP, or JSR-107 `javax.cache`. Swap `jackson-module-jaxb-annotations` → `jackson-module-jakarta-xmlbind-annotations` and Ehcache 3 → its `jakarta` classifier. Spring Security 6 and Spring MVC 6 changes. WAR kept; compiler release stays 17
- Done when: no Jakarta EE `javax.*` import remains, the four Java SE `javax.*` families are untouched, and the WAR deploys to Tomcat 10.1


## Stage 6: Java 17 → Java 25 LTS

### Task 6.1: Set the compiler release to 25 and verify the legacy cleanup
- Files: `pom.xml`
- Depends on: Stage 5
- Change: `maven.compiler.release` = 25. Verify no `cglib` or `javassist` anywhere in the dependency tree, including transitively — JDK 17+ strong encapsulation makes them throw `InaccessibleObjectException`, and `--add-opens` is not the fix. Bump Lombok and Mockito if the JDK requires it. Never touch the Spring Boot version in this stage
- Done when: `mvn -q -DskipTests package` succeeds at release 25 and `mvn dependency:tree` contains neither cglib nor javassist

### Task 6.2: Adopt the language features that earn their place
- Files: `src/main/java/com/acme/orders/service/OrderService.java`, `src/main/java/com/acme/orders/service/PricingService.java`, `src/main/java/com/acme/orders/batch/NightlyReconciliation.java`
- Depends on: Task 6.1
- Change: virtual threads for the fixed pool in `NightlyReconciliation` that blocks on JDBC; pattern matching for `switch` in `PricingService`'s discount dispatch; sequenced collections where `get(0)`/`get(size()-1)` is used. Only where it meaningfully improves these specific files — no repo-wide rewrite
- Done when: the build passes at release 25 and no `SecurityManager` reference remains


## Phase 4: Spring Boot 4 & Cloud Native
Goal: Spring Boot 4 on Jakarta EE 11 with Spring Data JPA, then an executable JAR.

## Stage 7: Upgrade to Spring Boot 4.x

### Task 7.1: Spring Boot 4 parent, dependency cleanup and Jackson 3
- Files: `pom.xml`, `src/main/java/com/acme/orders/web/OrderJsonController.java`, `src/main/java/com/acme/orders/web/ProductJsonController.java`, `src/main/java/com/acme/orders/config/WebConfig.java`, `src/main/resources/application.yml`
- Depends on: Stage 6
- Change: Boot 4.x / Spring Framework 7 / Jakarta EE 11; remove every conflicting library by name (explicit Spring versions, servlet API, JSTL, the extra connection pool, `jackson-databind` and the merged `jsr310`/`jdk8` modules, the extra logging binding); Jackson 2 → 3: `com.fasterxml.jackson.databind`/`.core` → `tools.jackson.*` (annotations unchanged), mutable `ObjectMapper` → `JsonMapper.builder()…build()`, `JsonProcessingException` → unchecked `JacksonException`; `application.properties` → `application.yml` with env-var placeholders for secrets
- Done when: no `com.fasterxml.jackson.databind` import remains and `mvn -q -DskipTests package` succeeds

### Task 7.2: DAOs → Spring Data JPA
- Files: `src/main/java/com/acme/orders/dao/OrderDao.java`, `src/main/java/com/acme/orders/dao/OrderDaoImpl.java`, `src/main/java/com/acme/orders/dao/ProductDao.java`, `src/main/java/com/acme/orders/dao/ProductDaoImpl.java`, `src/main/java/com/acme/orders/repository/OrderRepository.java`, `src/main/java/com/acme/orders/repository/ProductRepository.java`
- Depends on: Task 7.1
- Change: `spring-boot-starter-data-jpa`; each DAO becomes a `Repository` interface, keeping the existing DAO interface so callers are untouched. The four Oracle-specific queries (`ROWNUM`, the analytic `RANK() OVER`, the `FETCH FIRST`, the `seq_order.NEXTVAL`) are kept **verbatim** as `@Query(nativeQuery = true)` — never rewritten into JPQL
- Done when: no `SessionFactory` or `HibernateTemplate` usage remains and every native query is byte-identical to the original SQL


## Stage 8: Convert WAR → Executable JAR (Embedded Container)

### Task 8.1: JSP → Thymeleaf
- Files: `src/main/webapp/WEB-INF/jsp/*.jsp` (14 files), `src/main/resources/templates/*.html` (14 new), `pom.xml`
- Depends on: Stage 7
- Change: each JSP becomes a Thymeleaf template preserving its markup, form fields and validation messages exactly; JSTL constructs map to `th:each` / `th:if` / `th:text`; remove the JSP and JSTL dependencies
- Done when: no `.jsp` remains under `src/main/webapp` and every form posts the same field names

### Task 8.2: Executable JAR and container-provided resources
- Files: `pom.xml`, `src/main/java/com/acme/orders/Application.java`, `src/main/webapp/WEB-INF/web.xml`, `src/main/resources/application.yml`, `src/main/resources/static/**`
- Depends on: Task 8.1
- Change: `<packaging>jar</packaging>` with `spring-boot-maven-plugin` and an embedded Tomcat; remove `SpringBootServletInitializer`; translate and delete the remaining `web.xml`; JNDI DataSource → `spring.datasource.*` env vars; context path, encoding, session timeout, TLS and the container security realm → Spring Boot configuration; static assets → `src/main/resources/static`. The result is always an executable JAR — never a WAR
- Done when: `java -jar target/acme-orders.jar` starts and serves every migrated route


## 2. What Stays the Same

### Explicit Non-Changes
- **No REST or servlet endpoint changes.** All 19 paths, methods and request/response field names are identical before and after. The JSON field names survive the Jackson 1 → 2 → 3 moves.
- **No database schema changes.** No table, column, index or sequence is created, dropped or renamed. The four Oracle-specific queries are kept verbatim as native queries.
- **No business logic changes.** Pricing, discount, tax and validation rules are untouched. Stage 6's pattern-matching rewrite in `PricingService` changes the dispatch syntax, not any branch's outcome.
- **No configuration key renames.** Keys move from `.properties` to `.yml` and secrets become env-var placeholders, but every key name is preserved.
- **One exception, stated rather than hidden:** the cache admin endpoint `GET /admin/cache/dump` changes its read semantics — Ehcache 2's `getQuiet()` did not touch statistics or TTL, and Ehcache 3 offers no equivalent. Same response shape, different side effects.

### Out of Scope
- **JUnit 3/4 → Jupiter.** 41 JUnit 4 test classes remain. The toggle was off; they are carried as tech debt and bumped to 4.13.2 only.
- **A null-check bug in `PricingService.applyVolumeDiscount`** — a quantity of exactly 0 returns a discount of 0 rather than throwing. Pre-existing, unrelated to the migration, deliberately left alone.
- **Dead code:** `com.acme.orders.legacy.XmlExportService` (312 lines) has no callers in the repo. Not deleted — an external cron may invoke it via the `ExportServlet` mapping. Flagged, not touched.
- **The `ehcache-web` page-caching filters.** Removed because Ehcache 3 has no equivalent, but no replacement page cache is introduced. Response times for the two filtered paths may change.
- **JGroups cache replication.** Removed with Ehcache 2; choosing a replacement is a design decision, not a port. See Open Questions.
- **Database migration to 23ai.** `ojdbc6` → `ojdbc11` is a driver bump only. The Oracle upgrade is a separate companion migration.

## 3. Why This Is Safe

### Risk Tier
**High** — driven by **behavioural opacity**, not by blast radius or novelty.

- **Blast radius: Medium.** One deployable WAR, one Oracle schema shared with a reporting job that reads three tables directly. No published library artefacts, no message broker.
- **Novelty: High.** 6 of the 9 Stage 3 tasks are API rewrites rather than version bumps (Hibernate `Interceptor`, Jackson 1 → 2, Ehcache 2 → 3, log4j → SLF4J, Guava removals, `spring-mock`). None has a worked precedent in this codebase.
- **Behavioural opacity: High — this set the tier.** The Test Inventory reports 41 JUnit 4 classes covering 34% of source files, with **no test at all** touching the cache layer, the audit interceptor, or any of the four Oracle-specific queries. Those are exactly the three areas where this migration changes real behaviour.

### Behaviour Inventory

| Behaviour | Kind | Where it lives | Evidence |
|---|---|---|---|
| `GET /orders`, `GET /orders/{id}` | endpoint | `OrderServlet` | verified |
| `POST /orders`, `PUT /orders/{id}`, `DELETE /orders/{id}` | endpoint | `OrderServlet` | verified |
| `GET /api/orders.json`, `GET /api/products.json` | endpoint | `OrderJsonController`, `ProductJsonController` | verified |
| 12 further JSP-rendered routes | endpoint | `src/main/webapp/WEB-INF/jsp/` | verified |
| `GET /admin/cache/dump` | endpoint | `CacheAdminController` | verified |
| Order lookup by customer + date range (`ROWNUM`) | SQL path | `OrderDaoImpl.findRecentByCustomer` | verified |
| Top-N products by revenue (`RANK() OVER`) | SQL path | `ProductDaoImpl.topByRevenue` | verified |
| Paged order search (`FETCH FIRST`) | SQL path | `OrderDaoImpl.search` | verified |
| Order ID allocation (`seq_order.NEXTVAL`) | SQL path | `OrderDaoImpl.nextId` | verified |
| Audit columns written on insert and update | side effect | `AuditInterceptor` | verified |
| Nightly reconciliation | scheduled job | `NightlyReconciliation` (`@Scheduled`, 02:00) | verified |
| Stale-order sweep | scheduled job | `OrderSweeper` (`@Scheduled`, hourly) | verified |
| Order-summary cache population and eviction | side effect | `OrderCacheService` | verified |
| Cross-node cache replication | side effect | `ehcache.xml` JGroups block | inferred* — config present, no code reads it |

### Blast Radius
- **Oracle schema `ACME_ORD`** — shared with a nightly reporting job outside this repo that reads `ORDERS`, `ORDER_LINES` and `PRODUCTS` directly. No schema change is planned, so no coordination is required; if that changes, the reporting job moves in the same release.
- **Tomcat deployment** — the app moves from an external Tomcat 7 to an embedded container. Ops must retire the container-managed JNDI DataSource, TLS config and security realm, and supply them as environment variables instead. This is a coordinated release, not a drop-in redeploy.
- **The `ExportServlet` mapping** — possibly invoked by an external cron. See Out of Scope.
- **No published artefacts.** This repo publishes no library any other repo depends on.
- **No message broker.** No producer or consumer in this repo.

## 4. How We'll Prove It Worked

### Evidence Plan

| Behaviour | What proves it survives | Exists today? |
|---|---|---|
| 19 endpoints | `OrderServletIT`, `OrderJsonControllerTest` cover 7 of 19 | **Partial** — 12 have no test |
| `ROWNUM` recent-orders query | none | **No** |
| `RANK() OVER` top-products query | none | **No** |
| `FETCH FIRST` paged search | `OrderSearchTest` asserts result count, not ordering | **Partial** |
| `seq_order.NEXTVAL` allocation | `OrderDaoTest.testNextId` | Yes |
| Audit columns on insert/update | none | **No** |
| Nightly reconciliation | `NightlyReconciliationTest` (unit, mocked DAO) | **Partial** — logic only, no DB |
| Stale-order sweep | none | **No** |
| Cache population and eviction | none | **No** |
| Cache replication | none | **No** |

### Coverage Gaps
**17 of the 31 behaviours above have nothing proving them.** Concretely: 12 of 19 endpoints have no characterisation test; the audit interceptor, the cache layer and three of the four Oracle-specific queries are entirely untested.

This matters more than the raw number, because the untested areas and the behaviour-changing areas are the same set: **the audit interceptor is rewritten in Task 3.2, the cache layer in Task 3.4, and the native queries move in Task 7.2 — and none of the three has a test.**

**This run will proceed without generating characterisation tests first.** That is the decision being approved here. The alternative — generating characterisation tests for the 17 uncovered behaviours before Stage 3 — is recommended and is the single highest-value thing to add, but the JUnit toggle is off and no test-generation stage is in this plan.

### Validation Contract
- **What the pipeline guarantees:** each of the 8 stages is compiled by its own build loop (`mvn -q -DskipTests compile`, and `package` from Stage 4 onward so the WAR and then the JAR are really built), with the fixer iterating on errors. No stage may be left uncompilable. The independent code review must find no change outside this manifest and no manifest row unmet.
- **What it does not:** **the build loop never runs the test suite.** A green pipeline means "it compiles and packages", not "it works".
- **What a human must still do:** run `mvn verify` after Stage 8 and compare against a pre-migration baseline; exercise all 19 endpoints against the running JAR; verify audit columns are written on a real insert and update; verify the four native queries return identical rows and ordering against a production-like dataset; confirm the reconciliation and sweeper jobs fire and complete; decide on cache replication.

## 5. What Happens If It Fails

### Rollback Plan
**Rollback is clean at the repository level.** Every change is source-level; no schema DDL is applied, no data is migrated, nothing is published. Reverting the commit and rebuilding produces the original artefact exactly.

Rollback points, one per phase:
- **After Phase 1** — build-only changes, still Java 8, still deploys to Tomcat 7. Zero-risk stopping point.
- **After Phase 2** — Java 17 + Boot 2.7, WAR on Tomcat 9. A viable long-term resting point if the run has to stop.
- **After Phase 3** — Java 25 + Boot 3.5, WAR on Tomcat 10.1. Viable, but Tomcat 10.1 must already be available.
- **After Phase 4** — executable JAR, no external container.

**The deployment rollback is not as clean as the code rollback, and that is the real risk.** Each phase changes the container the artefact needs (Tomcat 7 → 9 → 10.1 → embedded). Rolling back the code after deploying a later phase means the *previous* container must still exist. Ops must keep the Tomcat 9 and 10.1 environments available until Phase 4 is verified in production, or a rollback becomes a rebuild-and-redeploy rather than a redeploy.

### Escalation Triggers
The run stops and hands over to a person when:
- the build loop reaches its iteration limit with errors outstanding;
- the same error reappears after the fixer reported it fixed;
- a stage cannot be made to compile without changing behaviour — specifically, if the `AuditInterceptor` rewrite cannot preserve the audit columns, or an Oracle native query will not run unmodified;
- the change audit finds `--add-opens` added to silence an `InaccessibleObjectException`, which means Task 3.1's cglib removal is incomplete and the fix is being masked;
- the code review finds a change outside this manifest, or a manifest row the run did not deliver;
- a file this plan names turns out not to exist in the repository, which means the plan was built on a wrong assumption.

## 6. What the Planner Doesn't Know

### Confidence Register

| Claim | Confidence | Basis |
|---|---|---|
| Spring Framework is 4.3.30 | verified | `pom.xml` read by the scanner |
| Hibernate is 3.6.10 with `orm.hibernate3` imports | verified | `pom.xml` and `HibernateConfig.java` |
| 19 endpoints exist | verified | API Contracts section, from the servlet and controllers |
| 41 JUnit 4 test classes | verified | Test Inventory |
| Four Oracle-specific queries | verified | Persistence & View Layer, quoted verbatim |
| 23 files import `org.apache.log4j` | verified | Legacy Stack Blockers, file list given |
| Cache replication is actually used across nodes | inferred* | JGroups block in `ehcache.xml`; no code reads it and no deployment topology was provided |
| `XmlExportService` is dead code | inferred* | no in-repo caller found; an external cron could still hit `ExportServlet` |
| The reporting job reads three tables directly | inferred* | table names in a comment in `OrderDaoImpl`; the job itself is not in this repo |
| The JNDI resources listed are the complete set | inferred* | `web.xml` and `context.xml` were read; a container-level `server.xml` was not available |
| No consumer depends on undocumented JSON fields | inferred* | no consumer code is in this repo |
| 34% test coverage of source files | inferred* | ratio of test classes to source files, not a coverage report |

### Assumptions
- The test suite passes today. If it does not, the post-migration run cannot distinguish a migration regression from a pre-existing failure — **verify this before Stage 1**.
- CI has, or can get, JDK 17 and JDK 25, and Tomcat 9, 10.1 and 11 environments are available in sequence.
- The Oracle instance the app runs against supports every native query unchanged after the `ojdbc11` bump.
- No external system depends on the WAR's context path or file name, both of which change in Stage 8.
- The 14 JSPs contain no business logic in scriptlets that would be lost in the Thymeleaf conversion. The scanner found none, but did not read every JSP in full.

### Open Questions for the SME
1. **`src/main/resources/ehcache.xml`** — is the JGroups cache replication actually load-bearing in production, or vestigial config from a clustered deployment that no longer exists? Ehcache 3 has no equivalent, so this is a design decision, not a port. If it is load-bearing, this plan is incomplete and needs a replacement strategy before Stage 3.
2. **`src/main/java/com/acme/orders/cache/CacheAdminController.java`** — does anything depend on `GET /admin/cache/dump` not disturbing cache statistics or TTL? Ehcache 2's `getQuiet()` guaranteed that; Ehcache 3 does not.
3. **`src/main/java/com/acme/orders/audit/AuditInterceptor.java`** — the interceptor writes `modified_by` from a thread-local set by a servlet filter. Is that thread-local guaranteed set on every write path, including the two scheduled jobs? The rewrite to event listeners preserves the mechanism, but not a latent bug if one exists.
4. **`src/main/java/com/acme/orders/dao/ProductDaoImpl.java`** — the `RANK() OVER` query has no `ORDER BY` on ties. Is the current tie-breaking order relied on by any caller? It is not guaranteed and may change under a new driver.
5. **`src/main/java/com/acme/orders/legacy/XmlExportService.java`** — is `ExportServlet` invoked by an external cron or integration? If not, it is dead code and can be deleted in a follow-up; if it is, it needs to be in scope.
6. **`src/main/webapp/WEB-INF/web.xml`** — the two `ehcache-web` page-caching filters are removed with no replacement. Were they added for a real performance problem, and what response times are acceptable without them?

## Estimated Effort

| Phase | Stages | Files touched | Effort |
|---|---|---|---|
| 1 Readiness | 1-2 | 4 | 0.5 day |
| 2 Java 17 Baseline | 3-4 | 42 | 4-6 days |
| 3 Java 25 Baseline | 5-6 | 16 | 2-3 days |
| 4 Boot 4 & Cloud Native | 7-8 | 46 | 4-5 days |
| **Total** | **8** | **~108** | **11-15 days**, plus the characterisation-test work under Coverage Gaps if that decision is reversed |
