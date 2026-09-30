# Java 11 Build Errors and Their Fixes

| Error (as the build prints it) | Cause | Fix inside the fence |
|---|---|---|
| `package javax.xml.bind does not exist` | JAXB left the JDK in 11 | `javax.xml.bind:jaxb-api:2.3.1`, `provided` in a WildFly WAR; implementation in `test` scope if tests marshal |
| `package javax.annotation does not exist` / `cannot find symbol: class PostConstruct` | Common Annotations left the JDK | `javax.annotation:javax.annotation-api:1.3.2`, `provided` |
| `package javax.xml.ws does not exist`, `package javax.jws does not exist` | JAX-WS left the JDK | `javax.xml.ws:jaxws-api:2.3.1`, `provided` |
| `package javax.activation does not exist` | JAF left the JDK | `javax.activation:javax.activation-api:1.2.0`, `provided` |
| `package javax.transaction does not exist` | JTA left the JDK (`javax.transaction.xa` did not) | `javax.transaction:javax.transaction-api:1.3`, `provided` |
| `package org.omg.CORBA does not exist` | CORBA left the JDK | no drop-in — report for a human |
| `package sun.misc does not exist` / `cannot find symbol: class BASE64Encoder` | removed internal API | `java.util.Base64` (MIME variant to keep line wrapping) |
| `package sun.reflect does not exist` | internal API | `StackWalker` |
| `as of release 9, '_' is a keyword` | underscore identifier | rename the variable |
| `exception java.io.IOException is never thrown in body of corresponding try statement` | a replaced API no longer throws | narrow the `try` — keep any handling other calls still need |
| `invalid target release: 11` / `release version 11 not supported` | build JDK older than 11 | environment — report, never lower the release |
| `Fatal error compiling: invalid flag: --release` | maven-compiler-plugin too old | 3.8.1 |
| `Unsupported class file major version 55` (from a plugin or library) | ASM too old in that tool | move that plugin/library to a Java 11-capable version (see the plan's matrix) |
| `Execution default-war of goal ...maven-war-plugin:2.x:war failed` | WAR plugin 2.x on JDK 9+ | maven-war-plugin 3.4.0 — `<version>` only |
| surefire `The forked VM terminated without properly saying goodbye` during compile/package | surefire below 2.22 | 2.22.2 |
| `Rule 0: org.apache.maven.plugins.enforcer.RequireJavaVersion failed` | enforcer range excludes 11 | widen the range to admit 11 |
| `cannot find symbol: class MockitoJUnitRunner` (in `org.mockito.runners`) | only on Mockito 4+ (2.x/3.x keep it, deprecated) | `org.mockito.junit.MockitoJUnitRunner` |
| `cannot find symbol: method getArgumentAt(int,java.lang.Class<…>)` | removed in Mockito 2 | `getArgument(i)` |
| `Could not transfer artifact org.powermock:powermock-api-mockito:pom:2.x` (401/404/absent) | the artifact does not exist at 2.x | `powermock-api-mockito2`, same version |
| `Could not transfer artifact …:2.4.0-b…` / any 401 on a version this run set | invented or pre-release version | the released version from the plan's matrix (JAXB 2.3.1); remove transitive artifacts added on their own |
| `ClassCastException: …AppClassLoader cannot be cast to java.net.URLClassLoader` (at test/run time) | system loader is not a URLClassLoader on 9+ | the modify reference's "Adding jars to the class path at runtime" pattern |
| `cannot find symbol: class Whitebox` | removed in Mockito 2 | set the field through the class's own setter/constructor or reflection in the test |
| `java.lang.NoSuchFieldError` / `IllegalArgumentException: Unsupported class file` from Spring during `package` of an XML/annotation scan | Spring 3.x ASM | Spring 5.3.x (per the plan) |
| Lombok: `java.lang.IllegalAccessError ... com.sun.tools.javac` | Lombok below 1.18.4 | newest 1.18.x |
| AspectJ: `bad version number found in ... expected <= 52` | AspectJ below 1.9.2 | newest 1.9.x, and the plugin's `complianceLevel` 11 |

Warnings that are not errors — leave them: `WARNING: An illegal reflective
access operation has occurred`, deprecation warnings, `[WARNING] ... bootstrap
classpath not set` (resolved by `release` anyway).
