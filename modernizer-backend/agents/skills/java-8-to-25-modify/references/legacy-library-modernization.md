# Legacy Library Modernization (Java 8-era stacks)

A Java 8 repository rarely fails to reach Java 25 because of the *language* —
it fails because of the libraries around it. The stacks below **cannot run on
Java 17 at all**: they generate or parse bytecode and refuse class-file
versions they predate, so they throw at runtime (or during annotation
processing) rather than producing a compiler error you can read.

Each entry says **which stage owns it**. Do the work in that stage and no
earlier — but never leave one of these behind in a stage that has already
moved past the JDK it dies on.

Stage names below are the incremental stage titles. In a bigbang run every
entry applies in the single pass.

## Ownership at a glance

| Legacy artifact | Target | Owning stage |
|---|---|---|
| `junit:junit` 4.x < 4.13.2 | `junit:junit` 4.13.2 (a bridge, not a destination) | Readiness — Modernize Build Systems |
| JUnit 3 (`junit.framework.TestCase`) and JUnit 4 (`org.junit.Test`, `@RunWith`, `@Rule`) — **deprecated** | JUnit Jupiter (`org.junit.jupiter.api`) | Called out in every stage that sees them; migrated in Java 8 → Java 17 LTS only when the JUnit upgrade was requested, otherwise carried as recorded tech debt |
| `org.junit.vintage:junit-vintage-engine` — **deprecated** in JUnit 6 | Removed once no JUnit 3/4 test remains | Whichever stage finishes the JUnit migration |
| `org.mockito:mockito-all` / `mockito-core` 1.x | `mockito-core` 4.11.0, then 5.x | Readiness (4.11.0) → Java 8 → 17 (5.x) |
| `maven-surefire-plugin` / `maven-failsafe-plugin` 2.x | 3.2.5+ | Readiness — Modernize Build Systems |
| `maven-svn-revision-number-plugin`, SVN `<scm>` URL | Removed | Readiness — Modernize Build Systems |
| `cargo-maven2-plugin` (embedded Jetty 6), `tomcat7-maven-plugin` | `jetty-maven-plugin` (current), or nothing | Readiness — Modernize Build Systems |
| `org.springframework:spring-*` 3.x/4.x | Spring Framework 5.3.x (still `javax`) | Java 8 → Java 17 LTS |
| `org.hibernate:hibernate-core` 3.x/4.x | Hibernate ORM 5.6.x | Java 8 → Java 17 LTS |
| `org.codehaus.jackson:*` (Jackson 1) — **EOL** | `com.fasterxml.jackson.*` 2.x | Java 8 → Java 17 LTS |
| Jackson 2.x below 2.12, mismatched Jackson module versions, `jackson-module-afterburner`, `ObjectMapper.enableDefaultTyping()` — **deprecated / insecure** | Newest 2.x aligned through `jackson-bom`, `jackson-module-blackbird`, `activateDefaultTyping(PolymorphicTypeValidator)` | Java 8 → Java 17 LTS |
| `com.fasterxml.jackson.module:jackson-module-jaxb-annotations` | `jackson-module-jakarta-xmlbind-annotations` | Spring Boot 3.x stage (or Java 17 → 25 if no Boot upgrade) |
| Jackson 2 (`com.fasterxml.jackson.databind` / `.core`) | Jackson 3 (`tools.jackson.*`) | Spring Boot 4.x stage (only with the Spring Boot upgrade) |
| `cglib:cglib`, `cglib:cglib-nodep`, `javassist:javassist` | Removed (no replacement) | Java 8 → Java 17 LTS |
| `org.aspectj:aspectjweaver` / `aspectjrt` < 1.9.20 | Newest 1.9.x | Java 8 → Java 17 LTS |
| `net.sf.ehcache:ehcache` / `ehcache-core` 2.x — **EOL** | `org.ehcache:ehcache` 3.x | Java 8 → Java 17 LTS |
| `org.springframework.cache.ehcache.*` (`EhCacheCacheManager`, `EhCacheManagerFactoryBean`) | `JCacheCacheManager` over Ehcache 3 (JSR-107) | Java 8 → Java 17 LTS (removed in Spring 6, so never later than the Spring Boot 3.x stage) |
| `org.hibernate:hibernate-ehcache` (`EhCacheRegionFactory`) | `hibernate-jcache` + Ehcache 3 | Java 8 → Java 17 LTS (deprecated in Hibernate 5.6, removed in 6) |
| `net.sf.ehcache:ehcache-web` (`SimplePageCachingFilter`) | No Ehcache 3 successor — HTTP caching headers or `@Cacheable` services | Java 8 → Java 17 LTS; flag as a decision |
| `log4j:log4j` 1.2.x | SLF4J API + Logback (or Log4j 2) | Java 8 → Java 17 LTS |
| `com.oracle:ojdbc6` / `ojdbc14` | `com.oracle.database.jdbc:ojdbc11` (or `ojdbc17`) | Java 8 → Java 17 LTS |
| `com.google.collections:google-collections` — **abandoned**, and any `com.google.guava:guava` older than the newest release | `com.google.guava:guava` at the newest `-jre` release (33.7.1-jre at the time of writing) | Java 8 → Java 17 LTS |
| `org.springframework:spring-mock` at runtime scope | Real Servlet API wrapper classes | Java 8 → Java 17 LTS |
| `javax.xml.bind:jaxb-api` reliance (removed from the JDK in 11) | Explicit JAXB dependency | Java 8 → Java 17 LTS |
| `com.mchange:c3p0`, `commons-dbcp` | HikariCP | Spring Boot stage (or Java 17 stage if no Boot upgrade) |

