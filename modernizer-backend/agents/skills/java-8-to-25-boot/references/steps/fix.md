# Java 8 → 25 + Spring Boot 4 (executable JAR) — `fix` supplement

_How to resolve each Boot conformance finding, and the bean-wiring failures that appear while removing XML and manual beans._

Supplement to the `java-8-to-25` skill's `references/steps/fix.md` — follow both, with the same tools, the Fix Result and the `## Lessons` block. Part of the `java-8-to-25-boot` skill: read its SKILL.md for the end state.

**Knowledge for this step** (load each with `load_skill_resource`): `references/boot-conformance-rules.md`, `references/spring-to-boot-component-map.md`, `references/xml-and-web-xml-to-boot.md`; plus the topic file for the code in the error (`web-layer-to-boot.md`, `security-to-boot.md`, `data-access-to-boot.md`, `messaging-integration-batch-to-boot.md`, `testing-to-boot.md`).

Errors prefixed `BOOT:` come from the pipeline's conformance scan, not the compiler. Fix the cause the code names, and fix **forward onto the Boot way** — never by restoring the legacy construct or by hiding the finding.

## Finding code → what to do

| Code | Fix |
|---|---|
| B001 packaging `war` / war plugin | `<packaging>jar</packaging>` (or remove it); delete `maven-war-plugin`; Gradle: drop the `war` plugin, `bootWar` → `bootJar`. Follow `java-8-to-25` › `war-to-executable-jar.md` |
| B002 `web.xml` / `WebApplicationInitializer` / `SpringBootServletInitializer` | Translate every remaining `web.xml` element (`xml-and-web-xml-to-boot.md`), then delete the file; remove the initializer class (or the `extends` and the `configure` override) and keep `main` |
| B003 no `@SpringBootApplication` | Add one class with `main` in the root package, above all scanned packages; delete a second one if two exist |
| B004 `.jsp` / `WEB-INF` | Convert each JSP to a Thymeleaf template with the same view name (`java-8-to-25` › `jsp-to-thymeleaf.md`, `web-layer-to-boot.md`); delete the JSPs and `src/main/webapp/WEB-INF`; move assets to `src/main/resources/static` |
| B005 Spring XML bean file | Convert the beans (stereotype annotations, `@Configuration`, properties), delete the file; remove its `@ImportResource`/`<import>`. Tests that load it move to `@SpringBootTest` |
| B006 explicit Spring artifact with a starter | Replace the dependency with the starter the finding names; drop its `<version>`; delete sibling Spring artifacts the starter already brings |
| B007 no Boot parent/BOM, or plugin missing / no `repackage` | Add `spring-boot-starter-parent` (newest 4.x) or import `spring-boot-dependencies`; add `spring-boot-maven-plugin` with an explicit `repackage` execution when there is no starter parent. **W101:** remove the hand-set `<version>` of a managed library (keep versions only for what Boot does not manage) |
| B008 `javax.*` EE imports | Rename per `java-8-to-25` › `jakarta-ee11-namespace-map.md`; swap the artifact; never rename Java SE `javax.sql`, `javax.naming`, `javax.crypto`, JAXP |
| B009 config that fights Boot | See "Fighting configuration" below |
| B010 another server / `provided` Tomcat | Remove `spring-boot-starter-jetty` / `-undertow` and any `spring-boot-starter-tomcat` exclusion; remove `<scope>provided</scope>` from `spring-boot-starter-tomcat` (or delete the explicit entry — `spring-boot-starter-web` brings it) |
| B011 no `application.properties`/`.yml` | Create `src/main/resources/application.yml` with the keys the conversion produced (`spring.datasource.*`, `server.*`, …) |
| B012 old test runner (warning) | `@SpringBootTest` / slices, JUnit Jupiter — `testing-to-boot.md`; only if the JUnit upgrade was requested, otherwise leave it and list it as deprecated |
| B013 `log4j.*` / explicit logging binding (warning) | Delete `log4j.properties`/`log4j.xml`, `slf4j-log4j12`, `slf4j-simple`, a versioned `logback-classic`; configure levels in `logging.level.*` or `logback-spring.xml` |

## Fighting configuration (B009)

| Found | Replace with |
|---|---|
| `@EnableWebMvc` | Delete it; keep customisations in a `WebMvcConfigurer` |
| `WebMvcConfigurerAdapter` | `implements WebMvcConfigurer` (all methods are defaults) |
| `WebSecurityConfigurerAdapter` | A `SecurityFilterChain` bean, lambda DSL (`security-to-boot.md`) |
| `InternalResourceViewResolver` | Delete; Thymeleaf's resolver is auto-configured |
| `ContextLoaderListener`, a registered `DispatcherServlet` | Delete; Boot starts one context and one `DispatcherServlet` |
| `ClassPathXmlApplicationContext` / `XmlWebApplicationContext` | Inject the dependency; if code looked up beans, inject `ObjectProvider`/`ApplicationContext` |
| hand-built `DataSource`, `LocalContainerEntityManagerFactoryBean`, `DataSourceTransactionManager`, `JpaTransactionManager` | Delete; `spring.datasource.*`, `spring.jpa.*` (`data-access-to-boot.md`) |
| `PropertyPlaceholderConfigurer`, `CommonsMultipartResolver` | Delete; `application.yml`, `spring.servlet.multipart.*` |

Carry every setting over before you delete — a deleted manual bean with a non-default setting is a regression, not a fix.

## Bean-wiring failures after removing XML or manual beans

- **`NoSuchBeanDefinitionException` / `UnsatisfiedDependencyException`:** a bean existed in the deleted XML and was not converted. Search the deleted XML (use `git show HEAD:<path>` or the Modify Result) for the bean id/type, then declare it: stereotype annotation if it is your class, `@Bean` in a `@Configuration` if it is a library type. If a type is not found by scanning, the class lives outside the `@SpringBootApplication` package: move the application class up, or add `scanBasePackages`. A property placeholder `Could not resolve placeholder` means a key did not move to `application.yml`.
- **Bean looked up by name fails:** the converted bean lost its name — restore it with `@Service("name")` / `@Bean("name")`.
- **`BeanDefinitionOverrideException` / `NoUniqueBeanDefinitionException` / `The bean 'x' could not be registered`:** two definitions of one bean — XML plus Java, or a manual bean plus Boot's. Delete the redundant one; keep the customisation as a property or `Customizer`. **`spring.main.allow-bean-definition-overriding=true` is not a fix**, and neither is `@Primary` added to hide the duplicate. If a second bean of the same type is intended (two `DataSource`s), name them and qualify at the injection points.
- **Auto-configuration backs off silently:** a leftover `@EnableWebMvc`, a `DataSource` bean, or a `@Configuration` defining `ObjectMapper` disables Boot's. Remove it.
- **`@Transactional` not applied:** the method is `private`/self-invoked, or the XML `<tx:advice>` pointcut covered methods no annotation does — put `@Transactional` on the same service methods the pointcut matched.
- **Spring Security:** `403` everywhere → CSRF now on for state-changing requests the old config exempted; `/login` loops → `requestMatchers` order (first match wins; `anyRequest()` last); `NoSuchMethodError` on `authorizeRequests`/`antMatchers`/`and()` → the lambda DSL.
- **Jakarta leftovers at runtime:** `ClassNotFoundException: javax.servlet…` → an old library still in the dependency tree (`mvn dependency:tree`); replace or remove it, never add the `javax` jar back.

Add each repaired finding or wiring failure to `## Lessons`, written without file paths or project names.
