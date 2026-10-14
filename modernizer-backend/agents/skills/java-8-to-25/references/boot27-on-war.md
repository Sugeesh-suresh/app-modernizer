# Spring Boot 2.7 on a WAR (javax, external container, Java 17)

Target: the newest Spring Boot 2.7.x (2.7.18 is the final open-source 2.7 release), Spring Framework 5.3, `javax.*`, on Java 17, still deployed as a WAR to the existing external container.

## Plain-Spring → Spring Boot starter map

| Legacy dependency | Replace with (version managed by Boot 2.7) |
|---|---|
| `spring-webmvc`, `spring-web`, `jackson-databind` | `spring-boot-starter-web` |
| `spring-jdbc`, `spring-tx` | `spring-boot-starter-jdbc` |
| `spring-orm` + `hibernate-core` 5.x + `javax.persistence-api` | `spring-boot-starter-data-jpa` |
| `spring-security-web` / `-config` | `spring-boot-starter-security` |
| `hibernate-validator` 6.x / `validation-api` | `spring-boot-starter-validation` |
| `logback-classic` / `slf4j-api` | `spring-boot-starter-logging` (default — no explicit entry needed) |
| `log4j` 1.x / `log4j-core` 2.x as the logging backend | `spring-boot-starter-log4j2`, excluding `spring-boot-starter-logging` |
| `javax.servlet-api` (provided) | Remove — `spring-boot-starter-tomcat` (provided) supplies it for compilation |
| JDBC driver (e.g. `ojdbc8`) | Keep; drop its explicit `<version>` only if Boot 2.7 manages it |
| Connection pool (`commons-dbcp`, `c3p0`) | Keep unless the plan says to switch to HikariCP; configure via `spring.datasource.type` |

Always keep dependencies Boot doesn't manage (vendor SDKs, in-house libraries) with their explicit versions.

## Composition root

```java
@SpringBootApplication
@ImportResource("classpath:applicationContext.xml") // only if XML bean definitions exist
public class Application extends SpringBootServletInitializer {
    @Override
    protected SpringApplicationBuilder configure(SpringApplicationBuilder builder) {
        return builder.sources(Application.class);
    }
    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}
```

- Put it in the root package, above all `@Component`/`@Controller` classes, so component scanning still finds them. If it can't go there, add `scanBasePackages`.
- XML contexts under `WEB-INF/` that `@ImportResource` needs: move them to `src/main/resources/` and reference them with `classpath:`.
- Remove `@EnableWebMvc` from existing config classes — it switches off Boot's MVC auto-configuration. The exception is when the app deliberately takes full control of MVC; keep it then, and say so.
- `<context:property-placeholder location="classpath:app.properties"/>` → keep the file, and load it with `@PropertySource`, or rename its keys into `application.properties` if the plan says so.

## Deployment stays identical

- JNDI DataSources: keep them — `spring.datasource.jndi-name=java:comp/env/jdbc/<name>` — the container still provides them.
- `<packaging>war</packaging>`; `spring-boot-starter-tomcat` `provided`; the WAR file name is unchanged.
- The container stays on a Java EE 8 / Servlet 4 container (e.g. Tomcat 9).

## Java level

This stage runs on Java 17, which the preceding JDK stage set up. Spring Boot 2.7 / Spring Framework 5.3 support Java 8 through 21, so this is a supported, deployable combination (Tomcat 9 runs on Java 17 too). It's also why the Java 25 upgrade waits until after the Spring Boot 3.x stage — never leave a Spring Boot 2.x codebase on a Java 25 compiler release, and never change the compiler release in this stage.

## The test engine, and what Boot 2.7 manages that is older than the earlier stages set

- **JUnit 4 tests need the Vintage engine from the first Boot stage.** `spring-boot-starter-test` stopped bringing `junit-vintage-engine` in 2.4: with only Jupiter on the test classpath Surefire runs zero JUnit 4 tests and reports success. When the repository has JUnit 4 tests and the plan does not convert them, add `org.junit.vintage:junit-vintage-engine` (test scope, version managed by Boot) in the same task that introduces the starter, and check that the test count did not drop.
- **Boot 2.7.18 manages older libraries than the Java 17 stages may have set** (Spring Framework 5.3.x, Jackson 2.13.x, Mockito 4.5.x and its Byte Buddy). "Never regress a version" wins over the BOM: override the BOM's version properties in the parent (`spring-framework.version`, `jackson-bom.version`, `mockito.version`, `byte-buddy.version`) with the versions the previous stage set, and drop each override at the stage where Boot's own managed version is no longer older (Boot 3.x / 4.x).
- **A library on `jaxb-impl` 2.3.0** (Apache Camel 2.x, older JAX-B users) fails on Java 17 with `Injector.defineClass is null`: pin `jaxb-impl` and `jaxb-core` 2.3.9 / `jaxb-api` 2.3.1 until the library itself moves; Boot 2.7 does not manage them.
