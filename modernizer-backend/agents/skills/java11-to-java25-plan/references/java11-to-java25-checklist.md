# Java 11 → Java 25 Migration Checklist

Java 11 to 25 is a 14-release jump — every feature introduced along the
way is in scope, not just the final Java 25 surface.

## Language Features Introduced Along the Way

| Feature | Introduced | Notes |
|---|---|---|
| `var` for local variables | 10 | Often under-used in Java 11 codebases — adopt where it improves readability |
| Switch expressions (`->` form, `yield`) | 14 (std) | Replace fall-through `switch` statements |
| Text blocks (`"""`) | 15 (std) | Replace concatenated multi-line strings, embedded SQL/JSON/HTML |
| Records | 16 (std) | Replace boilerplate DTOs/value objects (including Lombok `@Value` classes) |
| Pattern matching for `instanceof` | 16 (std) | Replace `instanceof` + explicit cast |
| Sealed classes/interfaces | 17 (std) | Use for closed type hierarchies (e.g. result/event types) |
| Pattern matching for `switch` | 21 (std) | Replace `instanceof` chains in `switch` form |
| Virtual threads (Project Loom) | 21 (std) | Replace platform-thread pools for blocking I/O workloads |
| Sequenced collections (`getFirst`/`getLast`/`reversed`) | 21 (std) | Replace `get(0)` / `get(size()-1)` idioms |
| Record patterns (nested deconstruction) | 21 (std) | Use in `switch`/`instanceof` over nested records |
| Unnamed variables/patterns (`_`) | 22 (std) | Use for intentionally-ignored catch/lambda parameters |
| Structured concurrency, scoped values | 21+ (preview) | Optional — only adopt if the codebase already leans on `ExecutorService` fan-out/fan-in patterns |

## Deprecated / Removed Since Java 11

| API | Status | Replacement |
|---|---|---|
| Java EE modules (`javax.xml.bind`/JAXB, JAX-WS, CORBA) | Removed in 11 | Add as explicit dependencies if still needed, or replace (e.g. Jackson XML for JAXB) |
| `Thread.stop()`, `Thread.suspend()`, `Thread.resume()` | Removed | Interruption + cooperative cancellation |
| `SecurityManager` | Removed | JVM security flags / OS-level isolation |
| `RMI Activation` | Removed | REST / gRPC |
| `java.util.Date` / `Calendar` | Long deprecated | `java.time.*` |
| `Object.finalize()` | Deprecated for removal | `Cleaner` API |
| `javax.*` Jakarta EE namespaces | Renamed at Jakarta EE 9 | `jakarta.*` — required if bumping past Spring Boot 2.x / Jakarta EE 9 |

## Third-Party Library Compatibility (target: Java 25)

| Library | Java 11-era version | Java 25-compatible version |
|---|---|---|
| Spring Boot | 2.5–2.7 (`javax.*`) | 3.3+ (`jakarta.*`) |
| Hibernate ORM | 5.x | 6.4+ |
| Jackson | 2.11–2.13 | 2.17+ |
| JUnit | 4.x | 5.10+ (JUnit Jupiter) |
| Mockito | 3.x | 5.x |
| Lombok | 1.18.x (older) | 1.18.34+ |
| MapStruct | 1.3–1.4 | 1.5.5+ |
| Flyway | 6.x/7.x | 10.x |
| Testcontainers | 1.15.x | 1.20+ |

## Build Tooling

- Maven: bump `<maven.compiler.source>`/`<maven.compiler.target>` (or `<release>`) to `25`; update `maven-compiler-plugin` to a version that supports it
- Gradle: `sourceCompatibility`/`targetCompatibility = JavaVersion.VERSION_25`; update the Gradle wrapper to a version with JDK 25 toolchain support
- CI: update the pinned JDK distribution in pipeline config
