# Java 8 → 25 + Spring Boot 4 (executable JAR) — `modify` supplement

_How to convert each Spring component class and configuration file to its Spring Boot equivalent while applying a task or a whole plan._

Supplement to the `java-8-to-25` skill's `references/steps/modify.md` — follow both, with the same tools (`read_file`, `replace_in_file`, `write_file`, `delete_file`) and the same Modify Result summary. Part of the `java-8-to-25-boot` skill: read its SKILL.md for the end state and rules.

**Knowledge for this step** (load each with `load_skill_resource`): `references/spring-to-boot-component-map.md` always; `references/xml-and-web-xml-to-boot.md` when the task touches an XML context or `web.xml`; `references/boot-conformance-rules.md` so you do not create a finding; and the topic file for what you touch — `references/web-layer-to-boot.md`, `references/security-to-boot.md`, `references/data-access-to-boot.md`, `references/messaging-integration-batch-to-boot.md`, `references/testing-to-boot.md`.

Your task still bounds the files you may edit and the stage still bounds the work (the guardrail of an incremental run wins over anything below). Inside those bounds:

## Order of work

Convert in dependency order, whatever the task's file order:

1. **Build file** — Boot parent/BOM, starters for `spring-*` artifacts, no hand-set versions of managed libraries, `spring-boot-maven-plugin` with `repackage`
2. **`@SpringBootApplication` class** — create it once in the root package (above every scanned package); `main` calls `SpringApplication.run`
3. **Properties** — `application.yml`; one key per legacy placeholder
4. **Infrastructure beans** — delete what Boot auto-configures; keep customisations as properties or `Customizer` beans
5. **Data access → services → web → security → views → packaging → tests**, as the plan's Conversion Order lists

## Rules

- **One concern per task.** A task that converts the security config does not also convert the controllers. If you find a second concern, report it; do not do it.
- **Keep behaviour.** Same URL mappings, HTTP methods, security rules, transaction boundaries and propagation, message keys, cron expressions, JSON shapes.
- **Keep bean names other code looks up.** If code uses `getBean("auditService")`, `@Qualifier("primaryDs")`, `@Resource(name=...)`, a SpEL `#{beanName}` or an XML `ref`, the converted bean keeps that name: `@Service("auditService")`, `@Bean("primaryDs")`. Grep for the name before you rename.
- **Move placeholders to `application.yml` keys.** `${db.url}` becomes `spring.datasource.url`; application-specific keys get a prefix and a `@ConfigurationProperties` class; secrets are `${ENV_VAR}` with no real default.
- **Convert XML one context at a time.** For one XML file: list its beans, convert each (stereotype annotation with constructor injection, `@Configuration` + `@Bean` for third-party types, or properties for what Boot configures), and **delete the XML file only after every bean in it exists in its new form.** A context imported by another stays until the importer is converted. Never leave both an XML definition and a Java definition of the same bean.
- **`@ImportResource` is a short-lived bridge.** Use it only where your stage's guardrail says XML survives; never add it to finish early. In the stage that deletes the last XML file, remove every `@ImportResource`.
- **Remove manual beans that Boot auto-configures** (`DataSource`, `EntityManagerFactory`, transaction manager, `JdbcTemplate`, `ObjectMapper`, `MessageSource`, view/multipart resolvers, `DispatcherServlet`, `CharacterEncodingFilter`, `PropertyPlaceholderConfigurer`) — **but keep a customisation**: a non-default pool setting → `spring.datasource.hikari.*`; a Jackson feature → `spring.jackson.*` or a `JsonMapperBuilderCustomizer`; an extra converter/formatter/interceptor → a `WebMvcConfigurer`; a Hibernate property → `spring.jpa.properties.*`; extra Tomcat tuning → `server.tomcat.*` or a `WebServerFactoryCustomizer`.
- **Never silence a conflict.** `spring.main.allow-bean-definition-overriding=true` is not a conversion; neither is `@Primary` added only to hide a duplicate.
- **Constructor injection** for converted beans; no `@Autowired` field injection added. Existing injection style in untouched classes stays.
- **`@Transactional` stays where it was**; the proxy mode and rollback rules do not change silently. `<tx:advice>`/`<aop:config>` pointcuts become `@Transactional` on the same methods, and the plan's mapping says which.
- **Delete what is replaced.** Delete the XML file, the `web.xml`, the `WebApplicationInitializer`, the JSP, the `log4j.*` file in the task that makes it obsolete, and name it in the summary.
- **Do not touch what the plan did not assign**, and do not add Spring Security, Actuator or caching that the application did not already have, except `spring-boot-starter-actuator` where the plan replaces a custom health servlet.

## Self-check before you finish each file

Grep the files in your task for the patterns in `references/boot-conformance-rules.md` that your edit could introduce or should have removed: `javax.` EE imports, `@EnableWebMvc`, `WebMvcConfigurerAdapter`, `WebSecurityConfigurerAdapter`, `InternalResourceViewResolver`, `ClassPathXmlApplicationContext`, hand-built `DataSource`/`EntityManagerFactory`/transaction-manager/`CommonsMultipartResolver` beans, `SpringJUnit4ClassRunner`.

## Add to the Modify Result

- **Components converted:** component | before | after | files — one row per component, for the Spring → Spring Boot conversion table in the report
- **Beans:** XML beans converted (name → new form), manual beans deleted (name → property or auto-configuration that replaces them), customisations kept (and how)
- **Bridges left:** every `@ImportResource` or XML file still present, with the later stage that removes it ("none" at the end of the final stage)
- **Behaviour notes:** anything that could change a URL, a security rule, a transaction boundary, a message or a JSON shape, stated plainly
