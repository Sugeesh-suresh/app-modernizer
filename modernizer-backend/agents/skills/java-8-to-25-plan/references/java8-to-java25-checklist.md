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
| Records | 16 (std) | 8→17 | Replace boilerplate DTOs/value objects (including Lombok `@Value` classes) — never JPA entities |
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
| Spring / Spring Boot | Spring 3.1–5.x, Boot 1.5–2.7 (`javax.*`) | Newest Spring Boot 4.x (Spring 7, `jakarta.*`, executable JAR) if `{springboot_upgrade}` is true; otherwise Spring Framework 6.x, which still forces the Jakarta rename |
| Hibernate ORM | 3.x/4.x/5.x | 7.x via `spring-boot-starter-data-jpa` with Spring Boot 4 (6.4+ otherwise); staged through 5.6 on Java 17 |
| Jackson | 1.x (`org.codehaus.jackson`, **EOL**), 2.6–2.10 (**deprecated / CVE-laden**; `jackson-module-afterburner`, `enableDefaultTyping()`, unaligned module versions) | Java 17 stage: Jackson 1 → 2 (a rewrite, not a bump) and old 2.x → newest 2.x (2.17+) aligned via `jackson-bom`, Afterburner → Blackbird, `activateDefaultTyping(PolymorphicTypeValidator)`. Spring Boot 4 stage: Jackson 3 (`tools.jackson.*`, managed by Boot). 2.17+ is the end state if Spring Boot isn't upgraded |
| Connection pool | commons-dbcp / c3p0 (incl. Hibernate's `C3P0ConnectionProvider`) | HikariCP (Spring Boot's default) when Spring Boot is upgraded |
| JUnit | 3.x (`junit.framework.TestCase`), 4.8.x — **both deprecated** | 4.13.2 in readiness as a bridge only (JUnit 4 is maintenance-only, JUnit 6 deprecates the Vintage engine, Spring Framework 7 deprecates its JUnit 4 support). JUnit Jupiter (JUnit 6 under Spring Boot 4, 5.10+ otherwise) when `{junit_upgrade}` is true; otherwise listed as deprecated tech debt |
| Mockito | 1.x/2.x (`mockito-all`) | `mockito-core` 4.11.0 in readiness (last line supporting a Java 8 runtime), then 5.x on Java 17 |
| Bytecode / proxies | `cglib`, `cglib-nodep`, `javassist` | **Removed** — Spring 5+ repackages cglib, Hibernate 5.3+ uses ByteBuddy |
| AspectJ | 1.6–1.8 | Newest 1.9.x (1.9.20 is the Java 21 floor) |
| Cache | Ehcache 2.x (`net.sf.ehcache`, **EOL**), Spring `EhCacheCacheManager`, `hibernate-ehcache`, `ehcache-web` | Ehcache 3.x (`org.ehcache`) — different API, `getKeys()`/`getQuiet()` are gone; Spring `JCacheCacheManager` (Ehcache 2 support removed in Spring 6); `hibernate-jcache` (`hibernate-ehcache` removed in Hibernate 6); `ehcache-web` has no successor. `jakarta` classifier from the Spring Boot 3.x stage |
| Logging | log4j 1.2.x (`org.apache.log4j`) | SLF4J API + Logback (or Log4j 2); log4j 1.2 is EOL |
| Oracle JDBC | `ojdbc6` / `ojdbc14` | `com.oracle.database.jdbc:ojdbc11` (or `ojdbc17`) |
| Guava | `com.google.collections:google-collections` (**abandoned**), old `com.google.guava:guava` (below 32.0 is also a CVE finding) | The newest `com.google.guava:guava` `-jre` release (33.7.1-jre at the time of writing), pinned once through `guava-bom`; google-collections removed (same packages, so both together means duplicate classes). Removed APIs (`Objects.toStringHelper`, `new Stopwatch()`, `MapMaker.makeComputingMap`, `sameThreadExecutor`, executor-less `Futures.transform`) are rewritten. Spring Boot does not manage Guava |
| Servlet test doubles | `spring-mock` at runtime scope | Real `HttpServletRequestWrapper` / `ServletOutputStream` implementations |
| Lombok | 1.16.x/1.18.x (older) | 1.18.40+ (JDK 25 support) |
| MapStruct | 1.1–1.3 | 1.5.5+ |
| Flyway | 4.x/5.x | 10.x |

### Why these are different from an ordinary version bump

Spring 3.x/4.x, Hibernate 3/4, cglib and javassist all generate or parse bytecode
with a bundled ASM that **refuses class files newer than it knows**. They do not
produce a compiler error you can read — they throw at context startup
(`Unsupported class file major version`, `ArrayIndexOutOfBoundsException`) or, on
JDK 17+, `InaccessibleObjectException` from strong encapsulation. So they must be
resolved in the Java 8 → 17 stage, not deferred to a framework stage, and
`--add-opens` is never the fix. The `java-8-to-25-modify` skill's
`references/legacy-library-modernization.md` carries the per-library rewrites and
says which stage owns each one.