---

## Readiness — the test stack is the safety net, so it goes first

The regression suite is what proves the later stages did not change behaviour.
Modernise it **before** touching production code, and keep the compiler release
at 8 while doing it. This is the one place the readiness stage is allowed to
change dependency version *values*, and it is limited to test-scoped artifacts
and the test plugins.

| Artifact | From | To | Why here |
|---|---|---|---|
| `junit:junit` | 4.8.1 | **4.13.2** | 4.8.1 predates `@Rule`/`ExpectedException` behaviour later versions fix, and is what surefire 3.x expects from a vintage suite |
| `org.mockito:mockito-core` (replacing `mockito-all`) | 1.8.5 | **4.11.0** | Mockito 1.x generates mocks with cglib and **fails outright on JDK 9+**. 4.11.0 is the last line that still runs on a Java 8 runtime, so it is safe while the release level is still 8. The move to **5.x** belongs to the Java 8 → 17 stage, where the runtime floor becomes Java 11+ |
| `maven-surefire-plugin`, `maven-failsafe-plugin` | 2.x | **3.2.5+** | Surefire/Failsafe 2.x fork a JVM using internal APIs and module-path assumptions that JDK 9+ rejects — the test run dies before a single test executes |

- `mockito-all` is a shaded fat jar that was discontinued after 1.x. Replace it with `mockito-core`, adding `mockito-junit-jupiter` only when the JUnit 5 migration was requested.
- Mockito 2+ dropped cglib for ByteBuddy, so `org.mockito.Mockito.mock` on a final class now needs the inline mock maker. If tests mock final classes or static methods, add `mockito-inline` (4.x) — in 5.x the inline maker is the default and the artifact is unnecessary.
- Removing `cglib` from the test path is part of the Java 17 stage, not this one; here you only stop *Mockito* from pulling it in.

### JUnit 3 and JUnit 4 are deprecated — call them out every time

JUnit 4 has been maintenance-only since 4.13.2 and gets no further feature
releases; JUnit 3 (`junit.framework.TestCase`, `extends TestCase`, `test*`-named
methods) is older still. The rest of the stack has moved on:

