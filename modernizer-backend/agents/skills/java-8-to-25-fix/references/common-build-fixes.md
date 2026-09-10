# Common Java 8 → Java 25 Build Errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `package javax.xml.bind does not exist` (JAXB) or similar for JAX-WS/CORBA | Java EE module removed in JDK 11, no longer on the bootclasspath | Add the equivalent standalone dependency (e.g. `jakarta.xml.bind:jakarta.xml.bind-api` + a runtime impl), or replace the usage |
| `error: invalid source release: 11` (or 17/21/25) at Stage N | `maven-compiler-plugin`/Gradle toolchain predates the stage's target JDK | Bump the compiler plugin/toolchain version for this stage before retrying |
| `package javax.persistence does not exist` (or servlet/validation/annotation) | Framework was bumped to Jakarta EE 9+ but an import was missed | Change `javax.*` import to the matching `jakarta.*` import |
| `cannot find symbol` on a getter/setter after converting a class to a record | Callers still use `getX()`/`setX()` bean-style accessors | Update call sites to the record's accessor method (`x()`), or keep a compatibility method if the class is a public API boundary |
| `error: switch expression does not cover all possible input values` | Sealed type added a new permitted subtype without a corresponding `case` | Add the missing `case` branch |
| `error: incompatible types` after replacing `Date`/`Calendar` with `java.time.*` | Call site still expects the old type | Update the call site's parameter/return type, or add an explicit conversion at the boundary |
| `cannot find symbol: method getFirst()/getLast()` | Called on a collection type/interface that doesn't implement `SequencedCollection` | Confirm the runtime type is a supported collection (e.g. `ArrayList`, `LinkedHashMap`), or fall back to `get(0)`/`get(size()-1)` for that type |
| Maven `Fatal error compiling: invalid target release: 25` | `maven-compiler-plugin` version predates JDK 25 support, or wrong `release`/`source`/`target` value | Bump `maven-compiler-plugin` to a current version; set `<release>25</release>` |
| `NoClassDefFoundError` / `ClassNotFoundException` for a Jakarta/Spring class at compile or test time | Old `javax.*`-based dependency still on the classpath alongside a `jakarta.*`-based one | Remove the stale `javax.*` dependency and its exclusions in `pom.xml`/`build.gradle` |
| Lombok-generated methods missing after adding a newer JDK | Lombok version too old for the target JDK | Bump Lombok to a version that supports the target JDK (1.18.34+ for very recent JDKs) |
| JUnit 4 test fails to run / not discovered | Test still uses `org.junit.Test` under a JUnit 5 runner | Migrate the test class to JUnit Jupiter (`org.junit.jupiter.api.Test`) or add the `junit-vintage-engine` dependency |
