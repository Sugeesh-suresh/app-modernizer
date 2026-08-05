# Java 11 Baseline — Patterns to Look For

These are the language/library patterns typical of a Java 11-era codebase
that the migration plan will need to address on the way to Java 25.

## Language-level tells
- `var` used sparingly or not at all (introduced in 10, often under-adopted)
- Verbose anonymous inner classes instead of lambdas/method references
- Classic `switch` statements with fall-through instead of switch expressions
- Manual `instanceof` + cast instead of pattern matching
- Hand-written POJOs (getters/setters/equals/hashCode/toString) instead of records
- No sealed type hierarchies — open class hierarchies with instanceof chains
- String concatenation building multi-line text instead of text blocks
- `Executors.newFixedThreadPool(...)` / `newCachedThreadPool(...)` for I/O-bound work instead of virtual threads
- Manual null checks instead of `Optional` chains, or `Optional` used but not idiomatically

## Library/runtime tells
- `javax.*` imports (Servlet, JPA/`javax.persistence`, Bean Validation, `javax.annotation`) — pre-Jakarta EE 9 namespace, relevant if the framework is bumped past Spring Boot 2.x / Jakarta EE 9
- Java EE modules removed in JDK 11 that may still be referenced via extra dependencies: JAXB (`javax.xml.bind`), JAX-WS, CORBA, Java EE annotations
- `java.util.Date` / `Calendar` instead of `java.time.*`
- Lombok used heavily for boilerplate that records could replace
- JUnit 4 (`org.junit.Test`) instead of JUnit 5 (`org.junit.jupiter.api.Test`)
- Old Mockito/AssertJ versions incompatible with newer JDKs

## Build tooling tells
- Maven `maven.compiler.source`/`target` set to `11` (or `<release>11</release>`)
- Gradle `sourceCompatibility`/`targetCompatibility` set to `JavaVersion.VERSION_11`
- CI pipeline pinned to a JDK 11 distribution
