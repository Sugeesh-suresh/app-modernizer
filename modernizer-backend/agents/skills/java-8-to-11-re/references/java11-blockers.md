# What Breaks Between Java 8 and Java 11

A discovery checklist, not evidence about the repository in front of you.
Nothing here says a file or library is present — record only what you read.
Versions are the commonly documented minimums; the real build is the arbiter,
so mark any version claim you did not verify as inferred.

## 1. Java EE modules removed from the JDK (JEP 320, Java 11)

Compiles on Java 8 without any dependency; fails with `package ... does not
exist` on Java 11.

| API | Packages | Compile-time artifact (javax namespace) | Runtime on WildFly |
|---|---|---|---|
| JAXB | `javax.xml.bind.*` | `javax.xml.bind:jaxb-api:2.3.1` | container-provided |
| JAX-WS | `javax.xml.ws.*`, `javax.jws.*`, `javax.xml.soap.*` | `javax.xml.ws:jaxws-api:2.3.1`, `javax.xml.soap:javax.xml.soap-api:1.4.0`, `javax.jws:javax.jws-api:1.1` | container-provided |
| JAF | `javax.activation.*` | `javax.activation:javax.activation-api:1.2.0` | container-provided |
| Common Annotations | `javax.annotation.PostConstruct`, `PreDestroy`, `Resource`, `Resources`, `Generated` | `javax.annotation:javax.annotation-api:1.3.2` | container-provided |
| JTA | `javax.transaction.*` (NOT `javax.transaction.xa`, which stays in the JDK) | `javax.transaction:javax.transaction-api:1.3` | container-provided |
| CORBA / RMI-IIOP | `org.omg.*`, `javax.rmi.*`, `javax.activity.*` | no drop-in; needs a human decision | only via WildFly's IIOP subsystem |

Two things decide the right fix, and both must be recorded:

1. **Does an existing dependency already supply the API at compile time?** A
   `provided` `javax:javaee-api`, `javax:javaee-web-api`, or a
   `org.jboss.spec` / `jboss-javaee-*` spec BOM may already contain some of
   these. Check which, rather than assuming.
2. **Who supplies it at runtime?** Inside a WAR on WildFly, the container
   does, so the compile-time artifact belongs in `provided` scope — bundling
   an API jar into `WEB-INF/lib` duplicates a class the container already
   loads. Code that runs *outside* the container (a standalone JAR module,
   a CLI, unit tests that marshal XML) additionally needs an implementation
   at runtime or test scope (e.g. `org.glassfish.jaxb:jaxb-runtime:2.3.x`).

Note `javax.annotation.Generated` in generated sources (JAXB/xjc, wsimport,
MapStruct, Immutables, protobuf): the generator, not the file, is what needs
the fix.

## 2. JDK-internal and removed APIs

| Usage | Status on 11 | Replacement |
|---|---|---|
| `sun.misc.BASE64Encoder` / `BASE64Decoder` | removed (9) | `java.util.Base64` — the MIME variants preserve the old line-wrapping/whitespace behaviour |
| `sun.reflect.Reflection.getCallerClass()` | inaccessible | `StackWalker.getInstance(RETAIN_CLASS_REFERENCE).getCallerClass()` |
| `sun.misc.Cleaner` | moved/internal | `java.lang.ref.Cleaner` |
| `sun.misc.Unsafe` | still reachable via `jdk.unsupported` | usually no change; record it |
| `com.sun.*` internals, `sun.security.*` | strongly encapsulated, warnings on 11 | public API where one exists; record |
| `Thread.destroy()`, `Thread.stop(Throwable)` | removed (11) | redesign — cooperative interruption |
| `System.runFinalizersOnExit`, `Runtime.runFinalizersOnExit` | removed (11) | shutdown hooks |
| `SecurityManager.checkAwtEventQueueAccess`, `checkMemberAccess`, `checkSystemClipboardAccess`, `checkTopLevelWindow` | removed (11) | `checkPermission(...)` |
| `javax.security.auth.Policy` | removed (11) | `java.security.Policy` |
| JavaFX (`javafx.*`) | no longer in the JDK | OpenJFX dependency — a decision, not a bump |
| Nashorn (`javax.script` "nashorn") | deprecated, still present in 11 | no change for Java 11 |

## 3. Behavioural changes that compile cleanly

- `(URLClassLoader) ClassLoader.getSystemClassLoader()` — the system loader is
  no longer a `URLClassLoader` (Java 9): `ClassCastException` at runtime.
