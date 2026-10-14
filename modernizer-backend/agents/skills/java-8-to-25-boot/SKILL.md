---
name: java-8-to-25-boot
description: >
  Overlay profile for the java-8-to-25 migration: besides Java 8 → 25, every Spring Framework component
  (XML contexts, web.xml, MVC config, security, data access, messaging, tests) is converted to its Spring Boot 4.x
  equivalent and the application ships as an executable JAR on embedded Tomcat — never a WAR. Supplement step
  files for plan, modify, validate, fix, review and report, plus Spring-to-Boot knowledge and the exact
  conformance rules the pipeline's scanner enforces.
---

# Java 8 → 25 + whole-framework Spring Boot 4 (executable JAR)

This is an **overlay**. The `java-8-to-25` skill owns the engine — bigbang or incremental stages, the JDK hops, the build loop, the Jakarta rename, the Boot 2.7 → 3.x → 4.x stage guides, the WAR → JAR checklist. This skill repeats none of that. It adds the part `java-8-to-25` only does in outline: **every Spring Framework component the repository uses is converted to its Spring Boot equivalent**, not merely the dependencies and the packaging. The pipeline tells you: "also load and follow the `java-8-to-25-boot` skill's `references/steps/<step>.md`". Follow that supplement alongside your own `java-8-to-25` step. Where the two seem to disagree, the stricter one wins; where this skill is silent, `java-8-to-25` governs.

## The end state (non-negotiable)

When the run finishes, every line below is true. The pipeline scans the result and fails validation if one is not.

| Aspect | End state |
|---|---|
| Boot | The newest Spring Boot 4.x, via `spring-boot-starter-parent` or an imported `spring-boot-dependencies` BOM. No hand-set `<version>` on any library the BOM manages |
| JDK / EE | Java 25, Jakarta EE 11 — no `javax.*` for EE APIs (Java SE `javax.sql`, `javax.naming`, `javax.crypto`, … stay) |
| Packaging | `<packaging>jar</packaging>` (or Gradle `bootJar`), `spring-boot-maven-plugin` with the `repackage` goal; `java -jar target/<name>.jar` starts the app |
| Server | **Embedded Tomcat** through the web starter (`spring-boot-starter-webmvc`, Boot 4's name; `spring-boot-starter-web` if the chosen release does not publish it — see the base skill's `boot4-dependency-cleanup.md`). No Jetty, no Undertow, no external container, no WAR, no `SpringBootServletInitializer`, no `web.xml`, no `src/main/webapp/WEB-INF` |
| Entry point | Exactly one `@SpringBootApplication` class with `main` |
| Configuration | `application.yml` / `application.properties` + `@ConfigurationProperties`; secrets as `${ENV_VAR}` placeholders |
| Spring XML | None. No `<beans>` files, no `@ImportResource`, no `ClassPathXmlApplicationContext` |
| Auto-configuration | No hand-declared bean for what Boot auto-configures: `DataSource`, `EntityManagerFactory`, transaction manager, `JdbcTemplate`, `ObjectMapper`/`JsonMapper`, `MessageSource`, view and multipart resolvers, `DispatcherServlet`, security filter-chain wiring, `CharacterEncodingFilter`, … A real customisation survives as a property or a `*Customizer` bean |
| Views | Thymeleaf. JSP cannot be served from an executable JAR, so no `.jsp` file remains |
| Dependencies | Every `org.springframework.*` library dependency expressed as the matching `spring-boot-starter-*` |
| Behaviour | Same URLs, security rules, transactions, messages, scheduled jobs and JSON shapes as before |

## The deterministic gate

After the last stage the pipeline scans the workspace and emits **findings B001–B013** (and W101). `references/boot-conformance-rules.md` lists exactly what each one matches. **Error-level findings fail validation; every one must be gone** before the run counts as passed. Warnings are reported, not blocking — but a warning you can clear in passing, you clear. Read that file before you write the plan, so every finding is pre-empted rather than found at the end.

## Workflow

These supplements ride along with the `java-8-to-25` steps; the pipeline decides when each runs.

| # | Step | Supplement file | What it adds |
|---|---|---|---|
| 1 | `plan` | `references/steps/plan.md` | Spring Component Inventory, Conversion Order per engine stage, manifest rows for every XML/config/test file |
| 2 | `modify` | `references/steps/modify.md` | How each component class is converted, in order, one concern per task |
| 3 | `validate` | `references/steps/validate.md` | `package`, the JAR artifact, a `java -jar` smoke check, the conformance report → `BOOT:` errors |
| 4 | `fix` | `references/steps/fix.md` | Finding code → fix table, bean-conflict repairs |
| 5 | `review` | `references/steps/review.md` | The independent reviewer's checklist for conformance and preserved behaviour |
| 6 | `report` | `references/steps/report.md` | Component conversion table, end-state evidence, run instructions |

