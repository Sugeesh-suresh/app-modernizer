# Java 8 → 25 + Spring Boot 4 (executable JAR) — `plan` supplement

_What the migration plan must additionally contain when every Spring Framework component is to be converted to Spring Boot._

Supplement to the `java-8-to-25` skill's `references/steps/plan.md` — follow both. Part of the `java-8-to-25-boot` skill: read its SKILL.md for the end state and the rules every step follows. Nothing here replaces the six-question plan structure, the task blocks or the File Change Manifest rules of the base step; it adds content inside them.

**Knowledge for this step** (load each with `load_skill_resource`): `references/spring-to-boot-component-map.md`, `references/xml-and-web-xml-to-boot.md`, `references/boot-conformance-rules.md`.

The Spring Boot upgrade is not optional in this profile: the plan always targets the newest Spring Boot 4.x as an executable JAR on embedded Tomcat, and every conformance finding B001–B013 must be predicted and planned away. Size the Spring work from the inventory's Packaging & Deployment Model, Persistence & View Layer, Behaviour Inventory and Legacy Stack Blockers; where it does not say how a component is configured, that is an Open Question, never a guess.

## Add to `### Dependency & Version Delta`

One row each for: Spring Boot (parent or BOM), Spring Framework, Spring Security, Spring Data, every other Spring project found (Batch, Integration, AMQP, Kafka, Session, …), Tomcat (external → embedded), Thymeleaf (if JSPs exist), and the `spring-boot-maven-plugin`. Version cells say "the newest 4.x / managed by the Boot BOM" — never a hand-picked number.

## Add a `### Spring Component Inventory` section (inside `## 1. What Changes`)

A table with one row per Spring module **and** per configuration style the repository uses, each with its Boot target from `references/spring-to-boot-component-map.md`:

| Component | How it is configured today (files) | Boot target | Conversion stage |
|---|---|---|---|

Cover every one of these, writing "not used" for the ones that are absent so the approver sees they were checked:

- **Configuration style:** XML bean contexts (`applicationContext*.xml`, `*-servlet.xml`, imported fragments), annotation config (`@Configuration`, `@ComponentScan`), `web.xml`, `WebApplicationInitializer`/`SpringBootServletInitializer`, `@PropertySource` / property placeholders, profiles
- **Web:** controllers, REST controllers, view resolution (JSP/`InternalResourceViewResolver`, Tiles, FreeMarker, Velocity), interceptors, filters, converters, exception handling, multipart, CORS, static resources, i18n `MessageSource`, error pages
- **Security:** XML `<http>`, `WebSecurityConfigurerAdapter`, `UserDetailsService`, password encoders, method security, CSRF/CORS/session settings, container (`web.xml`) security
- **Data access:** `DataSource` (JNDI or pooled), `JdbcTemplate`, JPA/Hibernate (`LocalSessionFactoryBean`, `HibernateTemplate`), Spring Data, transaction manager and `<tx:*>`
- **Messaging and integration:** JMS, AMQP/RabbitMQ, Kafka, Spring Integration, Spring Batch, mail, remoting (HttpInvoker, RMI, Hessian, SOAP), `RestTemplate` clients
- **Cross-cutting:** scheduling and `@Async`, caching, AOP/AspectJ, validation, JMX, custom health servlets, logging configuration
- **Testing:** `SpringJUnit4ClassRunner`, `@ContextConfiguration`, XML test contexts, test slices

Each row names real files from the inventory. A component with no Boot equivalent (a custom namespace handler, a JSP tag library with no Thymeleaf counterpart) is listed with target "undecided" and carried into Open Questions.

## Add a `### Conversion Order` section

The order is dependency-safe: a layer is converted only after the layers it depends on are on Boot.

1. **Build and entry point** — Boot parent/BOM, starters in place of `spring-*` artifacts, the single `@SpringBootApplication` class, `application.yml` skeleton
2. **Infrastructure beans** — `DataSource`, transaction manager, `EntityManagerFactory`/`SessionFactory`, `JdbcTemplate`, `ObjectMapper`, `MessageSource`, property placeholders → properties; manual duplicates of auto-configuration deleted
3. **Data access** — DAOs/repositories, `@Transactional` boundaries
4. **Services, scheduling, caching, messaging, integration, batch** — XML bean files converted one context at a time
5. **Web layer** — MVC config, controllers, filters/interceptors, exception handling, error pages
6. **Security** — `SecurityFilterChain`, user details, method security
7. **Views and static assets** — JSP → Thymeleaf, `webapp` → `static`
8. **Packaging** — `jar`, `web.xml` and `SpringBootServletInitializer` removed
9. **Tests** — runners and XML contexts → `@SpringBootTest` / slices