- **JUnit 6** — the line Spring Boot 4 ships — deprecates `junit-vintage-engine`, the only way the JUnit Platform runs JUnit 3/4 tests at all.
- **Spring Framework 7** deprecates its JUnit 4 support: `SpringRunner`, `SpringJUnit4ClassRunner`, `SpringClassRule` / `SpringMethodRule`, `AbstractJUnit4SpringContextTests`, `AbstractTransactionalJUnit4SpringContextTests`.
- Inside 4.13 itself, `org.junit.Assert.assertThat` and `ExpectedException.none()` are deprecated (→ AssertJ / Hamcrest `assertThat`, `assertThrows`).

So:

- The 4.13.2 bump above keeps the suite running on newer JDKs. It is a bridge, and the summary must say so.
- **Every** stage that touches a JUnit 3/4 test class or the test dependencies lists them as *deprecated* in its summary, with a count of JUnit 3 and JUnit 4 test classes — whether or not the JUnit upgrade was requested.
- **When the JUnit upgrade was requested** (Java 8 → 17 stage): migrate to JUnit Jupiter per the plan checklist. JUnit 3 classes lose `extends TestCase`, their `test*` methods get `@Test`, `setUp()`/`tearDown()` become `@BeforeEach`/`@AfterEach`, and asserts come from `org.junit.jupiter.api.Assertions` (message argument last). Remove `junit:junit` and `junit-vintage-engine` once the last test is converted — leaving the Vintage engine behind is leaving a deprecated dependency behind.
- **When it was not requested:** do not rewrite test code. Keep `junit:junit` 4.13.2 (plus `junit-vintage-engine` wherever the JUnit Platform runs the suite) and record the remaining JUnit 3/4 classes as deprecated tech debt. If you must add a test, write it in JUnit Jupiter when `junit-jupiter` is already on the test classpath (it is with `spring-boot-starter-test`); otherwise follow the existing style and flag it.

### Dead build cruft to delete in the same stage

- `maven-svn-revision-number-plugin` and any `<scm>` pointing at an SVN URL: the repository is on Git, so the plugin either no-ops or fails against the checkout. If the pom already has `maven-gitlog-plugin` or `git-commit-id-maven-plugin`, the SVN plugin is redundant; delete both it and the stale `<scm>` block (or correct `<scm>` to the Git remote).
- `cargo-maven2-plugin`: it embeds Jetty 6, which will not start on a modern JDK. Replace it with the current `jetty-maven-plugin` for local runs, or drop it entirely if the plan's Spring Boot stages will introduce `spring-boot:run`.
- Any plugin without a `<version>`, per the readiness skill's pinning rule.

---

## Java 8 → Java 17 LTS — the stage where the old stacks actually die

### Spring Framework 3.x / 4.x → 5.3.x (still `javax`)

**This is not optional and it is not deferrable to a Spring Boot stage.** Spring
3.x/4.x bundle an ASM version that cannot read Java 9+ class files; on Java 17
component scanning fails with `ArrayIndexOutOfBoundsException` or
`IllegalArgumentException: Unsupported class file major version`. Spring
Framework 5.3.x is the newest line that still uses the `javax` namespace, and it
supports Java 8 through 21 — so it is the correct Java 17 baseline whether or not
a Spring Boot upgrade was requested.

- Bump every `org.springframework:spring-*` artifact to the same newest 5.3.x version. Mixed Spring versions on one classpath fail at startup, not at compile time.
- `org.springframework.orm.hibernate3.*` was **removed in Spring 5** (so was `hibernate4`). Rewrite any `LocalSessionFactoryBean`, `HibernateTemplate`, `HibernateTransactionManager` or `HibernateDaoSupport` import from `org.springframework.orm.hibernate3` to `org.springframework.orm.hibernate5`, in step with the Hibernate bump below. A typical Java config:

```java
// Before — Spring 3.1 + Hibernate 3.5
import org.springframework.orm.hibernate3.LocalSessionFactoryBean;
import org.springframework.orm.hibernate3.HibernateTransactionManager;

// After — Spring 5.3 + Hibernate 5.6
import org.springframework.orm.hibernate5.LocalSessionFactoryBean;
import org.springframework.orm.hibernate5.HibernateTransactionManager;
```

