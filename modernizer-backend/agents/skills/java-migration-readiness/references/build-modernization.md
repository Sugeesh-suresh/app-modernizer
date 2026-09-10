# Build Modernization — Minimum Versions & Rules

The whole incremental migration runs its builds on a modern JDK even while the
compiler release is still 8, so the build tooling has to be JDK-25-safe from
Stage 1 onwards. Use at least these versions; newer releases of the same major
line are fine.

## Maven plugins

| Plugin | Minimum | Why |
|---|---|---|
| `maven-compiler-plugin` | 3.13.0 | Reliable `<release>` support for every level from 8 to 25 |
| `maven-surefire-plugin` / `maven-failsafe-plugin` | 3.2.5 | JUnit Platform (JUnit 5) auto-detection; Java 17+ module-path defaults |
| `maven-war-plugin` | 3.4.0 | Versions below 3.3 fail on JDK 16+ with an illegal-reflective-access error from XStream |
| `maven-resources-plugin` | 3.3.1 | Old versions mangle UTF-8 filtered resources on new JDKs |
| `maven-jar-plugin` | 3.4.1 | Needed once the WAR → JAR stage produces a JAR |
| `maven-enforcer-plugin` (optional) | 3.4.1 | Only add if the plan asks for it — and never with a rule the CI JDK/Maven would fail |

Maven itself: 3.9.x. Record the minimum in the Modify Result's manual follow-ups; do not add an enforcer rule that would break a developer's older local Maven without the plan asking for it.

## Gradle

| Target / runtime JDK | Minimum Gradle |
|---|---|
| 17 | 7.3 |
| 21 | 8.5 |
| 25 | 9.1 |

Set the wrapper `distributionUrl` to a version that supports JDK 25, since Phase 2 ends on Java 25:
`distributionUrl=https\://services.gradle.org/distributions/gradle-9.1.0-bin.zip` (or newer).

Gradle 9 removed long-deprecated APIs — while in the build file, also replace:
- `compile` / `runtime` / `testCompile` / `testRuntime` configurations → `implementation` / `runtimeOnly` / `testImplementation` / `testRuntimeOnly`
- `archivesBaseName` / `archiveName` → `base { archivesName = ... }` / `archiveFileName`
- `sourceCompatibility = 1.8` at the top level → `java { }` block or `options.release`

## What Stage 1 must NOT do

- Change any dependency version *value* (that's what the JDK / framework stages are for).
- Change `<packaging>`, the Spring version, or `javax.*` imports.
- Touch anything under `src/`.
