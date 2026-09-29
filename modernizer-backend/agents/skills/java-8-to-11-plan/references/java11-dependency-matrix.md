# Java 11 Dependency & Plugin Matrix

For deciding what moves, to what, and why. The **minimal-change rule** holds
throughout: move a coordinate only when Java 11 needs it, and to the smallest
version that fixes the problem unless a row says otherwise. Versions below are
commonly documented floors and known-good choices — mark any you did not see
verified in the specification as inferred (`*`) in the Confidence Register;
the build loop is the arbiter.

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

| Plugin | Move when | Target |
|---|---|---|
| maven-compiler-plugin | below 3.8.0 | 3.8.1 (or newer if the Maven version allows) |
| maven-surefire-plugin / maven-failsafe-plugin | below 2.22.0 | 2.22.2 |
| maven-war-plugin | 2.x | 3.4.0 — **`<version>` only**; its configuration is frozen |
| maven-jar-plugin / maven-resources-plugin | 2.x and failing | newest 3.x |
| maven-javadoc-plugin | below 3.0.1 and bound to the build | newest 3.x |
| maven-shade-plugin | below 3.2.0 | newest 3.x |
| maven-enforcer-plugin | `requireJavaVersion` excludes 11 | widen the range to admit 11 (e.g. `[11,)`) |
| animal-sniffer-maven-plugin | a `java18` signature in a release-11 build | remove the check or its `java18` signature — `--release 11` enforces the API now |
| jacoco-maven-plugin | below 0.8.2 | 0.8.8+ |
| findbugs-maven-plugin | present | `com.github.spotbugs:spotbugs-maven-plugin` newest 4.x, same checks |
| aspectj-maven-plugin (org.codehaus.mojo) | 1.11 or older | 1.14.0 with `<complianceLevel>11</complianceLevel>` |
| jaxb2-maven-plugin (xjc) | below 2.5.0 | 2.5.0 |
| org.codehaus.mojo:jaxws-maven-plugin (wsimport) | present | `com.sun.xml.ws:jaxws-maven-plugin` 2.3.x (brings its own wsimport) |
| wildfly-maven-plugin / jboss-as-maven-plugin / cargo | — | **frozen, never touched** |
| Gradle wrapper | below 5.0 | the lowest that runs on 11 and the build's plugins (5.6.4 / 6.9.4) |

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

| Library | Move when | Target | Note |
|---|---|---|---|
| Spring Framework | 3.x, or 4.x | newest 5.3.x | 3.x cannot read Java 11 class files. 4.3 is EOL and not documented for 11. 4 → 5 is not a pure bump: `orm.hibernate3` support, Velocity, and some deprecated APIs are gone — size the call sites. Still `javax`. Spring Security moves with it (5.x). |
| Hibernate ORM | below 5.3, and bundled | 5.4.33.Final or 5.6.15.Final (javax) | if WildFly provides Hibernate (JPA with a container persistence unit), it is the container's — do not touch |
| ASM | below 7.0 | newest 9.x | |
| cglib | below 3.3.0 | 3.3.0, or remove if Spring's repackaged copy is what is used | |
| javassist | old | newest 3.x | |
| Byte Buddy | old | newest 1.x | |
| AspectJ (aspectjrt / aspectjweaver / aspectjtools) | below 1.9.2 | newest 1.9.x that still supports compliance 11 | |
| Lombok | below 1.18.4 | newest 1.18.x | |
| mockito-all 1.x / mockito-core 1.x | always | `mockito-core` **2.28.2** | the minimal hop: Java 11 support landed in 2.23, and 2.x still has `Matchers`, `anyObject()` and `org.mockito.runners` that 4.x deletes. Test code changes: runner package, `anyString()` no longer matches null, `Whitebox` removed |
| PowerMock 1.x | always | 2.0.9 (`powermock-api-mockito2`) | |
| commons-lang3 | below 3.8 and `SystemUtils`/`JavaVersion` used | 3.8.1+ | older versions misread Java 9+ version strings |
| JavaFX | used | OpenJFX 11 | a decision, not a bump — escalate |

## Explicitly not moved by this migration

Unless a real Java 11 failure is evidenced: Jackson (1 or 2), log4j 1.2,
Ehcache 2, Guava, commons-collections, Quartz, JUnit 3/4 (JUnit 4.12 runs on
11), Servlet/JSP/EL APIs (container-provided), the Java EE / Jakarta platform
version. List them under Deprecated Libraries if EOL, and under Out of Scope.