- Version parsing that assumes `1.x` — `java.version` is now `11.0.x`; code
  such as `substring(2, 3)` or `Float.parseFloat(...)` misreads it. Old
  `commons-lang` / `commons-lang3` `SystemUtils`/`JavaVersion` do the same
  (commons-lang3 3.8+ knows Java 11).
- `_` as an identifier is a compile error (Java 9).
- Locale data: CLDR is the default (JEP 252, Java 9). Date, number and
  currency formatting output can change. The switch back
  (`-Djava.locale.providers=COMPAT,CLDR`) is a JVM option — i.e. frozen launch
  configuration, an ops action.
- Reflective `setAccessible(true)` into JDK classes prints "illegal reflective
  access" warnings on 11 and still works (it is denied from Java 16). Record,
  do not "fix" with `--add-opens`.

## 4. Build tooling that cannot run on JDK 11

| Tool | Problem | Commonly documented floor |
|---|---|---|
| maven-compiler-plugin | old releases mishandle `release` 11 | 3.8.0+ (3.8.1 widely used) |
| maven-surefire / failsafe | cannot fork reliably on JDK 9+ before 2.22 | 2.22.0+ |
| maven-war-plugin | 2.x fails on JDK 9+ | 3.2.2+ — version only; its configuration shapes the WAR |
| maven-javadoc-plugin | JDK 9+ javadoc changes | 3.0.1+ |
| maven-enforcer-plugin | a `requireJavaVersion` rule pinned to 1.8 fails the build | rule range must admit 11 |
| animal-sniffer | a `java18` signature check contradicts a release-11 build | review; `--release` already checks the API |
| jacoco-maven-plugin | cannot read Java 11 class files | 0.8.2+ |
| findbugs-maven-plugin | FindBugs cannot read Java 9+ class files | spotbugs-maven-plugin |
| aspectj-maven-plugin (codehaus 1.11) | no Java 11 compliance level | 1.14.0, or the `dev.aspectj` fork |
| jaxb2-maven-plugin / xjc, jaxws-maven-plugin / wsimport | rely on JDK tools removed in 11 | versions that bring their own tools (jaxb2 2.5.0, `com.sun.xml.ws:jaxws-maven-plugin` 2.3.x) |
| Gradle | wrapper older than 5.0 cannot run on JDK 11 | 5.0+ |

## 5. Libraries that fail on Java 11 class files or APIs

Bytecode libraries must understand class-file version 55:

| Library | Commonly documented floor |
|---|---|
| ASM | 7.0 |
| cglib | 3.3.0 (or remove when the framework repackages it) |
| javassist | a release from 2018 onward; prefer the newest 3.x |
| Byte Buddy | a release from late 2018 onward; prefer the newest 1.x |
| AspectJ (weaver/rt/tools) | 1.9.2 |
| Lombok | 1.18.4 |
| Mockito | 2.23.0 (`mockito-all` 1.x does not work) |
| PowerMock | 2.0.x with Mockito 2 |
| Spring Framework | 5.1+ supports JDK 11; 3.x cannot read Java 11 class files; 4.3.x is EOL and not documented for 11 |
| Hibernate ORM (when bundled in the WAR) | 5.3/5.4+ |

Libraries that are **EOL but run on Java 11** (Jackson 1, log4j 1.2,
Ehcache 2, old Guava, commons-lang 2) are Security/EOL findings for the
report — not Java 11 work, unless an actual Java 11 failure is evidenced.

## 6. Container and launch configuration (frozen — report only)

- WildFly lines older than about 14 (JBoss EAP older than 7.2) are not
  documented as running on Java 11. Classes compiled for release 11 cannot
  load on a Java 8 JVM (`UnsupportedClassVersionError`).
- JVM options that stop a Java 11 JVM from starting: `-XX:+PrintGCDateStamps`,
  `-XX:+PrintGCTimeStamps`, `-XX:+UseGCLogFileRotation`,
  `-XX:NumberOfGCLogFiles`, `-XX:GCLogFileSize`, `-XX:+UseParNewGC`,
  `-XX:+CMSIncrementalMode`, `-Xincgc` (GC logging moved to `-Xlog:gc*`).
  `-XX:MaxPermSize` is ignored with a warning.
- Default GC changed to G1 (Java 9) — a performance consideration, not a
  failure.
- All of these live in standalone.conf / Docker / scripts, which this
  migration never edits: they become ops action items in the plan and report.
