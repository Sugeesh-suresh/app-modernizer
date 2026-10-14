# Java 8 → 25 + Spring Boot 4 (executable JAR) — `report` supplement

_What the final report must add: the Spring → Spring Boot conversion table, end-state evidence, what was dropped or replaced, run instructions and human follow-up._

Supplement to the `java-8-to-25` skill's `references/steps/report.md` — follow both; the base report's sections stay, and the sections below are added after **Changes Applied** (the run instructions go inside **Deployment Impact**). Part of the `java-8-to-25-boot` skill: read its SKILL.md for the end state. You have no tools: write only from the Modify Results, Final Build Result(s), the conformance report and the Independent Code Review you are given. Never claim a conformance finding is gone that the report you were given still lists.

## Spring → Spring Boot component conversion table

One row per component from the plan's Spring Component Inventory, filled from the Modify Results' **Components converted** lines and checked against the review's diff evidence:

| Component | Before | After | Files |
|---|---|---|---|
| Spring MVC config | `WebMvcConfigurerAdapter` + `@EnableWebMvc` | `WebMvcConfigurer`, Boot MVC auto-configuration | `config/WebConfig.java` |
| Data source | `<bean id="dataSource">` (DBCP) in `applicationContext.xml` | `spring.datasource.*`, HikariCP | `application.yml` |

Include components "not used" only if the plan listed them. A component the run did not finish gets its row with the state "pending" and goes to Follow-up. Never fill a cell from the inventory's plan when the Modify Results did not confirm it.

## End-state checklist with evidence

A table `Requirement | Met? | Evidence`, one row per line of the end state in SKILL.md (Boot 4.x parent/BOM; Java 25; Jakarta EE 11; `jar` packaging with `repackage`; embedded Tomcat via `spring-boot-starter-web`; single `@SpringBootApplication`; `application.yml` + `@ConfigurationProperties`; no Spring XML; no manual auto-configured beans; Thymeleaf, no JSP; starters only; no `web.xml`/WAR/initializer). Evidence is a file, a build result or a conformance-report line: "no B001–B011 findings in the final conformance report", "`target/orders.jar` listed by the final build". A requirement with no evidence is **Not shown**, never Met. List any warning left (B012, B013, W101) with its count.

## What was dropped or replaced

- JSP → Thymeleaf: the views converted and any construct that needed a decision (`<c:*>`, `<fmt:*>`, custom tags)
- `web.xml` settings → properties/config: servlet, filter, listener, context-param, error-page, session, welcome-file, security-constraint — each with its new home
- XML bean contexts deleted, manual beans deleted because Boot auto-configures them, and the customisations kept (as properties or `Customizer` beans)
- Libraries removed with their replacements (take the Modify Results' **Removed libraries**)
- Behaviour differences accepted on purpose (trailing-slash matching, Jackson 3 JSON defaults, CSRF)

## Run instructions

State only what the inputs support, as commands a person can paste:

- Build: `mvn clean package` → `target/<name>.jar`
- Run: `java -jar target/<name>.jar`
- Port and context path: `server.port`, `server.servlet.context-path` (say whether the old WAR's context path was preserved)
- Profiles: `--spring.profiles.active=<profile>` or `SPRING_PROFILES_ACTIVE`, and which profiles exist
- Environment variables ops must supply (`DB_URL`, `DB_USERNAME`, `DB_PASSWORD`, broker credentials, …) taken from the Modify Results; the external container and JNDI resources that are no longer needed
- Health: the Actuator path if the run added it
- State whether the smoke check (`java -jar`) ran, from the Final Build Result; if it did not, say so

## Human follow-up

Everything the pipeline could not verify, in addition to the base report's list: running the full test suite; a startup against the real database and brokers; comparing endpoints, JSON and security behaviour against the old deployment; every `pending` component; every Open Question the plan carried and how it was resolved or left; third-party clients of removed remoting endpoints; TLS, access-log and realm settings that moved into configuration.
