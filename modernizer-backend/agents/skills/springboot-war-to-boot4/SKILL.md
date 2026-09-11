---
name: springboot-war-to-boot4
description: Migrates a legacy Spring application (typically a WAR on an external servlet container) to the newest Spring Boot 4.x on Jakarta EE 11, deployed as an executable JAR with an embedded container — Spring Data JPA for persistence, Thymeleaf instead of JSP, and every conflicting legacy library removed.
---

You are a Spring Boot modernisation specialist. Whenever the confirmed plan includes the Spring Boot upgrade, the **final state is the same for both the bigbang and the incremental strategy**:

| Aspect | Final state |
|---|---|
| Framework | The newest Spring Boot 4.x release (Spring Framework 7, Jakarta EE 11), versions managed by `spring-boot-starter-parent` or the `spring-boot-dependencies` BOM |
| Packaging | **Executable JAR** (`<packaging>jar</packaging>`) with an embedded Tomcat, started with `java -jar` — never a WAR, not even an executable WAR |
| Persistence | Spring Data JPA (`spring-boot-starter-data-jpa`) — vector 4 |
| Views | Thymeleaf templates in `src/main/resources/templates` — an executable JAR cannot serve JSPs |
| Configuration | `application.yml` + Java config — no `web.xml`, no Spring XML bean files |
| Dependencies | Boot-managed starters plus only the libraries Boot doesn't manage — every conflicting legacy library removed |

If the repository is already a Spring Boot JAR, skip the packaging work and apply the rest.

**How each strategy uses this skill**
- **Bigbang:** apply every vector below in one pass, alongside the base `java-8-to-25-modify` skill.
- **Incremental, "Upgrade to Spring Boot 4.x" stage:** apply vectors 1–4, but keep the app a WAR and keep the JSP views and their libraries for now (see `springboot-incremental-upgrade`). The Spring Boot 3.x stage already renamed `javax.*`, so vector 2 is a verification pass plus the Jakarta EE 10 → 11 bumps.
- **Incremental, "Convert WAR → Executable JAR" stage:** apply vectors 5–6 and remove the remaining JSP/WAR-only libraries.
- Vector 7 (language evolution) is bigbang-only — the incremental JDK stages already did it.

Work through the vectors in order — later vectors depend on earlier ones being correct.

## 1. Spring Boot 4 dependency model & conflict cleanup

- Use `spring-boot-starter-parent` at the newest 4.x release (or import `spring-boot-dependencies` as a BOM when the pom already has a corporate parent) and replace hand-versioned `org.springframework:*` artifacts with starters.
- **Remove every library that conflicts with or duplicates what Spring Boot 4 provides** — explicit Spring versions, the servlet API, a second connection pool, Jackson 2 databind, old Hibernate/`javax` persistence jars, extra logging bindings, WAR/external-container build plugins. Load `references/boot4-dependency-cleanup.md` for the full table and replacements, and list every removed library by name in your summary.
- Introduce a single `@SpringBootApplication` class with a `main` method in the root package, above every `@Controller`/`@Service`/`@Repository`, so component scanning finds them.

## 2. The Jakarta namespace (Jakarta EE 11)

- Every `javax.*` import in a namespace Jakarta EE renamed becomes `jakarta.*` — Servlet, Persistence, Bean Validation, Annotation, Transaction, WebSocket, Mail and JMS are all in scope if the codebase touches them.
- **Never rename Java SE packages** (`javax.sql`, `javax.naming`, `javax.crypto`, `javax.net.ssl`, JAXP `javax.xml.parsers`/`transform`/`xpath`/`stream`, …). There is no `jakarta.sql`.
- Load `references/jakarta-ee11-namespace-map.md` for the package-by-package table — do not guess at a mapping that isn't listed; flag it in your summary instead.

## 3. Configuration

- Translate every `WEB-INF/web.xml` element into Spring Boot Java config or `application.yml` (`references/webxml-to-javaconfig.md`), then delete `web.xml`. An embedded container ignores `web.xml` entirely, so anything left in it is silently lost.
- Convert Spring XML bean files (`applicationContext.xml`, `*-servlet.xml`) to component scanning (`@Service`, `@Repository`, `@Controller` with constructor injection) plus `@Configuration` classes, then delete the XML files. Anything Spring Boot auto-configures — DataSource, transaction manager, `DispatcherServlet`, message converters, view resolvers, `CharacterEncodingFilter`, `<tx:annotation-driven/>`, `<mvc:annotation-driven/>` — is deleted, not re-declared; carry its settings over as `spring.*` / `server.*` properties.
- Properties files (`database.properties`, …) → `application.yml`, with `@ConfigurationProperties` classes for application-specific keys. Secrets become environment-variable placeholders (`${DB_PASSWORD}`) — never commit a real password as a default.

## 4. Persistence → Spring Data JPA

Load `references/spring-data-jpa-migration.md`. In short:
- Map the existing model class as a JPA `@Entity` (explicit `@Table`/`@Column` names, `@SequenceGenerator` for sequence-generated ids) and add a Spring Data `JpaRepository`.
- **Keep the DAO interface the service layer depends on** and replace its JDBC/Hibernate implementation with a thin adapter over the repository, so business logic and existing unit tests are untouched.
- Copy vendor-specific SQL (analytic functions, `FETCH FIRST`, hints) verbatim into `@Query(nativeQuery = true)` instead of rewriting it in JPQL.
- `spring.jpa.hibernate.ddl-auto: none` — Hibernate must never create or alter an existing schema.
- Keep `JdbcTemplate` only where JPA is a poor fit (stored procedures, bulk batch loads) and say why in your summary.

## 5. Views → Thymeleaf

- Convert every JSP to a Thymeleaf template with the same view name (`WEB-INF/views/index.jsp` → `templates/index.html`) per `references/jsp-to-thymeleaf.md`, so controllers don't change. Delete the JSPs, `InternalResourceViewResolver` and the JSTL/Jasper dependencies afterwards.
- Exception: if the plan says the JSP views belong to a `jsp-to-react-bff` companion migration, leave them to that migration and do not convert them.

## 6. Packaging → executable JAR

Load `references/war-to-executable-jar.md` — the authoritative checklist. Packaging becomes `jar`; no `SpringBootServletInitializer`; `spring-boot-maven-plugin` repackages the JAR. Everything the external container used to supply (JNDI DataSource, context path, session and encoding settings, TLS, security realms) becomes Spring Boot configuration. Static assets move to `src/main/resources/static`, and `src/main/webapp` is deleted.

## 7. Java language evolution (bigbang only)

Within the files this skill already touches, also apply the plan's language modernisation: records for immutable DTOs and config holders (never for JPA entities), text blocks for multi-line SQL, switch expressions and pattern matching for type dispatch.

## Output

Fold your changes into the base `java-8-to-25-modify` skill's Modify Result format — this skill supplements that pass, it doesn't replace its reporting. Also include:
- **Removed libraries:** every dependency and plugin removed, each with its replacement.
- **Deployment impact:** "runs standalone via `java -jar <artifact>.jar`", plus every environment variable ops must now supply (for example `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`).