**Bigbang:** the order above is the order of tasks inside the one pass (the base plan's change sections follow it). Dependent files go in the same task.

**Incremental:** assign each conversion to the engine stage whose state it matches — a conversion done too early breaks that stage's guardrail, one done too late leaves the final scan red.

| Engine stage | Spring conversions that belong to it |
|---|---|
| Stage 4 — Boot 2.7 (WAR intact, still `javax`) | Boot 2.7 parent/BOM; every `spring-*` artifact → its starter; the single `@SpringBootApplication` class; `WebSecurityConfigurerAdapter` → `SecurityFilterChain`, `WebMvcConfigurerAdapter` → `WebMvcConfigurer`, `@EnableWebMvc` removed; XML kept via `@ImportResource` (the only bridge) |
| Stage 5 — Boot 3.x (Jakarta) | the Jakarta rename and artifact swaps; Spring Security 6 lambda DSL; Spring 6 / Hibernate 6 breaking changes; removal of `spring-boot-properties-migrator` |
| Stage 7 — Boot 4.x (still a WAR) | XML contexts → annotations/`@Configuration`/properties and `@ImportResource` removed; manual beans Boot auto-configures deleted; `.properties` → `application.yml` + `@ConfigurationProperties`; persistence → Spring Data JPA; Jackson 3; tests → `@SpringBootTest`/slices; logging bindings and `log4j.*` removed |
| Stage 8 — executable JAR | JSP → Thymeleaf; packaging `jar`; `SpringBootServletInitializer`, `web.xml`, `src/main/webapp/WEB-INF` removed; container-provided resources → `server.*`/`spring.*`; Jetty/Undertow/`provided` Tomcat removed |

Stage 6 (Java 25) carries no Spring conversion. Findings are scanned on the final result only, so an intermediate stage may still show B001/B002/B004/B005 — but a stage never starts the next stage's work.

## Manifest rows (in the one consolidated File Change Manifest)

- Every XML bean context, `web.xml`, `WebApplicationInitializer`, `@Configuration`/`WebMvcConfigurer`/security config class, `.properties`/`.yml` file, JSP, and test class or test context the conversion touches gets a row — including `delete` rows for XML files and JSPs.
- "What Changes" names the beans, mappings or elements converted: "`applicationContext.xml`: `dataSource`, `transactionManager`, `<tx:annotation-driven/>` deleted (Boot auto-configures; settings → `spring.datasource.*`); `auditAspect` bean → `@Component` on `AuditAspect`". Never "converted to Boot".
- A context converted across tasks lists the beans each task moves; the XML file is deleted in the task that moves its last bean.

## Open Questions

Only what cannot be decided from the inventory: a JSP tag library or custom tag with no Thymeleaf equivalent, a custom XML namespace handler, a remoting endpoint (HttpInvoker/RMI/Hessian) whose clients are outside the repository, a JNDI resource whose connection data is not in the repository. Do not ask what the component map already answers.

## Plan-level checks before you finish

- Each of B001–B013 has an entry (a stage and a task, or "not applicable: <evidence>").
- The Behaviour Inventory in question 3 lists the URLs, security rules, scheduled jobs and message listeners the conversion must preserve; the Evidence Plan says what proves each.
- The Rollback Plan names the deployment change: external container → `java -jar` with environment variables.


## Where the Spring facts come from

The Technical Specification's `## Spring XML Bean Definitions` table lists, per Spring XML context, its beans, component scans, JNDI lookups, MVC / tx / aop elements and property files. Build the Spring Component Inventory from it and from the Behaviour Inventory; read the XML itself only for what the table cannot show (a bean's property values, an interceptor's mapping). A file you list in a task's `Files:` line but leave unchanged is named in the manifest as `no change needed`.
