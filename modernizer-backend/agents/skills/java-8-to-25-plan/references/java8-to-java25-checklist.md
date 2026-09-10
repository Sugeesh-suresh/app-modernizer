# Java 8 → Java 25 Migration Checklist

Java 8 to 25 is a 17-release jump — every feature introduced along the way
is in scope, not just the final Java 25 surface. The incremental strategy's
two JDK stages (8→17, 17→25) line up with the JDK's own LTS boundaries; the
"Hop" column below says which JDK stage each item belongs to.

## Language Features Introduced Along the Way

| Feature | Introduced | Hop | Notes |
|---|---|---|---|
| Diamond operator on anonymous classes | 9 | 8→17 | `new Comparator<>() { ... }` |
| Effectively-final try-with-resources | 9 | 8→17 | `try (resource)` instead of re-declaring |
| `var` for local variables | 10 | 8→17 | Adopt where it improves readability |
| `String.isBlank()/strip()/repeat()/lines()` | 11 | 8→17 | Replace manual equivalents |
| `Files.readString()`/`writeString()` | 11 | 8→17 | Replace `Files.readAllBytes` + `new String(...)` |
| Switch expressions (`->` form, `yield`) | 14 (std) | 8→17 | Replace fall-through `switch` statements |
| Text blocks (`"""`) | 15 (std) | 8→17 | Replace concatenated multi-line strings, embedded SQL/JSON/HTML |
| Records | 16 (std) | 8→17 | Replace boilerplate DTOs/value objects (including Lombok `@Value` classes) |
| Pattern matching for `instanceof` | 16 (std) | 8→17 | Replace `instanceof` + explicit cast |
| Sealed classes/interfaces | 17 (std) | 8→17 | Use for closed type hierarchies (e.g. result/event types) |
| Pattern matching for `switch` | 21 (std) | 17→25 | Replace `instanceof` chains in `switch` form |
| Virtual threads (Project Loom) | 21 (std) | 17→25 | Replace platform-thread pools for blocking I/O workloads |
| Sequenced collections (`getFirst`/`getLast`/`reversed`) | 21 (std) | 17→25 | Replace `get(0)` / `get(size()-1)` idioms |
| Record patterns (nested deconstruction) | 21 (std) | 17→25 | Use in `switch`/`instanceof` over nested records |
| Unnamed variables/patterns (`_`) | 22 (std) | 17→25 | Use for intentionally-ignored catch/lambda parameters |
| Structured concurrency, scoped values | 21+ (preview) | 17→25 | Optional — only adopt if the codebase already leans on `ExecutorService` fan-out/fan-in patterns |

## Deprecated / Removed Since Java 8

| API | Status | Hop | Replacement |
|---|---|---|---|
| Java EE modules (`javax.xml.bind`/JAXB, JAX-WS, JAF, CORBA) | Removed in 11 | 8→17 | Add as explicit dependencies if still needed, or replace (e.g. Jackson XML for JAXB). In the incremental strategy, keep the `javax` artifacts here — the jakarta rename is the Spring Boot 3.x stage |
| Nashorn JS engine (`javax.script("nashorn")`) | Deprecated 11, removed 15 | 8→17 | GraalVM JS, or remove if unused |
| Strong encapsulation of JDK internals (`--illegal-access` removed) | 16/17 | 8→17 | Stop using `sun.*` internals; `--add-opens` only as a documented stop-gap |
| `Thread.stop()`, `Thread.suspend()`, `Thread.resume()` | Removed | any | Interruption + cooperative cancellation |
| `SecurityManager` | Deprecated 17, removed 24 | 17→25 | JVM security flags / OS-level isolation |
| `RMI Activation` | Removed 17 | 8→17 | REST / gRPC |
| `java.util.Date` / `Calendar` | Long deprecated | any | `java.time.*` |
| `Object.finalize()` | Deprecated for removal | any | `Cleaner` API |
| `javax.*` Jakarta EE namespaces | Renamed at Jakarta EE 9 | gated by `{springboot_upgrade}` | `jakarta.*` |

## Third-Party Library Compatibility (target: Java 25)

