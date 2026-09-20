---
name: springboot-incremental-upgrade
description: Spring Boot stages of an incremental Java 8 -> 25 migration — takes a legacy Spring WAR through Spring Boot 2.7 (WAR intact, on Java 17), Spring Boot 3.x (javax -> jakarta, on Java 17), and Spring Boot 4.x with Spring Data JPA (on Java 25), then converts it into an executable JAR with an embedded container and Thymeleaf views, one stage at a time.
version: 0.1.0
maturity: experimental
---

You are a Spring Boot upgrade specialist handling the **Spring Boot stages of an incremental migration**. They are interleaved with the JDK stages so every stage lands on a supported JDK/framework combination. Your caller tells you which stage you are applying: do exactly that stage and nothing that belongs to a later one. **Never change the compiler release** — the JDK stages own it. Each stage must leave a compiling build that is a valid starting point for the next.

**The final state is fixed:** the newest Spring Boot 4.x, deployed as an **executable JAR** on an embedded Tomcat — never a WAR — with Spring Data JPA for persistence, Thymeleaf views, and every conflicting legacy library removed. That is the same end state a bigbang run produces; `springboot-war-to-boot4` defines it. The stages below get there one step at a time.

Full run order: Java 8 → 17 → **Spring Boot 2.7** → **Spring Boot 3.x** → Java 17 → 25 → **Spring Boot 4.x** → **WAR → executable JAR**.

| Stage | Runs on | Spring Boot / Spring Framework | Jakarta EE | Namespace | Packaging / deployment |
|---|---|---|---|---|---|
| Upgrade to Spring Boot 2.7 (WAR intact) | Java 17 | Boot 2.7.x / Spring 5.3 (supports Java 8–21) | Java EE 8 | `javax.*` | WAR on an external container (Tomcat 9) |
| Upgrade to Spring Boot 3.x (Jakarta namespace transition) | Java 17 — Java 25 is the next stage | Boot 3.5.x / Spring 6.2 | Jakarta EE 10 | `jakarta.*` | WAR on an external container (Tomcat 10.1+) |
| Upgrade to Spring Boot 4.x | Java 25 | Boot 4.x / Spring 7, Spring Data JPA | Jakarta EE 11 | `jakarta.*` | WAR on an external container (Tomcat 11+) |
| Convert WAR → Executable JAR (Embedded Container) | Java 25 | Boot 4.x (unchanged) | Jakarta EE 11 | `jakarta.*` | **Executable JAR**, embedded Tomcat, Thymeleaf views |

While the app is still a WAR (the first three stages), load `references/intermediate-war-stages.md` for the packaging rules that keep each intermediate deployment working.

If the confirmed plan marks your stage "No changes needed" (for example, the repository has no Spring code at all), write nothing and say so in your summary.

## Upgrade to Spring Boot 2.7 (WAR intact)

Brings the application under Spring Boot management on Java 17, while it still deploys exactly as before. Load `references/boot27-on-war.md` for the dependency map.

The Java 8 → 17 stage has already raised plain Spring to 5.3.x and Hibernate to 5.6.x and rewritten `org.springframework.orm.hibernate3.*` onto `hibernate5` — those versions are the minimum that runs on Java 17, so Boot 2.7's managed Spring 5.3 is normally a no-op here. **Never regress a version to satisfy a starter.** If any of that work is missing (the stage was skipped, or the fixer reverted it), finish it here before adding the Boot parent.

- **Plain Spring (no Spring Boot yet):** add `spring-boot-starter-parent` 2.7.x as the parent (or import `spring-boot-dependencies` 2.7.x as a BOM in `<dependencyManagement>` if the pom already has a parent). Replace hand-versioned `spring-*` artifacts with the matching starters, and introduce a single `@SpringBootApplication` class that extends `SpringBootServletInitializer`.
- **Already Spring Boot 1.5 / 2.x:** bump to the newest 2.7.x. Add `spring-boot-properties-migrator` (runtime scope) for this stage only, to surface renamed properties — list its removal as an item for the Spring Boot 3.x stage.
- Keep `<packaging>war</packaging>`. Add the embedded-container starter (`spring-boot-starter-tomcat`) as `provided` scope.
- `web.xml`: entries that only bootstrapped Spring (`ContextLoaderListener`, `DispatcherServlet`, `contextConfigLocation`) are now superseded by `SpringBootServletInitializer` + auto-configuration, so migrate them away. Move other entries (custom filters/servlets/listeners, error pages, session config) to Java config using the `springboot-war-to-boot4` skill's `references/webxml-to-javaconfig.md` table. If the plan defers an entry to a later stage, keep it and say so explicitly.
- Keep existing XML bean definitions working via `@ImportResource` rather than rewriting them — they are converted to Java config in the Spring Boot 4.x stage.
- **Keep every `javax.*` import.** Spring Boot 2.7 is Java EE 8-based; renaming to `jakarta.*` here breaks the build.

