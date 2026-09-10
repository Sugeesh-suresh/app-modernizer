# Java 8 Baseline — Patterns to Look For

These are the language/library patterns typical of a Java 8-era codebase
that the migration plan will need to address on the way to Java 25 —
whether taken as one bigbang jump or as the 8 → 11 → 17 → 21 → 25
incremental hops.

## Language-level tells
- `var` not used at all (introduced in 10 — Java 8 has no local-variable type inference)
- Anonymous inner classes where a lambda/method reference would now do (Java 8 has lambdas, but pre-8-style code and some libraries still favour anonymous classes)
- No diamond operator on anonymous inner class instantiation (`new Comparator<String>() { ... }` instead of `new Comparator<>() { ... }` — diamond-for-anonymous-classes lands in 9)
- `try (Resource r = new Resource())` re-declaring an already-final local instead of `try (r)` (effectively-final try-with-resources lands in 9)
- Classic `switch` statements with fall-through instead of switch expressions (14)
- Manual `instanceof` + cast instead of pattern matching (16/21)
- Hand-written POJOs (getters/setters/equals/hashCode/toString) instead of records (16)
- No sealed type hierarchies — open class hierarchies with instanceof chains (17)
- String concatenation building multi-line text instead of text blocks (15)
- `Executors.newFixedThreadPool(...)` / `newCachedThreadPool(...)` for I/O-bound work instead of virtual threads (21)
- Manual null checks instead of `Optional` chains, or `Optional` used but missing `Optional.ofNullable`/`orElseThrow` idioms
- String utility reinventions (`s.trim().isEmpty()`, manual repeat loops) instead of `String.isBlank()`/`strip()`/`repeat()` (11)

## Library/runtime tells
- `javax.*` imports (Servlet, JPA/`javax.persistence`, Bean Validation, `javax.annotation`) — pre-Jakarta EE 9 namespace, relevant if the framework is bumped past Spring Boot 2.x / Jakarta EE 9
- Java EE modules bundled with 8 but removed in JDK 11: JAXB (`javax.xml.bind`), JAX-WS, JAF, CORBA, Java EE annotations (`javax.annotation.Resource` etc.) — these must become explicit dependencies (or be replaced) before the 11 hop
- `java.util.Date` / `Calendar` instead of `java.time.*` (java.time has existed since 8, but 8-era code frequently predates its adoption)
- Lombok used heavily for boilerplate that records could replace
- JUnit 4 (`org.junit.Test`) instead of JUnit 5 (`org.junit.jupiter.api.Test`) — flag as an upgrade candidate regardless of whether the user requested it; only actually plan the migration if `{junit_upgrade}` is true
- Spring Boot 1.x/2.x (`javax.*`) instead of Spring Boot 3.x (`jakarta.*`) — flag as an upgrade candidate; only actually plan the migration if `{springboot_upgrade}` is true
- Old Mockito/AssertJ versions incompatible with newer JDKs
- Nashorn JavaScript engine (`javax.script` with `"nashorn"`) — deprecated in 11, removed in 15; flag any usage explicitly

## Build tooling tells
- Maven `maven.compiler.source`/`target` set to `1.8` or `8` (or `<release>8</release>`)
- Gradle `sourceCompatibility`/`targetCompatibility` set to `1.8` or `JavaVersion.VERSION_1_8`
- CI pipeline pinned to a JDK 8 distribution

## Existing test suite — what to record for the Test Inventory
- Every test class found under `src/test/**` (or equivalent), its test framework (JUnit 4 vs 5, TestNG), and a one-line summary of what it exercises
- Any integration/e2e test setup (Testcontainers, embedded servers, `@SpringBootTest`) that the build_loop's `mvn compile` step will NOT itself re-run — call this out explicitly, since compiling is not the same as testing
- Test coverage gaps: source files with no obvious corresponding test class