| Library | Java 8-era version | Java 25-compatible version |
|---|---|---|
| Spring Boot | 1.5–2.7 (`javax.*`) | 3.3+ (`jakarta.*`) — only in scope if `{springboot_upgrade}` is true |
| Hibernate ORM | 4.x/5.x | 6.4+ |
| Jackson | 2.6–2.10 | 2.17+ |
| JUnit | 4.x | 5.10+ (JUnit Jupiter) — only in scope if `{junit_upgrade}` is true |
| Mockito | 1.x/2.x | 5.x |
| Lombok | 1.16.x/1.18.x (older) | 1.18.40+ (JDK 25 support) |
| MapStruct | 1.1–1.3 | 1.5.5+ |
| Flyway | 4.x/5.x | 10.x |

## JUnit 4 → 5 Migration (only when `{junit_upgrade}` is true)
- `org.junit.Test` → `org.junit.jupiter.api.Test`; `@Before`/`@After` → `@BeforeEach`/`@AfterEach`; `@BeforeClass`/`@AfterClass` → `@BeforeAll`/`@AfterAll` (static)
- `@RunWith(SpringRunner.class)` → `@ExtendWith(SpringExtension.class)` (or just `@SpringBootTest`, which already includes it)
- `Assert.assertEquals(...)` → `Assertions.assertEquals(...)` (argument order for message changes from first to last)
- Parameterized tests: JUnit 4 `@RunWith(Parameterized.class)` → JUnit 5 `@ParameterizedTest` + `@MethodSource`/`@ValueSource`
- Add `junit-jupiter` (and `junit-vintage-engine` only as a temporary bridge for tests not yet migrated) to the dependency set

## Spring Boot Version Bump (only when `{springboot_upgrade}` is true)

**Incremental strategy:** ignore Path A / Path B below. The framework upgrade is always staged and interleaved with the JDK stages, so every step is on a supported combination: Java 17 → Spring Boot 2.7 (WAR, javax) → Spring Boot 3.x (WAR, jakarta) → Java 25 → Spring Boot 4.x (WAR) → executable JAR. It is governed by the `springboot-incremental-upgrade` skill (and `springboot-war-to-boot4` for the Spring Boot 4 stage). Spring Boot 2.7 supports Java 8–21 and Spring Boot 3.x needs Java 17+, so both are done on Java 17, before the Java 25 jump.

**Bigbang strategy:** first check the scanner's "Packaging & Deployment Model" repo fact to pick ONE of the two paths below — do not mix them:

**Path A — standalone embedded-server JAR** (the repo's `<packaging>` is already `jar`, or is `war` but with no real deployment dependency on an external container):
- Target the newest Spring Boot 3.x compatible with the target Java level (3.3+ for Java 21/25)
- Every `javax.*` import in the Jakarta-covered namespaces (`servlet`, `persistence`, `validation`, `annotation`, `transaction`) → `jakarta.*`
- `WebSecurityConfigurerAdapter` (removed) → `SecurityFilterChain` bean-based configuration
- `spring.factories`-based auto-configuration → `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports` if the project defines custom auto-configuration
- Actuator endpoint security defaults changed — review `management.endpoints.web.exposure.include`

**Path B — WAR deployed to an external servlet container** (the repo's `<packaging>` is `war` AND it has a real `WEB-INF/web.xml` and/or is clearly deployed to a shared/managed container rather than run standalone):
- Target **Spring Boot 4** on **Jakarta EE 11**, keeping WAR packaging — this is a different target than Path A, not a further bump of it
- Do NOT convert the app to a standalone JAR — that breaks the external container's deployment model
- Delegate this entire path to the dedicated `springboot-war-to-boot4` skill (loaded automatically by modifier_agent alongside this one): it covers WAR/`SpringBootServletInitializer` packaging rules, the full Jakarta EE 11 namespace surface (broader than just servlet/persistence/validation/annotation/transaction), and `web.xml` → Java-config translation
- The plan's manifest for this section should still list every affected file (same as any other section) — just note against each one that `springboot-war-to-boot4` governs the specifics of *how* it changes

In either path, never rename Java SE `javax.*` packages (`javax.sql`, `javax.naming`, `javax.crypto`, JAXP `javax.xml.parsers`/`transform`, …) — they are part of the JDK and have no `jakarta.*` equivalent.

## Build Tooling
- Maven: bump `<maven.compiler.release>` to the current stage's target JDK; update `maven-compiler-plugin` to a version that supports it
- Gradle: `options.release` / toolchain `languageVersion` = the current stage's target JDK; update the Gradle wrapper to a version with the target JDK's toolchain support (9.1+ for Java 25)
- CI: update the pinned JDK distribution in pipeline config
