# Intermediate WAR Stages (incremental runs only)

This applies ONLY to the intermediate Spring Boot stages of an incremental run — Spring Boot 2.7, 3.x and 4.x — while the app still deploys as a WAR to its external container. The final stage always converts it to an executable JAR (`springboot-war-to-boot4`'s `references/war-to-executable-jar.md`). Until that stage, keep the app deployable exactly as before: stripping `SpringBootServletInitializer`, deleting `web.xml` entries without a replacement, or bundling an embedded Tomcat into the WAR would break the intermediate deployments.

## pom.xml / build.gradle rules (intermediate stages)

| Item | Rule |
|---|---|
| `<packaging>` | Stays `war` until the final "Convert WAR → Executable JAR" stage |
| Embedded server starter (`spring-boot-starter-tomcat` / `-jetty`) | Add if missing (for local `spring-boot:run` and tests) with `provided` scope, so the external container's runtime wins at deployment |
| `spring-boot-starter-web` / `-webmvc` | Normal compile-scope dependency — it brings Spring MVC |
| `spring-boot-maven-plugin` | Keep configured for WAR packaging during these stages |
| Final artifact name | Keep the existing WAR file name / context-path convention |

## SpringBootServletInitializer

Each intermediate stage needs exactly one composition root extending `SpringBootServletInitializer`. If the legacy app already has a `main()`-based bootstrap class, extend it in place rather than creating a second entry point:

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

The final JAR stage removes the superclass and the `configure()` override and keeps `main`.

## Custom ServletContainerInitializer / HandlesTypes

If the legacy app registers its own `META-INF/services/javax.servlet.ServletContainerInitializer` (renamed to `jakarta.servlet.ServletContainerInitializer` in the Spring Boot 3.x stage), don't delete it as "redundant with Spring Boot". First read the class it points to:
1. If it only bootstrapped Spring itself, remove it and say so in the Modify Result.
2. If it does something Spring Boot doesn't (e.g. registers a vendor SDK's listeners), keep it and migrate its imports. The final JAR stage then turns it into a `ServletContextInitializer` bean, because an embedded container doesn't run `META-INF/services` initializers from the application JAR.

## web.xml during the intermediate stages

`web.xml` can coexist with `SpringBootServletInitializer`. Migrate entries away as the stage's plan section says:
- Spring bootstrap entries (`ContextLoaderListener`, `DispatcherServlet`, `contextConfigLocation`) → superseded by `SpringBootServletInitializer` + auto-configuration.
- Servlets, filters and listeners → Spring `@Bean` registrations (`webxml-to-javaconfig.md`).
- Anything the plan defers stays, with an explicit note. By the end of the final JAR stage `web.xml` must be gone, because an embedded container ignores it.
