# Boot conformance rules (the pipeline's scanner)

After the last stage the pipeline scans the workspace and emits the findings below. **Error-level findings fail validation and must all disappear; warnings are reported.** Read this before planning so each finding is pre-empted, and use it to self-check every edit. A finding carries a code, a file and usually a line; the validator passes each error on as `BOOT: <code> — <message>`. The patterns below are the ones the scanner is specified to match — treat them as the minimum, not as the whole of what "conformant" means (the end state in SKILL.md is the standard; a reviewer checks it too).

## Errors (fail validation)

| Code | What the scanner matches | Make it disappear |
|---|---|---|
| **B001** | packaging `war`, `maven-war-plugin`, the Gradle `war` plugin | `jar` packaging; remove the plugin |
| **B002** | a `web.xml`; a `WebApplicationInitializer` or `SpringBootServletInitializer` subclass | translate and delete `web.xml`; remove the initializer; the application class only has `main` |
| **B003** | no `@SpringBootApplication` class | add exactly one, in the root package |
| **B004** | `.jsp` files, or `src/main/webapp/WEB-INF` still present | JSP → Thymeleaf, assets → `src/main/resources/static`, delete the directory |
| **B005** | Spring XML bean files: `<beans …>` roots, `applicationContext*.xml`, `*-servlet.xml` | convert the beans, delete the file (`xml-and-web-xml-to-boot.md`) |
| **B006** | an explicit `org.springframework:spring-*`, `org.springframework.security:spring-security-*`, `org.springframework.data:spring-data-*`, or `org.springframework.integration` / `batch` / `amqp` / `kafka` / … dependency that has a `spring-boot-starter-*` replacement — the message names the starter | replace it with the named starter, with no `<version>` |
| **B007** | no Boot parent and no `spring-boot-dependencies` BOM; or `spring-boot-maven-plugin` missing, or without `repackage` | add the parent/BOM (newest 4.x) and the plugin with a `repackage` execution. A hand-set `<version>` on a managed dependency is the warning W101, not this error |
| **B008** | `javax.servlet`, `javax.persistence`, `javax.validation`, `javax.annotation`, `javax.jms`, `javax.mail`, `javax.transaction`, `javax.ws.rs`, `javax.xml.bind` imports | `jakarta.*` (`java-8-to-25` › `jakarta-ee11-namespace-map.md`) and the matching artifact. Java SE `javax.sql`/`naming`/`crypto`/JAXP stay `javax` |
| **B009** | Java config that fights Boot: `@EnableWebMvc`; `WebMvcConfigurerAdapter`; `WebSecurityConfigurerAdapter`; `InternalResourceViewResolver`; `ContextLoaderListener`; a manually registered `DispatcherServlet`; `ClassPathXmlApplicationContext` / `XmlWebApplicationContext`; hand-built `DataSource`, `LocalContainerEntityManagerFactoryBean`, `DataSourceTransactionManager`, `JpaTransactionManager`, `PropertyPlaceholderConfigurer`, `CommonsMultipartResolver` beans | the table in `steps/fix.md`; carry settings into properties first |
| **B010** | another server (`spring-boot-starter-jetty`, `spring-boot-starter-undertow`, Tomcat excluded) or `spring-boot-starter-tomcat` with `provided` scope | remove them; embedded Tomcat comes with `spring-boot-starter-webmvc` |
| **B011** | no `application.properties` / `application.yml` | create `src/main/resources/application.yml` |

## Warnings (reported, not blocking)

| Code | What the scanner matches | Action |
|---|---|---|
| **B012** | old test runners: `SpringJUnit4ClassRunner`, `@RunWith(SpringRunner.class)` | `@SpringBootTest` / slices when the JUnit upgrade is in scope (`testing-to-boot.md`); otherwise list as deprecated |
| **B013** | `log4j.properties`, `log4j.xml`, explicit logging bindings | delete; `logging.*` properties or `logback-spring.xml`; drop `slf4j-log4j12`, `slf4j-simple`, versioned `logback-classic` |
| **W101** | a hand-set `<version>` on a Boot-managed dependency | delete the version; keep versions only for libraries Boot does not manage (Guava, vendor SDKs, in-house artifacts) |

## Pre-empt the scan: greps before you finish a task

Run these on the files your task touched (and, in the last stage, on the whole workspace). Every hit is either gone or has a plan-approved reason.

```
packaging|maven-war-plugin|bootWar|id 'war'              # B001
web.xml | WebApplicationInitializer | SpringBootServletInitializer     # B002
@SpringBootApplication                                    # B003: exactly one hit
*.jsp , src/main/webapp/WEB-INF                           # B004
<beans , applicationContext , -servlet.xml                # B005
<artifactId>spring-  (and spring-security-, spring-data-, spring-integration, spring-batch, spring-amqp, spring-kafka)   # B006
spring-boot-starter-parent | spring-boot-dependencies | repackage                                   # B007: present
import javax.(servlet|persistence|validation|annotation|jms|mail|transaction|ws.rs|xml.bind)       # B008
@EnableWebMvc | WebMvcConfigurerAdapter | WebSecurityConfigurerAdapter | InternalResourceViewResolver | ContextLoaderListener | DispatcherServlet | ClassPathXmlApplicationContext | XmlWebApplicationContext | DataSource | LocalContainerEntityManagerFactoryBean | TransactionManager | PropertyPlaceholderConfigurer | CommonsMultipartResolver   # B009
spring-boot-starter-(jetty|undertow|tomcat)               # B010
application.yml | application.properties                  # B011: present
SpringJUnit4ClassRunner | SpringRunner                    # B012
log4j | slf4j-log4j12 | slf4j-simple | logback-classic     # B013
<version> inside a dependency whose group the Boot BOM manages                                       # W101
```

## What is never an acceptable way to clear a finding

- `spring.main.allow-bean-definition-overriding=true`, `@Primary` added only to hide a duplicate bean, or an `exclude` of a Boot auto-configuration to keep a manual bean — each trades the finding for a different failure at startup or in review.
- Moving the offending code behind a comment, a rename, or `@ImportResource`; deleting a bean without carrying its settings over; deleting a test to remove its runner.
- Re-adding a legacy dependency (a servlet API, a second pool, Jackson 2 databind) to make something compile.

## When a finding is legitimate

A second `DataSource` (B009), a JSP tag library with no Thymeleaf equivalent (B004), or a vendor `ConnectionFactory` bean the broker starter cannot configure is a genuine exception the scan cannot tell apart from a leftover. These are **Open Questions in the plan**, decided by a person before the run, and the report lists them. An agent never decides one alone.

## The `boot:keep` marker (a person's decision, never yours)

A finding the plan's Open Questions let a person keep is silenced in code with a comment carrying its reason: `// boot:keep <reason>` on the offending line or on the line directly above it (Java), or `<!-- boot:keep <reason> -->` directly before a `<dependency>` (pom). The scan then reports it under "Kept on purpose" instead of failing, and the report lists every one. An agent adds the marker only for an exception the confirmed plan names; adding one to clear a finding on its own is the same as the shortcuts above.