`LocalSessionFactoryBean` in `hibernate5` takes `setPackagesToScan(...)` and a
`DataSource`; the `hibernate3` `setMappingResources`/`setConfigLocation` style
still works for `.hbm.xml` mappings. If the plan's Spring Boot stages will move
this code to Spring Data JPA anyway, still do the `hibernate5` rewrite here —
the intermediate stage has to compile and run.

- If the app has **no Spring Boot upgrade requested**, note in the summary that Spring 5.3 does not support Java 25 either: the Java 17 → 25 stage has to take the framework to Spring 6.x, which forces the Jakarta rename. Say so explicitly rather than leaving a Spring 5.3 app on a Java 25 release.

### Hibernate 3.x/4.x → 5.6.x

- Bump `org.hibernate:hibernate-core` (the groupId only changes to `org.hibernate.orm` at 6.x — that is a later stage).
- **`org.hibernate.Interceptor` implementations must be rewritten.** The SPI signatures changed across 4 → 5 → 6 (`onSave`/`onFlushDirty`/`preFlush` argument types, and `org.hibernate.type.Type` moved), so an audit interceptor written against 3.5 will not compile. Prefer replacing it with an event listener rather than chasing the SPI:

```java
// Before — Hibernate 3.5 Interceptor
public class AuditInterceptor extends EmptyInterceptor {
    public boolean onSave(Object entity, Serializable id, Object[] state,
                          String[] propertyNames, Type[] types) { ... }
}

// After — Hibernate 5/6 event listeners
public class AuditListener implements PreInsertEventListener, PreUpdateEventListener {
    @Override public boolean onPreInsert(PreInsertEvent event) { ... return false; }
    @Override public boolean onPreUpdate(PreUpdateEvent event) { ... return false; }
}
```

Register the listener through an `Integrator` or, once on Spring Boot,
`hibernate.integrator_provider`. Returning `true` from a pre-event listener
vetoes the operation — return `false` unless the old interceptor deliberately
cancelled the write.

- Drop `hibernate.dialect=org.hibernate.dialect.Oracle10gDialect` (and the other versioned `Oracle*Dialect` classes): they are removed in Hibernate 6, and from 5.x on the dialect is auto-detected from the JDBC connection. Removing the property is safer than pinning a class name that disappears in the next stage.
- Replace `org.hibernate.connection.C3P0ConnectionProvider` / `hibernate.c3p0.*` settings with a container- or Spring-managed `DataSource` backed by **HikariCP**. Carry the pool settings over by meaning, not by name: `c3p0.max_size` → `maximumPoolSize`, `c3p0.min_size` → `minimumIdle`, `c3p0.timeout` (seconds) → `idleTimeout` (**milliseconds**), `c3p0.acquire_increment` has no equivalent and is dropped.

### Jackson 1 (`org.codehaus.jackson`) → Jackson 2 (`com.fasterxml.jackson`)

Jackson 1 has been unmaintained for a decade and its `ObjectMapper` configuration
API was replaced wholesale in 2. Both the imports and the configuration calls
change:

| Jackson 1 | Jackson 2 |
|---|---|
| `org.codehaus.jackson.map.ObjectMapper` | `com.fasterxml.jackson.databind.ObjectMapper` |
| `org.codehaus.jackson.annotate.JsonProperty` / `JsonIgnore` | `com.fasterxml.jackson.annotation.JsonProperty` / `JsonIgnore` |
| `org.codehaus.jackson.map.SerializationConfig.Feature.X` | `com.fasterxml.jackson.databind.SerializationFeature.X` (or `MapperFeature` for mapper-wide options) |
| `org.codehaus.jackson.map.DeserializationConfig.Feature.X` | `com.fasterxml.jackson.databind.DeserializationFeature.X` |
| `org.codehaus.jackson.map.annotate.JsonSerialize.Inclusion` | `com.fasterxml.jackson.annotation.JsonInclude.Include` |
| `mapper.setVisibility(JsonMethod.FIELD, ...)` | `mapper.setVisibility(PropertyAccessor.FIELD, ...)` |
| `org.springframework.http.converter.json.MappingJacksonHttpMessageConverter` | `MappingJackson2HttpMessageConverter` (Spring 5) |

