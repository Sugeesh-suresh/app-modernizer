# WAR → Executable JAR (Embedded Container)

The application stops being deployed into someone else's servlet container and becomes a self-contained `java -jar` process. Everything the external container used to supply now has to come from the application's own configuration. Anything missed here is a **silent runtime regression**: it still compiles, but the behaviour is gone.

## Build file

**Maven**
- `<packaging>war</packaging>` → `<packaging>jar</packaging>` (or remove the element — `jar` is the default).
- `spring-boot-starter-tomcat`: remove the `provided` scope, or remove the explicit dependency entirely — `spring-boot-starter-web` already brings the embedded Tomcat.
- Remove `maven-war-plugin` configuration (`failOnMissingWebXml`, `warName`, overlays). If `warName` set the deployed context path, carry it over to `server.servlet.context-path` (see below).
- Keep `spring-boot-maven-plugin`. With `spring-boot-starter-parent` its `repackage` goal is already bound; without the parent, add an `<execution>` with `<goal>repackage</goal>`.
- `<finalName>`: keep it if deployment tooling expects a specific file name; the artifact is now `<finalName>.jar`.

**Gradle**
- Remove the `war` plugin; `bootWar` → `bootJar`; `providedRuntime`/`providedCompile` entries for the container → remove them (the starter brings them).

## Application class

```java
@SpringBootApplication
public class Application {           // no longer extends SpringBootServletInitializer
    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}
```
Delete the `configure(SpringApplicationBuilder)` override along with the superclass.

## Everything the container used to provide

| Came from the external container | Now comes from | Flag for ops? |
|---|---|---|
| `WEB-INF/web.xml` (**ignored** by an embedded container) | Java config / `application.yml` via `springboot-war-to-boot4`'s `references/webxml-to-javaconfig.md` — then delete `web.xml` | Only for entries with no equivalent |
| `@WebServlet` / `@WebFilter` / `@WebListener` classes (the container scanned them) | Add `@ServletComponentScan` to `Application`, or register them as `ServletRegistrationBean` / `FilterRegistrationBean` beans | No |
| Context path = WAR file name (e.g. `/weather`) | `server.servlet.context-path=/weather` — preserve existing URLs | Yes, if it changes |
| JNDI DataSource (`spring.datasource.jndi-name`, `<jee:jndi-lookup>`, `context.xml` `<Resource>`) | `spring.datasource.url` / `username` / `password` bound to environment variables (`${DB_URL}` …) — never hard-code credentials | **Yes** — ops must supply the env vars |
| Connector port, TLS (`server.xml`) | `server.port`, `server.ssl.*` | Yes |
| Container-managed security realm / `<login-config>` | Spring Security configuration | Yes |
| `<session-config>` | `server.servlet.session.timeout`, `server.servlet.session.cookie.*` | No |
| `<error-page>` | `server.error.*` + an `ErrorController` or `@ControllerAdvice` | No |
| Container access / catalina logs | `server.tomcat.accesslog.*` + the application's own logging | Yes |

## Static resources

`src/main/webapp/{css,js,images,*.html}` → `src/main/resources/static/` (served at the same URLs). `src/main/webapp/WEB-INF/` has no meaning in a JAR — nothing may be left there except the JSPs handled below.

## JSP guard — do not break the views

Spring Boot **cannot serve JSPs from an executable JAR** (an embedded-container limitation). If `src/main/webapp/**/*.jsp` exists:
1. Do NOT delete, move or convert the JSPs in this stage.
2. Produce an **executable WAR** instead: keep `<packaging>war</packaging>`, make `spring-boot-starter-tomcat` compile scope, add `org.apache.tomcat.embed:tomcat-embed-jasper` (and JSTL if used), and keep `SpringBootServletInitializer`. The result still runs standalone with `java -jar app.war` on an embedded container, and remains deployable to an external container.
3. State this prominently in the Modify Result as a deliberate deviation from "executable JAR". Name the follow-up: migrate the views to Thymeleaf, or to React via the `jsp-to-react-bff` pattern, and then re-run this stage.

## Cloud-native readiness (only where the plan asks for it)

- `spring-boot-starter-actuator` with `management.endpoint.health.probes.enabled=true` for liveness/readiness probes.
- `server.shutdown=graceful`.
- Externalise every environment-specific value (URLs, credentials, ports) to environment variables or config imports.

## Validation

This stage's validator runs `package`, not just `compile`, so a broken repackage (for example a missing `repackage` execution) fails the stage. After packaging, the artifact is `target/<name>.jar` (or `.war` under the JSP fallback).
