# Spring Boot 4 — Dependency Model & Conflict Cleanup

Target the newest Spring Boot 4.x release and let Boot's dependency management own every version it manages — an explicit `<version>` on a Boot-managed artifact is itself a conflict waiting to happen.

## Parent / BOM

```xml
<parent>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter-parent</artifactId>
  <version><!-- newest 4.x release --></version>
  <relativePath/>
</parent>

<properties>
  <!-- the parent derives maven.compiler.release from this; keep the plan's target level -->
  <java.version>25</java.version>
</properties>
```

- With the parent, express the compiler level as `<java.version>` and remove `maven.compiler.source` / `target` / `release` properties and JDK-activated profiles that set them.
- If the pom already has a corporate parent, import `org.springframework.boot:spring-boot-dependencies` (type `pom`, scope `import`) in `<dependencyManagement>` instead, and give `spring-boot-maven-plugin` an explicit `repackage` execution.

## Starters

| Need | Starter |
|---|---|
| Spring MVC / REST, embedded Tomcat, JSON | `spring-boot-starter-webmvc` — Spring Boot 4's name for the web starter. If the chosen 4.x release doesn't publish it, use `spring-boot-starter-web`. |
| Persistence | `spring-boot-starter-data-jpa` (Hibernate ORM 7, Jakarta Persistence 3.2, HikariCP) |
| Views | `spring-boot-starter-thymeleaf` |
| Bean Validation | `spring-boot-starter-validation` (only if the code uses validation annotations) |
| Security | `spring-boot-starter-security` (only if the app already has security) |
| Health / readiness probes | `spring-boot-starter-actuator` |
| Tests | `spring-boot-starter-test` (test scope) |

## Remove — conflicting or redundant with Spring Boot 4

| Legacy dependency / plugin | Why it conflicts | Replacement |
|---|---|---|
| `org.springframework:spring-*` with explicit versions (`spring-webmvc`, `spring-jdbc`, `spring-orm`, `spring-tx`, `spring-context`, …) | Mixed Spring versions on the classpath → `NoSuchMethodError` / `ClassNotFoundException` at startup | The starters above; versions come from the Boot BOM |
| `javax.servlet:javax.servlet-api`, `jakarta.servlet:jakarta.servlet-api` (provided) | Duplicates the embedded Tomcat's own Servlet API (and the `javax` one is the wrong namespace) | Nothing — the embedded Tomcat supplies it |
| `javax.servlet:jstl`, `taglibs:standard`, Jakarta JSTL, `org.apache.tomcat.embed:tomcat-embed-jasper` | Only needed for JSP, which an executable JAR cannot serve | Thymeleaf (`references/jsp-to-thymeleaf.md`) — keep these only until the JSP views are converted |
| `commons-dbcp`, `commons-dbcp2`, `c3p0`, `tomcat-jdbc` | A second connection pool next to Boot's HikariCP | HikariCP (default) — map pool settings to `spring.datasource.hikari.*` |
| `com.fasterxml.jackson.core:jackson-databind` / `jackson-core` with explicit versions | Spring Boot 4 defaults to Jackson 3 (`tools.jackson.*` packages); an explicit Jackson 2 databind puts two JSON stacks on the classpath | Jackson 3 via the web starter. Annotations stay in `com.fasterxml.jackson.annotation`; imports of `com.fasterxml.jackson.databind` / `.core` move to `tools.jackson.databind` / `.core` |
| `Jackson2ObjectMapperFactoryBean`, `MappingJackson2HttpMessageConverter` bean definitions | Jackson 2 configuration classes | `spring.jackson.*` properties (date format, inclusion, indentation) |
| `org.hibernate:hibernate-core` / `hibernate-entitymanager` / `javax.persistence:javax.persistence-api` / `org.hibernate:hibernate-validator` with explicit versions | Wrong namespace and version next to Boot's Hibernate 7 / Jakarta Persistence 3.2 | `spring-boot-starter-data-jpa` / `spring-boot-starter-validation` |
| `log4j:log4j` 1.x, `org.slf4j:slf4j-log4j12`, `slf4j-simple`, explicitly versioned `logback-classic`, `commons-logging:commons-logging` | Several logging backends / SLF4J bindings | `spring-boot-starter-logging` (Logback, included by every starter). Code using `org.apache.commons.logging.Log` keeps compiling |
| `javax.annotation-api`, `javax.transaction-api`, `javax.xml.bind:jaxb-api`, `javax.mail` | `javax` namespace | The Jakarta artifact, only if the code still uses the API (see the namespace map) |
| `spring-boot-starter-undertow` | Spring Boot 4 no longer supports Undertow | Tomcat (default) or Jetty |
| `maven-war-plugin`, `jetty-maven-plugin`, `tomcat7-maven-plugin`, `cargo-maven*-plugin` | WAR / external-container tooling | `spring-boot-maven-plugin` (`mvn spring-boot:run`, `java -jar`) |
| JDBC driver with an old artifact id and explicit version (e.g. `ojdbc6`, `ojdbc8`) | Built for old JDKs | The current artifact (e.g. `com.oracle.database.jdbc:ojdbc11`) with the Boot-managed version — unless a companion migration such as `oracle-19c-to-23ai` owns the driver, in which case leave it to that migration |
| `junit:junit` 3.x | Too old for the JUnit Platform that `spring-boot-starter-test` runs on | If the JUnit upgrade was **not** requested: `junit:junit` 4.13.2 (still runs `TestCase`-style tests) + `org.junit.vintage:junit-vintage-engine` (test scope). If it was requested: migrate the tests to JUnit Jupiter and remove both |

After the cleanup, go through the pom once more and delete the `<version>` of every artifact the Boot BOM manages.

## Spring Boot 4 / Spring Framework 7 changes that commonly break the build

- **Jackson 3:** packages `tools.jackson.*`, while annotations keep `com.fasterxml.jackson.annotation`. Custom `ObjectMapper` beans are Jackson 2 — replace them with `spring.jackson.*` properties where they only set standard options.
- **Hibernate 7 / Jakarta Persistence 3.2:** entity annotations live in `jakarta.persistence`; Hibernate-native `Session`/`HibernateTemplate` code does not carry over — use Spring Data JPA.
- **Spring MVC 7:** suffix-pattern and trailing-slash matching are off (`/cities/St. Louis` stays intact — no config needed). Replace `@RequestMapping(method = GET)` with `@GetMapping` and friends while touching controllers.
- **Servlet 6.1 / Tomcat 11** is the embedded container.