## Deprecated Libraries — always called out

Some libraries are deprecated whether or not this run migrates them. The plan
lists them in its **Deprecated Libraries** section, with the version found and
the files or test-class count, even when a toggle keeps them out of scope:

- **JUnit 3** (`junit.framework.TestCase`) and **JUnit 4** (`org.junit.Test`, `@RunWith`, `@Rule`), plus `junit-vintage-engine`. Only the migration is gated by `{junit_upgrade}` — the call-out is not.
- **Jackson 1** (`org.codehaus.jackson`), **Jackson 2 below 2.12**, `jackson-module-afterburner`, `enableDefaultTyping()`, and — on a Spring Boot 4 target — any Jackson 2 code left on Boot's deprecated Jackson 2 support.
- **Ehcache 2** (`net.sf.ehcache`) and its integrations: Spring `EhCacheCacheManager` / `EhCacheManagerFactoryBean`, `hibernate-ehcache` region factories, `ehcache-web` filters.
- **google-collections** (`com.google.collections:google-collections`, abandoned) and any Guava older than the newest release.

## JUnit 3/4 → JUnit Jupiter Migration (only when `{junit_upgrade}` is true)
- JUnit 3: drop `extends TestCase`; annotate `test*` methods with `@Test`; `setUp()`/`tearDown()` → `@BeforeEach`/`@AfterEach`
- `org.junit.Test` → `org.junit.jupiter.api.Test`; `@Before`/`@After` → `@BeforeEach`/`@AfterEach`; `@BeforeClass`/`@AfterClass` → `@BeforeAll`/`@AfterAll` (static)
- `@RunWith(SpringRunner.class)` → `@ExtendWith(SpringExtension.class)` (or just `@SpringBootTest`, which already includes it)
- `Assert.assertEquals(...)` → `Assertions.assertEquals(...)` (argument order for message changes from first to last)
- Parameterized tests: JUnit 4 `@RunWith(Parameterized.class)` → JUnit 5 `@ParameterizedTest` + `@MethodSource`/`@ValueSource`
- `@Test(expected = X.class)` and `ExpectedException` rules → `assertThrows`; `TemporaryFolder` → `@TempDir`; `@Ignore` → `@Disabled`; `@Category` → `@Tag`
- Add `junit-jupiter` (and `junit-vintage-engine` only as a temporary bridge for tests not yet migrated — it is itself deprecated in JUnit 6) to the dependency set, and remove `junit:junit` and the Vintage engine once the last JUnit 3/4 test is converted

## Spring Boot Upgrade (only when `{springboot_upgrade}` is true)

**One target for both strategies:** the newest Spring Boot 4.x (Spring Framework 7, Jakarta EE 11), deployed as an **executable JAR** on an embedded Tomcat — never a WAR. It is defined by the `springboot-war-to-boot4` skill:
- Spring Boot 4 parent/BOM and starters; every conflicting legacy library removed (explicit Spring versions, servlet API, JSTL, commons-dbcp/c3p0, Jackson 2 databind, old Hibernate / `javax` jars, extra logging bindings, `maven-war-plugin` / `jetty-maven-plugin`)
- Jakarta EE `javax.*` → `jakarta.*`
- `web.xml` and Spring XML contexts → Java config / `application.yml`; secrets as environment-variable placeholders
- Persistence → Spring Data JPA, with the existing DAO interfaces kept and vendor-specific SQL kept as native queries
- JSP → Thymeleaf (an executable JAR cannot serve JSPs)
- WAR → executable JAR; container-provided resources (JNDI DataSource, context path, encoding, session) → Spring Boot properties

**Bigbang:** all of the above in one pass.

**Incremental:** the same end state, staged and interleaved with the JDK stages so every step is on a supported combination: Java 17 → Spring Boot 2.7 (WAR, javax) → Spring Boot 3.x (WAR, jakarta) → Java 25 → Spring Boot 4.x with Spring Data JPA (WAR) → executable JAR with Thymeleaf views. Governed by the `springboot-incremental-upgrade` skill (plus `springboot-war-to-boot4` for the last two stages). Spring Boot 2.7 supports Java 8–21 and Spring Boot 3.x needs Java 17+, so both are done on Java 17, before the Java 25 jump.

Never rename Java SE `javax.*` packages (`javax.sql`, `javax.naming`, `javax.crypto`, JAXP `javax.xml.parsers`/`transform`, …) — they are part of the JDK and have no `jakarta.*` equivalent.

## Build Tooling
- Maven: bump `<maven.compiler.release>` to the current stage's target JDK (with `spring-boot-starter-parent`, set `<java.version>` instead); update `maven-compiler-plugin` to a version that supports it
- Gradle: `options.release` / toolchain `languageVersion` = the current stage's target JDK; update the Gradle wrapper to a version with the target JDK's toolchain support (9.1+ for Java 25)
- CI: update the pinned JDK distribution in pipeline config
