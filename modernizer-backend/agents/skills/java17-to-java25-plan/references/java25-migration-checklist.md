# Java 17 → Java 25 Migration Checklist

## Environment & Tooling

- [ ] Install JDK 25 (OpenJDK or vendor distribution)
- [ ] Update `JAVA_HOME` and PATH
- [ ] Update Maven: `mvn --version` should show compatible version (Maven 3.9+)
- [ ] Update Gradle to 8.8+ if using Gradle
- [ ] Update IDE: IntelliJ IDEA 2024.2+, Eclipse 2024-09, VS Code Java Extension Pack latest
- [ ] Update `pom.xml` / `build.gradle`: `<java.version>25</java.version>` or `sourceCompatibility = 25`

## Dependency Upgrades

| Category | Upgrade |
|---|---|
| Spring Boot | `3.3.x` → `3.4.x` or latest 3.x |
| Spring Framework | `6.1.x` → `6.2.x` |
| Hibernate ORM | `6.4.x` or latest |
| Jackson | `2.17.x` or latest |
| Lombok | `1.18.34` or latest |
| MapStruct | `1.5.5.Final` or latest |
| Mockito | `5.x` or latest |
| JUnit 5 | `5.11.x` or latest |
| Flyway | `10.x` or latest |
| Testcontainers | `1.20.x` or latest |

## Code Modernisation

### Thread Pool → Virtual Threads
- [ ] Replace `Executors.newFixedThreadPool(n)` with `Executors.newVirtualThreadPerTaskExecutor()`
- [ ] Replace Spring `@Async` executor bean with virtual thread executor
- [ ] Configure embedded Tomcat to use virtual threads: `spring.threads.virtual.enabled=true`
- [ ] Review `synchronized` blocks — virtual threads can pin carriers; prefer `ReentrantLock`

### Pattern Matching
- [ ] Replace `instanceof` + cast chains with pattern matching switch expressions
- [ ] Replace multi-branch `if/else if` type checks with sealed class + exhaustive switch
- [ ] Audit `switch` statements on String/Integer — migrate to switch expressions

### Records
- [ ] Replace Lombok `@Value` / `@Data` immutable classes with `record`
- [ ] Replace simple DTOs and value objects with records
- [ ] Note: records cannot extend classes; use interfaces for polymorphism

### Sealed Classes
- [ ] Identify closed type hierarchies (Result, Event, Command patterns)
- [ ] Replace open class hierarchies with `sealed` + `permits`
- [ ] Update all switches on sealed types to exhaustive switch expressions

### Sequenced Collections
- [ ] Replace `list.get(0)` with `list.getFirst()`
- [ ] Replace `list.get(list.size()-1)` with `list.getLast()`
- [ ] Replace `Collections.unmodifiableList(new ArrayList<>(list))` with `List.copyOf(list)`

### Deprecated API Replacements
- [ ] Remove all `Thread.stop()` / `suspend()` / `resume()` — use interruption
- [ ] Remove `SecurityManager` configuration
- [ ] Replace `java.util.Date` / `Calendar` with `java.time.*`
- [ ] Replace `Object.finalize()` overrides with `java.lang.ref.Cleaner`
- [ ] Remove any CMS GC flags (`-XX:+UseConcMarkSweepGC`) from JVM args

## Validation & Rollout

- [ ] Run full test suite: `mvn test`
- [ ] Run integration tests with Java 25 runtime
- [ ] Performance benchmark: compare startup time, throughput, memory vs Java 17 baseline
- [ ] Verify Virtual Thread performance under load: use JFR (Java Flight Recorder) to check carrier pinning
- [ ] Test native image build if applicable (GraalVM 24.x for Java 25)
- [ ] Update Docker base image: `FROM eclipse-temurin:25-jre-alpine`
- [ ] Update CI/CD pipeline: `java-version: '25'` in GitHub Actions / Jenkins
