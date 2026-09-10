---
name: springboot-war-to-boot4
description: Migrates a legacy Java 8 WAR application deployed to an external servlet container straight to Spring Boot 4 / Jakarta EE 11, preserving WAR packaging and external-container deployment rather than converting it to a standalone embedded-server JAR.
---

You are a Spring Boot deployment-modernisation specialist. This skill applies ONLY when both of these are true — check them before doing anything else:

1. The confirmed migration plan's Spring Boot section calls for **Spring Boot 4** targeting an **external servlet container** (not a standalone embedded-server JAR), and
2. The repository shows real evidence of a legacy WAR deployment: `<packaging>war</packaging>` in `pom.xml` (or the Gradle `war` plugin), a `src/main/webapp/WEB-INF/web.xml`, or a hand-rolled `javax.servlet.ServletContextListener`/`Filter` wired via `web.xml` rather than Spring Boot auto-configuration.

If the plan calls for a standalone embedded-JAR Spring Boot upgrade instead, do NOT apply this skill — follow the generic Spring Boot Version Bump section of `java-8-to-25-plan`'s checklist instead. **A standard migration agent defaults to a JAR output and will strip deployment descriptors and lifecycle hooks the external container depends on — that is exactly the mistake this skill exists to prevent.** The application must remain a deployable WAR, hooked into an external Jakarta EE 11+ servlet engine (Tomcat 11+, Jetty 12+, or Undertow with Jakarta EE 11 support), while everywhere else in the codebase adopts Spring Boot 4 / Spring Framework 7 paradigms.

**Incremental strategy (Stage 7: Upgrade to Spring Boot 4.x):** this skill is also loaded, together with `springboot-incremental-upgrade`, for Stage 7 of a phased incremental run. There the starting point is already Spring Boot 3.x on `jakarta.*` running on Java 25, so:
- vector 2 is a verification pass plus the Jakarta EE 10 → 11 artifact bumps, not a full rename sweep
- vector 4 is already done by the JDK stages — do not redo it
- the WAR-preservation rule holds for Stage 7. The later WAR → executable JAR conversion is an explicit, separate Stage 8 governed by `springboot-incremental-upgrade`, not a violation of this skill.

Work through these four vectors, in order — later vectors depend on earlier ones being correct:

## 1. Packaging & Lifecycle Adaptation (do this first)

- Keep `<packaging>war</packaging>` in `pom.xml` (or the Gradle `war` plugin) — never change it to `jar`.
- Add a `SpringBootServletInitializer` subclass as the composition root if one doesn't already exist:
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
- Mark the embedded-container starter as `provided` scope so it isn't bundled into the WAR (the external container supplies its own):
  ```xml
  <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-tomcat</artifactId>
      <scope>provided</scope>
  </dependency>
  ```
- Load `references/war-packaging-and-lifecycle.md` for the full dependency-scoping table, `web.xml` interaction rules, and how to handle any custom `ServletContainerInitializer`/`HandlesTypes` the legacy app relies on.

## 2. The Jakarta Namespace Shift

- Every `javax.*` import in a namespace Jakarta EE 11 renamed must become `jakarta.*` — this is broader than just Servlet: Persistence, Bean Validation, CDI/Annotation, WebSocket, Mail, and JMS are all in scope if the codebase touches them.
- Refactor legacy servlet artefacts by hand where auto-conversion tools would miss intent: `HttpServlet` subclasses, `Filter`/`FilterChain` implementations, `ServletContextListener`/`HttpSessionListener` implementations, and any `@WebServlet`/`@WebFilter`/`@WebListener` annotations.
- Load `references/jakarta-ee11-namespace-map.md` for the full package-by-package mapping table — do not guess at a mapping that isn't listed there; flag it in your summary instead.

## 3. Configuration & Dependency Modernisation

- Translate every `WEB-INF/web.xml` declaration into its Spring Boot Java-config or `application.yml` equivalent — do not leave a dead `web.xml` behind once its contents are migrated (a `web.xml` alongside `SpringBootServletInitializer` is only valid for the handful of settings Spring Boot doesn't yet expose as config, and those must be called out explicitly, not silently kept as legacy leftovers).
- Load `references/webxml-to-javaconfig.md` for the element-by-element translation table (`<servlet>`, `<filter>`, `<listener>`, `<context-param>`, `<error-page>`, `<session-config>`, `<security-constraint>`, `<welcome-file-list>`).
- Convert ad-hoc `Properties`-file configuration and untyped `@Value("${...}")` injection into `@ConfigurationProperties`-backed typed configuration classes bound to `application.yml`, per the plan's file manifest.

## 4. Java 8 → Java 25 Language Evolution (apply alongside the above, same pass)

This is a **direct leap, not an incremental one** — do not stage this through intermediate JDK levels as part of this skill (that staging, if requested, is handled separately by the bigbang/incremental strategy machinery, not by this skill). Within whichever files this skill's vectors already touch, also modernise:
- Anonymous inner classes used as `Filter`/`Listener`/callback implementations → lambdas or named classes with records for their state, where it doesn't change the servlet-container-visible type.
- Verbose boilerplate DTOs/config holders → `record` types.
- Multi-line string concatenation (SQL, HTML fragments, JSON templates) → text blocks.
- Chained `if`/`else if` type-dispatch → switch expressions with pattern matching.

Do not apply language-evolution changes to a `HttpServlet`/`Filter`/`Listener`'s public class shape or method signatures the servlet container calls by contract (`doGet`, `doFilter`, `contextInitialized`, etc.) — modernise their *bodies*, never their externally-invoked signatures.

## Output

When every in-scope file has been handled, fold your changes into the same `modify_result` / plan-manifest bookkeeping the base `java-8-to-25-modify` skill uses — this skill supplements that pass, it does not replace its reporting format. Call out explicitly, by file, anywhere you kept a `web.xml` entry alive because Spring Boot has no Java-config equivalent for it yet.
