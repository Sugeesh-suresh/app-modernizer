# Java 11 Dependency & Plugin Matrix

For deciding what moves, to what, and why.

**Compile-first: the build decides, not this table.** The run builds the
uploaded code on JDK 11 before planning (the Technical Specification's
*Baseline Build on JDK 11*) and builds and **tests** the result after. A
plugin or library moves only when one of those shows the failure in its
row's **Trigger** column — the baseline build output, a validation error, or
a failing test naming it. An old version that builds and passes its tests on
JDK 11 stays exactly as it is, however old: list it under Deprecated
Libraries and Out of Scope. Real migrations of large monoliths succeed by
changing almost nothing beyond the compiler level and the removed JDK
modules; every speculative bump adds risk (renamed artifacts, API breaks in
test code, versions that do not download) and proves nothing.

When a trigger does fire, move to the smallest version that fixes it — the
**Target** column, which lists released versions that exist on Maven Central.

## Compiler configuration (always)

Maven — prefer the single property, and remove the `source`/`target` pair it
replaces so there is one source of truth:

```xml
<properties>
  <maven.compiler.release>11</maven.compiler.release>
</properties>
```

or `<release>11</release>` in the maven-compiler-plugin `<configuration>` if
that is where the build already sets its level. Every module that overrides
the level gets the same change. Gradle: `java { toolchain { languageVersion =
JavaLanguageVersion.of(11) } }` or `options.release = 11`.

Exactly 11 — never 12+.

## Build plugins

| Plugin | Trigger (the build must show this) | Target |
|---|---|---|
| maven-compiler-plugin | `invalid flag: --release`, or `release` not recognised, once the level is set to 11 | 3.8.1 |
| maven-surefire-plugin / maven-failsafe-plugin | `The forked VM terminated without properly saying goodbye`, or tests not run on JDK 11 | 2.22.2 |
| maven-war-plugin | `Execution default-war of goal …maven-war-plugin:2.x:war failed` (packaging on JDK 11) | 3.4.0 — **`<version>` only**; its configuration is frozen |
| maven-jar-plugin / maven-resources-plugin | that plugin's execution fails on JDK 11 | newest 3.x |
| maven-javadoc-plugin | it fails during `package` on JDK 11 | newest 3.x |
| maven-shade-plugin | `Unsupported class file major version 55` from shade | newest 3.x |
| maven-enforcer-plugin | `RequireJavaVersion failed` | widen the range to admit 11 (e.g. `[11,)`) |
| animal-sniffer-maven-plugin | its `java18` signature check fails | remove the check or its `java18` signature |
| jacoco-maven-plugin | `Unsupported class file major version 55` from jacoco during tests | 0.8.8 |
| findbugs-maven-plugin | it fails on JDK 11 classes during the build | `com.github.spotbugs:spotbugs-maven-plugin` 4.x, same checks |
| aspectj-maven-plugin (org.codehaus.mojo) | `bad version number found … expected <= 52` / compliance errors | 1.14.0 with `<complianceLevel>11</complianceLevel>` |
| jaxb2-maven-plugin (xjc) | xjc fails on JDK 11 | 2.5.0 |
| org.codehaus.mojo:jaxws-maven-plugin (wsimport) | wsimport not found on JDK 11 | `com.sun.xml.ws:jaxws-maven-plugin` 2.3.x |
| wildfly-maven-plugin / jboss-as-maven-plugin / cargo | — | **frozen, never touched** |
| Gradle wrapper | the wrapper cannot start on JDK 11 | the lowest that runs on 11 and the build's plugins (5.6.4 / 6.9.4) |

## Java EE modules removed from the JDK

Add only for APIs the code actually imports, and only when no existing
dependency already supplies them. In a WAR deployed to WildFly these are
**`provided`** — the container supplies them at runtime:

| Imports | Coordinate | Scope in a WildFly WAR |
|---|---|---|
| `javax.xml.bind.*` | `javax.xml.bind:jaxb-api:2.3.1` | provided |
| `javax.xml.ws.*`, `javax.jws.*` | `javax.xml.ws:jaxws-api:2.3.1` | provided |
| `javax.xml.soap.*` | `javax.xml.soap:javax.xml.soap-api:1.4.0` | provided |
| `javax.activation.*` | `javax.activation:javax.activation-api:1.2.0` | provided |
| `javax.annotation.PostConstruct` / `PreDestroy` / `Resource` / `Generated` | `javax.annotation:javax.annotation-api:1.3.2` | provided |
| `javax.transaction.*` (not `.xa`) | `javax.transaction:javax.transaction-api:1.3` | provided |

