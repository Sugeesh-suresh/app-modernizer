# Java 8 → 25 + Spring Boot 4 (executable JAR) — `review` supplement

_Checklist for the independent reviewer: conformance with the Boot end state, behaviour preserved, no half-converted component._

Supplement to the shared `code-review` skill's review of a migration against its plan — follow both. Part of the `java-8-to-25-boot` skill: read its SKILL.md for the end state and rules. You review from the workspace and the diff; you do not edit it.

**Knowledge for this step** (load with `load_skill_resource`): `references/boot-conformance-rules.md`, `references/spring-to-boot-component-map.md`.

Mark each item **met**, **unmet** (with file and line evidence) or **not applicable** (with the reason). An unmet item is a finding; do not soften it because the build passed. Evidence comes from files you read and the pipeline's conformance report — not from the Modify Results' account of themselves.

## 1. End-state conformance

- [ ] The pipeline's conformance report has no error-level finding (B001–B011); warnings (B012, B013, W101) are listed with a note on whether each was in scope
- [ ] Parent or BOM is Spring Boot 4.x; no `<version>` on a Boot-managed dependency; `spring-boot-maven-plugin` present with `repackage`
- [ ] Packaging `jar`; no `maven-war-plugin`; no `web.xml`, no `WebApplicationInitializer`/`SpringBootServletInitializer`, no `src/main/webapp/WEB-INF`
- [ ] Embedded Tomcat via `spring-boot-starter-web`; no Jetty/Undertow starter, no external-container plugin, no `provided` Tomcat
- [ ] Exactly one `@SpringBootApplication`, in a package above the scanned ones
- [ ] No Spring XML bean file, no `@ImportResource`, no `ClassPathXmlApplicationContext`/`XmlWebApplicationContext`
- [ ] No `.jsp`, no JSTL/Jasper dependency, no `InternalResourceViewResolver`; Thymeleaf templates exist for every former view
- [ ] No `javax.*` Jakarta-EE import; Java SE `javax.sql`/`naming`/`crypto`/JAXP still `javax` (a renamed one is a defect)
- [ ] Every `org.springframework.*` library dependency is a `spring-boot-starter-*`
- [ ] `application.yml`/`.properties` present; application keys bound with `@ConfigurationProperties`; no real secret as a default

## 2. No fighting of Boot

- [ ] No manual bean for what Boot auto-configures (`DataSource`, `EntityManagerFactory`, transaction manager, `JdbcTemplate`, `ObjectMapper`, `MessageSource`, view/multipart resolvers, `DispatcherServlet`, encoding filter)
- [ ] Every customisation of those survives as a property or a `Customizer`/`WebMvcConfigurer` (compare the deleted bean's settings with `application.yml`)
- [ ] No `@EnableWebMvc`, `WebMvcConfigurerAdapter`, `WebSecurityConfigurerAdapter`
- [ ] No `spring.main.allow-bean-definition-overriding`, no `@Primary` that only masks a duplicate
- [ ] No bean defined twice (XML and Java, or manual and auto-configured)

## 3. Behaviour preserved (check against the plan's Behaviour Inventory, row by row)

- [ ] **URLs:** every `@RequestMapping` path/method is unchanged; context path set in `server.servlet.context-path` where the WAR had one; trailing-slash differences are noted, not hidden
- [ ] **Security:** every `<intercept-url>`/`<security-constraint>`/`@PreAuthorize` rule has an equal in the `SecurityFilterChain` or method security — same patterns, same roles, same order; login/logout URLs, CSRF, CORS and session settings match the old behaviour or the difference is stated
- [ ] **Transactions:** each former `<tx:advice>`/`@Transactional` boundary, propagation, isolation, read-only flag and rollback rule is intact; no service method lost its boundary when XML pointcuts were replaced
- [ ] **Messages:** `MessageSource` basenames and keys resolve (`spring.messages.basename`), including encoding and fallback
- [ ] **Scheduled jobs and async:** same cron/fixed-rate values, same thread-pool sizes (`spring.task.*`), each job still scheduled once
- [ ] **Messaging and batch:** listeners, destinations, concurrency, acknowledgement and job definitions carried over
- [ ] **JSON and views:** same JSON shape (note Jackson 3 default changes); each Thymeleaf template renders the same data under the same model attribute names
- [ ] **Container-supplied settings:** JNDI DataSources, encoding, session timeout, TLS, error pages, access logs each became a property, or are listed for ops

## 4. No half-converted component

- [ ] Every row of the plan's Spring Component Inventory is converted to the target it names, or is listed as pending with a reason the approved plan allowed
- [ ] No class mixes legacy and Boot idioms for one component (a `SecurityFilterChain` next to `<http>`, a repository next to a hand-built `EntityManagerFactory`)
- [ ] Every deleted XML/JSP/`web.xml` had its content moved first (diff the deleted file's beans/elements against the new code)
- [ ] Tests no longer load deleted XML contexts or use `SpringJUnit4ClassRunner`; test configuration still boots

## Report to the caller

Group findings as **Blocks the end state** (unmet items from sections 1–2), **Behaviour risk** (section 3) and **Incomplete conversion** (section 4), each with file:line evidence and the conversion the plan promised. If every item is met, say so in one line.
