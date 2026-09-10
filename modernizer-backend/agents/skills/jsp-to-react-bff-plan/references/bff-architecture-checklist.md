# BFF Architecture & WAR → JAR Packaging Checklist

## What a Backend-For-Frontend is (and isn't) here

The BFF is a Spring Boot service whose API surface is shaped specifically for this React frontend's needs — not a generic public API. It's the natural home for everything the classification table marked Backend: the business logic that used to live in servlets/scriptlets, session/auth handling, and any request/response shaping the frontend needs (e.g. combining two legacy servlet calls into one BFF endpoint if the frontend page needs both pieces of data at once).

- One BFF, one React app: do not over-decompose this into multiple microservices unless the BRD explicitly calls for it — that's a separate, larger architectural decision than "get off JSP."
- The BFF may call further downstream systems (a database, other internal services) — those calls belong in the service layer classified-Backend logic maps to, not in the controller.

## Packaging: WAR → JAR (mandatory for this pipeline)

This is a **greenfield backend**, not a preserved deployment — unlike the `springboot-war-to-boot4` skill (which exists for the opposite case: keeping WAR packaging for an app that must stay on an external container), this pipeline's BFF is a **standard standalone executable JAR**:

| Item | Rule |
|---|---|
| `<packaging>` | `jar` |
| Embedded server starter | Normal (compile-scope) dependency — `spring-boot-starter-web` already pulls in embedded Tomcat. No `provided` scoping. |
| Composition root | Plain `@SpringBootApplication` class with a `main()` calling `SpringApplication.run(...)`. Do NOT extend `SpringBootServletInitializer` — that's only needed for WAR deployment to an external container, which this pipeline is explicitly moving away from. |
| `web.xml` | Does not exist in the generated backend at all — there is nothing to translate into it; every legacy `web.xml` concern either became a Spring Boot config property, a `@Bean`, or simply doesn't apply to a REST API (no `<welcome-file-list>`, no JSP-serving `<servlet-mapping>`). |
| Build plugin | `spring-boot-maven-plugin` with the `repackage` goal, producing a single executable JAR (`java -jar app.jar`). |

## API contract design rules

- Every endpoint should return exactly what its React page needs — avoid forcing the frontend to make multiple round-trips for data that's naturally used together, and avoid over-fetching (returning fields no page uses).
- Use DTOs/records for every request and response body — never expose JPA entities or internal domain objects directly across the API boundary.
- HTTP status codes carry meaning: `200`/`201` for success, `400` for validation failures (with a structured error body the frontend can render field-by-field), `401`/`403` for auth failures, `404` for missing resources. A legacy JSP app's "forward to an error page" pattern becomes a proper status code plus a JSON error body, not a redirect.
- Session/auth: if the reconciliation plan calls for a server-side session, use Spring Session with a cookie (the browser still handles this transparently, no frontend token management needed) — this is usually the lowest-risk translation of legacy `HttpSession` semantics. Only introduce JWT/token-based auth if the BRD specifically requires statelessness (e.g. for horizontal scaling without sticky sessions) — it's a bigger behavioural change than a straight session-cookie port.

## Java level

Target Java 25 in the generated `pom.xml` (`<java.version>25</java.version>` or `<maven.compiler.release>25</maven.compiler.release>`) — this is a greenfield generation, not a staged upgrade, so there is no intermediate-JDK concern the way there is in the `java-8-to-25` pattern's incremental strategy. Use modern Java idioms throughout the generated code (records for DTOs, pattern matching, virtual threads for I/O-bound service methods where it fits) rather than writing Java-8-style boilerplate and hoping a later pass modernises it.