`JsonMethod` and the nested `Feature` enums do not exist in Jackson 2 — a
converter bean built on them will not compile, so rewrite the whole bean method
rather than patching imports one at a time. Watch for both Jackson 1 and 2 being
on the classpath at once: they coexist without a conflict (different packages),
but annotations only take effect for the mapper from the *same* generation, so
mixed annotations silently stop being honoured. Remove the Jackson 1 dependency
once the last import is gone.

### Jackson 2 — the deprecated corners to clear on Java 17

Jackson 2 itself is maintained, but an 8-era Jackson 2 setup usually is not. Call
each of these out and fix it in this stage:

- **Align every Jackson artifact through `com.fasterxml.jackson:jackson-bom`** at the newest 2.x (2.17 as a floor). A `jackson-databind` 2.9 next to a `jackson-datatype-jsr310` 2.12 compiles and then fails with `NoSuchMethodError` at the first serialization. When Spring Boot manages Jackson, delete the explicit versions instead.
- **Jackson 2.x below 2.12 is a security finding**, not just an old version — `jackson-databind` 2.6–2.9 carries a long run of polymorphic-deserialization CVEs. Say so in the summary.
- **`ObjectMapper.enableDefaultTyping()` is deprecated** (and is the gadget-chain entry point) → `activateDefaultTyping(BasicPolymorphicTypeValidator.builder().allowIfSubType("com.example.").build(), DefaultTyping.NON_FINAL)` with an allow-list limited to the application's own packages. Flag `@JsonTypeInfo(use = JsonTypeInfo.Id.CLASS)` on anything that reads untrusted input.
- **`jackson-module-afterburner`** generates bytecode and reflects deeply, which strong encapsulation breaks on Java 17 → `jackson-module-blackbird` (MethodHandle-based), or drop the module.
- **`java.time` needs `jackson-datatype-jsr310`** (`JavaTimeModule`) registered on the mapper. When language modernisation turns a serialized DTO's `Date` into `java.time`, check this, or the JSON shape changes silently.
- `jackson-module-jaxb-annotations` stays on `javax` here; it becomes `jackson-module-jakarta-xmlbind-annotations` in the Spring Boot 3.x stage.

Jackson 2 → **Jackson 3** (`tools.jackson.*`) belongs to the Spring Boot 4.x stage
and is covered in the `springboot-war-to-boot4` skill's
`references/boot4-dependency-cleanup.md`. Do not pull it forward.

### cglib, javassist and AspectJ

- **Delete** explicit `cglib`, `cglib-nodep` and `javassist` dependencies. Spring 5+ ships a repackaged cglib inside `spring-core`, and Hibernate 5.3+ proxies with ByteBuddy — the external artifacts are stale duplicates that cannot parse Java 17+ class files and blow up at runtime with `IllegalArgumentException: Unsupported class file major version` or, once JDK 17 enforces strong encapsulation, `InaccessibleObjectException`.
- Bump `org.aspectj:aspectjweaver` / `aspectjrt` to the newest 1.9.x (1.9.20 is the floor for Java 21; Java 25 needs the newest available). An old weaver fails the same way, usually at context startup rather than at compile time.
- After removing them, grep for direct `net.sf.cglib.*` / `javassist.*` imports in application code. Direct use is rare; if it exists, it is a genuine rewrite and must be called out in the summary, not silently deleted.

### Ehcache 2.x → 3.x (an API rewrite, not a version bump)

Ehcache 2.x is **end-of-life** — unmaintained and not Jakarta-ready. Call it out
as deprecated even where the code still appears to work. Ehcache 3 is a
different API in a different package (`org.ehcache`, not `net.sf.ehcache`),
aligned with JSR-107:

| Ehcache 2 | Ehcache 3 |
|---|---|
| `net.sf.ehcache.CacheManager` | `org.ehcache.CacheManager` (built via `CacheManagerBuilder`) |
| `net.sf.ehcache.Cache` (untyped) | `org.ehcache.Cache<K, V>` (typed at configuration time) |
| `cache.getKeys()` | **Gone.** `Cache` is `Iterable<Cache.Entry<K,V>>` — iterate and collect keys, and say in the summary that this is now an O(n) scan |
| `cache.getQuiet(key)` | **Gone.** Use `cache.get(key)`; there is no read that bypasses statistics |
| `cache.get(key).getObjectValue()` | `cache.get(key)` returns the value directly (`Element` no longer exists) |
| `ehcache.xml` (2.x schema) | 3.x XML schema, or programmatic `CacheManagerBuilder` configuration |

Any controller or admin endpoint that introspects the cache (listing keys,
peeking at entries without touching statistics) has to be rewritten, not
re-imported. If the code cannot be expressed on the 3.x API, keep the endpoint's
contract and return what 3.x can supply, and flag the behavioural difference.

**JGroups-based replication** (`net.sf.ehcache.distribution.jgroups`) has no
Ehcache 3 equivalent. Do not attempt to port it: state in the summary that
distributed caching needs a deliberate decision (a clustered cache such as
Hazelcast/Redis, or dropping replication in favour of a shorter TTL), and leave
the local cache working.

**The framework integrations go too.** Grep for these, not just `net.sf.ehcache`:

- **Spring's Ehcache 2 cache support was removed in Spring Framework 6:** `org.springframework.cache.ehcache.EhCacheCacheManager`, `EhCacheManagerFactoryBean`, `EhCacheFactoryBean`, including `<bean class="org.springframework.cache.ehcache.…">` entries in XML contexts. Rewrite onto JSR-107: `org.springframework.cache.jcache.JCacheCacheManager` wrapping a `javax.cache.CacheManager` from `Caching.getCachingProvider("org.ehcache.jsr107.EhcacheCachingProvider")`, with `javax.cache:cache-api` added. `@Cacheable` / `@CacheEvict` call sites stay as they are. Once on Spring Boot, this becomes `spring-boot-starter-cache` + `spring.cache.jcache.config=classpath:ehcache.xml`.
- **`javax.cache` is JSR-107, not Jakarta EE.** It is never renamed — there is no `jakarta.cache`.
- **Hibernate second-level cache:** `hibernate-ehcache` (`org.hibernate.cache.ehcache.EhCacheRegionFactory` / `SingletonEhCacheRegionFactory`) is deprecated in Hibernate 5.6 and removed in 6 → `hibernate-jcache` with `hibernate.cache.region.factory_class=jcache`, `hibernate.javax.cache.provider=org.ehcache.jsr107.EhcacheCachingProvider` and `hibernate.javax.cache.uri=classpath:ehcache.xml`. Region names and `@Cache(usage = …)` annotations carry over unchanged.
- **`ehcache-web`** (`SimplePageCachingFilter`, `GzipFilter`) has no Ehcache 3 counterpart. Remove the filter mapping and flag the decision: `Cache-Control` / ETag headers (Spring's `ShallowEtagHeaderFilter`) or a `@Cacheable` service layer. Do not hand-write a page-cache filter.
- **Ehcache 3 parses `ehcache.xml` with JAXB.** Before the Spring Boot 3.x stage that needs the `javax.xml.bind` dependencies above; from that stage on use the `jakarta` classifier (`org.ehcache:ehcache:3.10.x:jakarta`).

### log4j 1.2.x → SLF4J + Logback

log4j 1.2 is end-of-life and unmaintained. Route logging through the SLF4J API
so the backend stays swappable (and so a later Spring Boot stage's
`spring-boot-starter-logging` just works):

```java
// Before
import org.apache.log4j.Logger;
private static final Logger LOG = Logger.getLogger(ETagContentFilter.class);

// After
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
private static final Logger LOG = LoggerFactory.getLogger(ETagContentFilter.class);
```

- `LOG.debug("x=" + x)` becomes `LOG.debug("x={}", x)`, and the `isDebugEnabled()` guard around a parameterised call can go.
- SLF4J has no `Level`/`Priority` API and no `Logger.getRootLogger()`; code that sets levels at runtime must use the backend directly and should be flagged.
- Translate `log4j.properties` / `log4j.xml` into `logback.xml` (appenders, pattern layouts, per-logger levels). Keep the same file names and rolling policy so operators' log tooling still works.
- If a third-party dependency still logs through the log4j 1.x API, add `org.slf4j:log4j-over-slf4j` and make sure `log4j:log4j` itself is excluded — having both on the classpath causes a `StackOverflowError` at first log statement.

### The remaining one-liners

- **`ojdbc6` / `ojdbc14` → `com.oracle.database.jdbc:ojdbc11`** (or `ojdbc17` for a JDK 17+ certified build against a current database). The old artifacts are compiled for Java 6 and are not certified past JDK 8. If an `oracle-19c-to-23ai` companion migration is in the plan, it owns the driver — leave it alone and say so.
- **google-collections and old Guava → the newest Guava** — see the section below.
- **`org.springframework:spring-mock` must never be a runtime dependency.** It is the pre-3.0 test library (superseded by `spring-test`), and production code using `MockHttpServletRequest` / `DelegatingServletOutputStream` to wrap a request is using test doubles to serve live traffic. Replace them with real implementations — extend `HttpServletRequestWrapper` / `HttpServletResponseWrapper` and write a real `ServletOutputStream` subclass (implementing `isReady()`/`setWriteListener()`, which Servlet 3.1+ requires) — then delete the dependency. If the class is only used in tests, move it to `test` scope and swap it for `spring-test` instead.
- **`javax.xml.bind` and friends.** JAXB, JAX-WS, JAF and CORBA left the JDK in 11. Grep the whole codebase, not just the files the task lists — a single `javax.xml.bind.DatatypeConverter` call is enough to break the build. Add `javax.xml.bind:jaxb-api` + `org.glassfish.jaxb:jaxb-runtime` 2.3.x here (the `jakarta.xml.bind` rename belongs to the Spring Boot 3.x stage).

### google-collections and old Guava → the newest Guava

`com.google.collections:google-collections` is Guava's abandoned predecessor
(last release 1.0, 2009). It ships the *same* `com.google.common.*` packages as
Guava, so having both on the classpath produces duplicate classes and whichever
jar sorts first wins. Call it out as **abandoned** and migrate it — and any
outdated `com.google.guava:guava` — to the **newest Guava release**, not merely
"some Guava":

- **Target:** `com.google.guava:guava` at the newest `-jre` release on Maven Central (33.7.1-jre at the time of writing). Always the `-jre` flavour on a server JDK — never `-android`. Check Maven Central for a newer one rather than copying the number.
- **Remove google-collections outright** — including where a third-party dependency drags it in transitively (add an `<exclusion>`); `mvn dependency:tree -Dincludes=com.google.collections` must come back empty.
- **One Guava version for the whole build.** Libraries bring their own Guava transitively, so pin it once: import `com.google.guava:guava-bom` in `<dependencyManagement>` (or a Gradle `platform(...)`) and drop per-module versions. Guava also pulls `failureaccess` and the `listenablefuture:9999.0-empty-to-avoid-conflict-with-guava` placeholder — leave those alone, they are intentional.
- **Spring Boot does not manage Guava.** In the Spring Boot stages, keep Guava's explicit version (through the BOM or a property) — the "delete versions of Boot-managed artifacts" rule does not apply to it.
- **Old Guava is also a security finding:** releases before 32.0 carry the `Files.createTempDir()` temp-directory CVEs. Say so in the summary.

APIs that were removed or deprecated between google-collections 1.0 / early Guava
and today. Rewrite each call site you find — they fail to compile on the newest
release, which is the point of the upgrade:

| Old call | Newest Guava / JDK replacement |
|---|---|
| `Objects.toStringHelper(...)`, `Objects.firstNonNull(...)` | `MoreObjects.toStringHelper(...)`, `MoreObjects.firstNonNull(...)` |
| `Objects.equal(a, b)` / `Objects.hashCode(...)` | Still present; prefer `java.util.Objects.equals` / `java.util.Objects.hash` while in the file |
| `new Stopwatch()`, `stopwatch.elapsedMillis()` | `Stopwatch.createStarted()` / `createUnstarted()`, `stopwatch.elapsed(TimeUnit.MILLISECONDS)` (or `elapsed()` → `Duration`) |
| `MapMaker().expiration(...)`, `MapMaker().makeComputingMap(...)` | `CacheBuilder.newBuilder().expireAfterWrite(...).build(CacheLoader)` → `LoadingCache` |
| `MoreExecutors.sameThreadExecutor()` | `MoreExecutors.directExecutor()` (or `newDirectExecutorService()` if an `ExecutorService` is required) |
| `Futures.transform(future, fn)`, `Futures.addCallback(future, cb)` without an executor | Pass the executor explicitly — `MoreExecutors.directExecutor()` preserves the old behaviour |
| `Iterators.emptyIterator()` | `java.util.Collections.emptyIterator()` |
| `Closeables.closeQuietly(closeable)`, `InputSupplier` / `OutputSupplier` | try-with-resources; `ByteSource` / `CharSource` / `ByteSink` / `CharSink` |
| `Files.toString(file, cs)`, `Files.readLines(file, cs)` | `Files.asCharSource(file, cs).read()` / `.readLines()`, or `java.nio.file.Files.readString` |
| `Files.createTempDir()` | `java.nio.file.Files.createTempDirectory(...)` |
| `Charsets.UTF_8` | `java.nio.charset.StandardCharsets.UTF_8` |
| `Throwables.propagate(e)` | `Throwables.throwIfUnchecked(e); throw new RuntimeException(e);` |
| `Enums.valueOfFunction(...)` | `Enums.stringConverter(...)` |
| `Hashing.murmur3_32()`, `Hashing.md5()`, `Hashing.sha1()` | `Hashing.murmur3_32_fixed()`; `sha256()` — only where the hash is not persisted or compared with stored values (otherwise keep it and flag it) |

- Collection factories (`Lists.newArrayList()`, `Maps.newHashMap()`) still compile; replace them with `new ArrayList<>()` / `new HashMap<>()` while you are in the file, nothing more.
- Do **not** swap Guava types that cross an API boundary (`com.google.common.base.Optional`, `ImmutableList` return types, `ListenableFuture`) for JDK equivalents in this stage — that changes public contracts. Flag them instead.

---

## Java 17 → Java 25 LTS — mostly verification

If the Java 17 stage was done properly this stage has little library work left.
What it must actively verify:

- **No `cglib`, `cglib-nodep` or `javassist` remains** in any module's dependency tree, including transitively (`mvn dependency:tree -Dincludes=cglib,javassist`). JDK 17+ enforces strong encapsulation by default, so these fail with `InaccessibleObjectException: Unable to make ... accessible: module java.base does not "opens java.lang" to unnamed module`. Adding `--add-opens` to work around it is the wrong fix — remove the library.
- **No remaining reflective access to JDK internals** (`sun.misc.Unsafe`, `setAccessible` on `java.*` types). `--add-opens` in a surefire `argLine` is a documented stop-gap only, and every one of them belongs in the summary.
- **Mockito is on 5.x** (4.x does not support the newest JDKs' bytecode), **Lombok 1.18.40+**, **ByteBuddy** current — these three are the usual JDK-25 annotation-processing failures.
- If the app is still on Spring Framework 5.3 because no Spring Boot upgrade was requested, Spring must move to 6.x here (Spring 5.3 does not support Java 25) — which forces the Jakarta EE `javax.*` → `jakarta.*` rename. Treat it as in-scope for this stage and list every renamed file; never leave a Spring 5.3 application compiled at release 25.
