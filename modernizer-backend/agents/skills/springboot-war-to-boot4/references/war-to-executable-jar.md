# WAR → Executable JAR (Embedded Container)

The application stops being deployed into someone else's servlet container and becomes a self-contained `java -jar` process. Everything the external container used to supply must now come from the application's own configuration. Anything missed here is a **silent runtime regression**: the app still compiles, but the behaviour is gone.

The result is always an executable **JAR** — never a WAR, and never an "executable WAR" kept alive for JSPs (convert JSPs with `jsp-to-thymeleaf.md` instead).

## Build file

**Maven**
- `<packaging>war</packaging>` → `<packaging>jar</packaging>` (or remove the element — `jar` is the default).
- `spring-boot-starter-tomcat`: remove the `provided` scope, or remove the explicit dependency entirely — the web starter already brings the embedded Tomcat.
- Remove `maven-war-plugin` and external-container plugins (`jetty-maven-plugin`, `tomcat7-maven-plugin`, cargo). If one of them set the context path, carry it over to `server.servlet.context-path`.
- Keep `spring-boot-maven-plugin`. With `spring-boot-starter-parent` its `repackage` goal is already bound; without the parent, add an `<execution>` with `<goal>repackage</goal>`.
- `<finalName>`: keep it if deployment tooling expects a specific file name; the artifact is now `<finalName>.jar`.

**Gradle**
- Remove the `war` plugin; `bootWar` → `bootJar`; drop `providedRuntime` / `providedCompile` container entries.

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
| `WEB-INF/web.xml` (**ignored** by an embedded container) | Java config / `application.yml` via `webxml-to-javaconfig.md`, then delete `web.xml` | Only for entries with no equivalent |
| `ContextLoaderListener` / `DispatcherServlet` + their XML contexts | Spring Boot auto-configuration + component scanning; delete the XML files | No |
| `CharacterEncodingFilter` (UTF-8, force) | `server.servlet.encoding.charset: UTF-8`, `server.servlet.encoding.force: true` | No |
| `@WebServlet` / `@WebFilter` / `@WebListener` classes (the container scanned them) | `@ServletComponentScan` on `Application`, or `ServletRegistrationBean` / `FilterRegistrationBean` beans | No |
| Context path = WAR file name (e.g. `/orders-service`) | `server.servlet.context-path: /orders-service` — preserves existing URLs | Yes, if it changes |
| JNDI DataSource (`spring.datasource.jndi-name`, `<jee:jndi-lookup>`, a `jndi` profile, `context.xml` `<Resource>`) | `spring.datasource.url` / `username` / `password` bound to environment variables; delete the JNDI profile | **Yes** — ops must supply the env vars |
| Connector port, TLS (`server.xml`) | `server.port`, `server.ssl.*` | Yes |
| Container-managed security realm / `<login-config>` | Spring Security configuration | Yes |
| `<session-config>` | `server.servlet.session.timeout`, `server.servlet.session.cookie.*` | No |
| `<error-page>` | `server.error.*` + an `ErrorController` or `@ControllerAdvice` | No |
| Default servlet serving static files (`<mvc:default-servlet-handler/>`) | Boot's static resource handling from `classpath:/static/` | No |
| Container access logs | `server.tomcat.accesslog.*` + the application's own logging | Yes |

## Static resources and the webapp directory

`src/main/webapp/{css,js,images,*.html}` → `src/main/resources/static/` (served at the same URLs). JSP views → `src/main/resources/templates/` via `jsp-to-thymeleaf.md`. When nothing is left, delete `src/main/webapp` entirely.

## Cloud-native readiness

- `spring-boot-starter-actuator` with `management.endpoint.health.probes.enabled: true` for liveness/readiness probes.
- `server.shutdown: graceful`.
- Every environment-specific value (URLs, credentials, ports) comes from environment variables.

## Validation

The validator runs `package`, not just `compile`, so a broken repackage (for example a missing `repackage` execution) fails the build. After packaging, the artifact is `target/<name>.jar`.
