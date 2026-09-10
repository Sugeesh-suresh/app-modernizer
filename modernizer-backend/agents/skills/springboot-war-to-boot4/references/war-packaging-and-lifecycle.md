# WAR Packaging & Lifecycle Rules — Spring Boot 4 on an External Container

## Why this is not just "a Spring Boot upgrade"

A default migration agent assumes the target is a standalone JAR with an embedded server, because that's the common case. When the actual target is an external Jakarta EE 11+ container (a shared Tomcat/Jetty instance managed by ops, a cloud platform's managed servlet runtime, etc.), that assumption is actively wrong: stripping `SpringBootServletInitializer`, deleting `web.xml` entries with no replacement, or bundling an embedded Tomcat into the WAR all break deployment. Treat "stay a WAR, stay hooked into an external container" as a hard constraint, not a style preference.

## pom.xml / build.gradle rules

| Item | Rule |
|---|---|
| `<packaging>` | Must remain `war`. Never change to `jar`. |
| Embedded server starter (`spring-boot-starter-tomcat` / `-jetty` / `-undertow`) | Add if missing (needed for local `bootRun`/IDE testing), scope it `provided` so the external container's own runtime wins at deployment. Never remove it entirely — local dev and integration tests still need it. |
| `spring-boot-starter-web` | Keep as a normal (compile-scope) dependency — it pulls in Spring MVC, not the container. |
| `spring-boot-maven-plugin` / Gradle Spring Boot plugin | Keep configured for WAR packaging; do not switch its `<executable>` or launcher settings to JAR-style bootable-jar options. |
| Final artifact name | Preserve the existing WAR filename/context-path convention the container's deployment tooling already expects, unless the plan explicitly calls for renaming it. |

## SpringBootServletInitializer

Every WAR-targeting Spring Boot application needs exactly one composition root extending `SpringBootServletInitializer`. If the legacy app already has a `main()`-based bootstrap class, extend it in place rather than creating a second entry point:

```java
@SpringBootApplication
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

`configure()` is what the external container calls at deployment time via the Servlet 6.1/Jakarta EE 11 `ServletContainerInitializer` mechanism that Spring Boot registers automatically — do not hand-roll a competing `ServletContainerInitializer` unless the legacy app had a genuinely custom one (see below).

## Custom ServletContainerInitializer / HandlesTypes

If the legacy app registers its own `META-INF/services/jakarta.servlet.ServletContainerInitializer` (commonly for third-party framework integration, e.g. a legacy JSF or a custom annotation scanner), do not delete it as "redundant with Spring Boot." Instead:
1. Confirm what it actually does — read the class it points to.
2. If its job is now handled by Spring Boot auto-configuration (e.g. it was only there to bootstrap Spring itself), remove it and note the removal explicitly in the modify/fix summary.
3. If it does something Spring Boot doesn't (e.g. registers a legacy vendor SDK's own listeners), keep it, but migrate its `javax.servlet.*` imports to `jakarta.servlet.*` per the namespace map.

## web.xml interaction

A `web.xml` can coexist with `SpringBootServletInitializer`, but every entry in it should be **migrated away**, not left in place by default:
- Servlets/filters/listeners declared in `web.xml` → Spring `@Bean`-registered equivalents (see `webxml-to-javaconfig.md`).
- `<display-name>`, `<description>` → safe to delete, purely cosmetic.
- Anything genuinely inexpressible in current Spring Boot configuration (rare — e.g. a container-vendor-specific extension element) → keep it, and say so explicitly in the fix/modify summary so a human reviewer knows it's intentional, not an oversight.

Once every migratable entry is gone, delete `web.xml` entirely rather than leaving an empty shell.

## Local testing vs. production deployment

Because the embedded-server starter is `provided`-scoped, `mvn spring-boot:run` / `gradle bootRun` and IDE run configurations still work unchanged for local development — `provided` scope is available at compile and test time, just excluded from the final WAR. Do not add profile-specific dependency exclusions to compensate for this; the scope declaration alone is sufficient and is the standard Spring Boot WAR pattern.