The stage guides of `java-8-to-25` (`readiness`, `springboot-incremental`, `springboot-boot4`) are unchanged; this skill tells you *what to convert* inside them.

## Rules for every step

- **Convert, don't wrap.** A Spring component is converted to the Boot way, not hidden behind `@ImportResource`, a copied-over `@Configuration`, or `spring.main.allow-bean-definition-overriding`. `@ImportResource` is a bridge inside the run and must be gone at the end.
- **Boot owns what Boot configures.** Delete the manual bean, carry its settings into `spring.*` / `server.*` properties, and keep only genuine customisations (as a `Customizer` or property).
- **One definition per bean.** Never leave an XML and a Java definition of the same bean, or a manual bean next to its auto-configured twin.
- **Behaviour is the contract.** Bean names that other code looks up, URL mappings, security rules, transaction boundaries, message keys, cron expressions and JSON shapes carry over unchanged. A deliberate change is named, not slipped in.
- **No half-converted component.** A component is either fully on its Boot equivalent or still listed as pending in the plan's current stage.
- **Never invent versions.** Say "the newest 4.x" as the `java-8-to-25` references do; versions of managed libraries come from the BOM.
- **The scanner and the validator are the truth.** No step reports conformance the conformance report did not show.
- **Knowledge lives in `references/`.** Load each file a step names with `load_skill_resource`.

## Knowledge

| File | Used by the steps |
|---|---|
| `references/boot-conformance-rules.md` | `plan`, `modify`, `validate`, `fix`, `review` |
| `references/spring-to-boot-component-map.md` | `plan`, `modify`, `fix`, `report` |
| `references/xml-and-web-xml-to-boot.md` | `plan`, `modify`, `fix` |
| `references/web-layer-to-boot.md` | `modify`, `fix` |
| `references/security-to-boot.md` | `modify`, `fix` |
| `references/data-access-to-boot.md` | `modify`, `fix` |
| `references/messaging-integration-batch-to-boot.md` | `modify`, `fix` |
| `references/testing-to-boot.md` | `modify`, `fix` |

Base knowledge it builds on, all in the `java-8-to-25` skill: `war-to-executable-jar.md`, `webxml-to-javaconfig.md`, `spring-data-jpa-migration.md`, `jsp-to-thymeleaf.md`, `boot4-dependency-cleanup.md`, `boot27-on-war.md`, `boot3-jakarta-transition.md`, `jakarta-ee11-namespace-map.md`, `legacy-library-modernization.md`.


## Decisions the base skill leaves open (this profile settles them)

- **The Boot version is the one version you choose.** The parent's version is resolved at modify time from Maven Central metadata as the newest **GA** 4.x — never a milestone (`-M`) or release candidate (`-RC`) — and written once, in `spring-boot-starter-parent`. This is the exception to "use only versions you have seen": every other managed library takes its version from the BOM.
- **Keep the repository's data-access style.** `JdbcTemplate` / plain JDBC → `spring-boot-starter-jdbc` (the template is auto-configured); JPA / Hibernate → `spring-boot-starter-data-jpa`. Do not rewrite hand-written SQL into entities to satisfy a "with Spring Data JPA" line in the base skill — this profile overrides it; JPA is for code that is already JPA.
- **Starter name.** The web starter is `spring-boot-starter-webmvc` in Boot 4 (fall back to `spring-boot-starter-web` only if the chosen release does not publish it).

## Looking things up (versions, artifact names)

- **Maven Central rate-limits** (HTTP 429) when several metadata files or poms are fetched in a row. Fetch what you need once, wait and retry with a growing pause (2 s, 5 s, 12 s), and write the answer into your output so nobody asks again. Never conclude "not found" from a 429.
- **An artifact name you cannot verify** (a read-only step cannot resolve anything) is written with `(verify)` after it, for example `camel-spring-boot-xml-starter (verify)`; the first step that can build resolves it and corrects the plan's row in its output. Never invent a coordinate and present it as fact.
- **A Boot-managed library's version is never copied from memory:** it comes from the BOM, resolved by the build.

Camel (any Camel route in the repository): `references/camel-to-boot.md` — the starter and BOM names, the wiring, and the Camel 2 → 4 API table.