Exceptions:
- A module that runs **outside** WildFly (a standalone JAR, a batch launcher)
  needs the API in `compile` scope plus an implementation at `runtime`
  (`org.glassfish.jaxb:jaxb-runtime:2.3.x`, `com.sun.xml.ws:jaxws-rt:2.3.x`,
  `com.sun.activation:javax.activation:1.2.0`).
- **Tests** that marshal XML or call JAX-WS outside the container need the
  implementation in `test` scope.
- If the build already has a `provided` `javax:javaee-api` / `javaee-web-api`
  / JBoss spec BOM, check what it actually contains before adding a
  duplicate — the specification's Removed-JDK-Module Usage table says.
- CORBA (`org.omg.*`, `javax.rmi`) has no drop-in: escalate.

## Libraries (only when bundled in the WAR — never when container-provided)

Every row needs its trigger in the baseline build, a validation error or a
failing test. "Old" or "EOL" is never a trigger.

| Library | Move when (trigger) | Target | Note |
|---|---|---|---|
| Spring Framework | 3.x (cannot read Java 11 class files: `ASM ClassReader failed to parse class file`), or a test/startup failure in Spring 4.x on JDK 11. Spring 4.3 that builds and passes its tests stays | newest 5.3.x | 3.x cannot read Java 11 class files. 4.3 is EOL and not documented for 11. 4 → 5 is not a pure bump: `orm.hibernate3` support, Velocity, and some deprecated APIs are gone — size the call sites. Still `javax`. Spring Security moves with it (5.x). |
| Hibernate ORM | bundled, and a JDK 11 failure (javassist/bytecode enhancement errors, test failures) names it | 5.4.33.Final or 5.6.15.Final (javax) | if WildFly provides Hibernate (JPA with a container persistence unit), it is the container's — do not touch |
| ASM | `Unsupported class file major version 55` from it | newest 9.x | |
| cglib | proxy-generation failures on JDK 11 | 3.3.0, or remove if Spring's repackaged copy is what is used | |
| javassist | `IllegalAccessError` / class-file errors from it on JDK 11 | newest 3.x | |
| Byte Buddy | `Java 11 (55) is not supported` from it | newest 1.x | |
| AspectJ (aspectjrt / aspectjweaver / aspectjtools) | weaving/compile errors on JDK 11 class files | newest 1.9.x that still supports compliance 11 | |
| Lombok | `IllegalAccessError … com.sun.tools.javac` | newest 1.18.x | |
| mockito-all 1.x / mockito-core 1.x | a test fails on JDK 11 inside Mockito/cglib (e.g. `Mockito cannot mock this class`, cglib `IllegalArgumentException`). Mockito 1 tests that pass on 11 stay on 1.x | `mockito-core` **2.28.2** | the minimal hop: Java 11 support landed in 2.23, and 2.x still has `Matchers`, `anyObject()` and `org.mockito.runners` that 4.x deletes. Test code changes: runner package, `anyString()` no longer matches null, `Whitebox` removed |
| PowerMock 1.x | a PowerMock test fails on JDK 11, or Mockito moved to 2.x (PowerMock 1.x requires Mockito 1) | 2.0.9 — and the Mockito module's **artifactId changes**: `powermock-api-mockito` → `powermock-api-mockito2` | `powermock-api-mockito:2.x` does not exist (it stops at 1.7.4); a build asking for it fails to download, often as 401 from a repository manager. `powermock-module-junit4` keeps its name |
| commons-lang3 | a failure from `SystemUtils`/`JavaVersion` misreading "11" | 3.8.1+ | older versions misread Java 9+ version strings |
| JavaFX | used | OpenJFX 11 | a decision, not a bump — escalate |

Versions in this table are released versions that exist on Maven Central.
Never plan a version that is not here or in the specification: an invented
version — especially a build-stamped pre-release like `2.4.0-b180608.0325` —
does not download. A JAXB/JAX-WS **implementation** (`jaxb-runtime`,
`jaxws-rt`) is `2.3.x` (`2.3.1`); never a `2.4.0-b…` pre-release, and never
its transitive artifacts (`txw2`, `istack-commons-runtime`) on their own.

## Explicitly not moved by this migration

Unless a real Java 11 failure is evidenced: Jackson (1 or 2), log4j 1.2,
Ehcache 2, Guava, commons-collections, Quartz, JUnit 3/4 (JUnit 4.12 runs on
11), Servlet/JSP/EL APIs (container-provided), the Java EE / Jakarta platform
version. List them under Deprecated Libraries if EOL, and under Out of Scope.