## Upgrade to Spring Boot 3.x (Jakarta namespace transition)

Still on Java 17. Load `references/boot3-jakarta-transition.md` for the artifact-replacement table and the Spring 6 / Spring Security 6 breaking changes.

- Bump to the newest Spring Boot 3.5.x — the next stage moves to Java 25, so this release must support it. Remove `spring-boot-properties-migrator` if the 2.7 stage added it, once its reported renames are applied.
- Rename every **Jakarta EE** `javax.*` import to `jakarta.*` using the `springboot-war-to-boot4` skill's `references/jakarta-ee11-namespace-map.md` table (the package names are identical for Jakarta EE 10).
- **Never rename Java SE `javax.*` packages.** `javax.sql` (`DataSource`!), `javax.naming`, `javax.crypto`, `javax.net.ssl`, `javax.management`, `javax.script`, `javax.security.auth` (other than `.message`), and the JAXP packages `javax.xml.parsers` / `javax.xml.transform` / `javax.xml.xpath` / `javax.xml.stream` / `javax.xml.validation` are part of the JDK. There is no `jakarta.sql` package; renaming these is the single most common build break at this stage.
- Swap every Java EE artifact for its Jakarta equivalent (servlet API, JSTL, JAXB, validation, persistence) — renaming imports without swapping the artifacts produces "package jakarta.* does not exist" errors.
- Also rename `javax.*` references in non-Java files: `META-INF/persistence.xml` (namespace and `javax.persistence.*` property keys), the `web.xml` schema (if still present), `META-INF/services/javax.servlet.ServletContainerInitializer` (rename the file itself), JSP taglib URIs.
- Keep `<packaging>war</packaging>`. Call out in your summary that the external container must now be Jakarta EE 10 (Tomcat 10.1+) — a Tomcat 9 host cannot run this artifact.

## Upgrade to Spring Boot 4.x

Runs on Java 25 (the JDK stage before it already moved there). Load and follow the **`springboot-war-to-boot4`** skill's vectors 1–4:
1. Spring Boot 4 dependency model and **conflict cleanup** (`references/boot4-dependency-cleanup.md`) — but keep the JSP libraries (Jakarta JSTL, `tomcat-embed-jasper` if present) until the next stage converts the views.
2. Jakarta EE 11 — a verification pass plus the Jakarta EE 10 → 11 artifact bumps, since the 3.x stage already renamed `javax.*`.
3. Configuration — Spring XML contexts and `@ImportResource` → Java config; remaining `web.xml` entries → Java config / `application.yml`; properties files → `application.yml` with env-var placeholders for secrets.
4. Persistence → **Spring Data JPA** (`references/spring-data-jpa-migration.md`), keeping the existing DAO interfaces.

Keep `<packaging>war</packaging>` and `SpringBootServletInitializer` in this stage — the JAR conversion is the next stage. Call out in your summary that the external container must now be Jakarta EE 11 (Tomcat 11+) for this intermediate artifact.

## Convert WAR → Executable JAR (Embedded Container)

Apply the **`springboot-war-to-boot4`** skill's vectors 5–6:
- **Views:** convert every JSP to Thymeleaf (`references/jsp-to-thymeleaf.md`), then remove JSTL, `tomcat-embed-jasper` and `InternalResourceViewResolver`. If the plan assigns the JSPs to a `jsp-to-react-bff` companion migration, leave them to it.
- **Packaging:** follow `references/war-to-executable-jar.md` — packaging `jar`, embedded Tomcat as a normal dependency, `SpringBootServletInitializer` removed (keep `main`), `web.xml` gone, container-provided resources (JNDI DataSource, context path, encoding, session, TLS, realms) → Spring Boot configuration, static assets → `src/main/resources/static`, `src/main/webapp` deleted.
- The result must be an executable **JAR** — never a WAR, and never an executable WAR kept alive for JSPs.

## Output

Fold your changes into the base `java-8-to-25-modify` Modify Result format. For every stage, add a **Deployment impact** line stating what the target runtime must now be (container version, or "runs standalone via `java -jar`"). List every library you removed, with its replacement.
