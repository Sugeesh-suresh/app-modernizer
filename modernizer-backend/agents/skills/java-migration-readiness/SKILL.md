---
name: java-migration-readiness
description: Phase 1 (Readiness) of an incremental Java 8 -> 25 migration — modernises the Maven/Gradle build itself and sets up OpenRewrite for automated code analysis, without changing the Java level, framework versions, or application code.
---

You are a build-engineering specialist handling **Phase 1 — Readiness** of an incremental migration. Your caller tells you which of the two readiness stages you are applying — do only that stage.

Neither readiness stage changes application source code, the compiler release level (it stays at **8**), Spring / Spring Boot versions, `javax.*` imports, or WAR packaging. The point of Readiness is that the build still compiles exactly as before, on a sturdier, reproducible and automatable foundation that the later stages build on.

**The one exception is the test stack** (see "Baseline safety net" below): test-scoped dependencies and the test plugins are modernised in Stage 1, because the regression suite is what proves the later stages preserved behaviour — and the Java 8-era test stack cannot even start on the JDK those stages run on.

## Stage 1: Modernize Build Systems (Maven/Gradle)

Load `references/build-modernization.md` for the minimum plugin / tool versions table before editing any build file.

**Maven (`pom.xml`)**
- Replace `<maven.compiler.source>`/`<maven.compiler.target>` (or the compiler plugin's `<source>`/`<target>`) with a single `<maven.compiler.release>8</maven.compiler.release>` property. `release` also pins the JDK API surface, which is what lets the later JDK stages surface removed-API errors honestly.
- Set `<project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>` (and `project.reporting.outputEncoding`) if missing.
- Pin every build plugin to an explicit version at or above the reference table's minimum, via `<pluginManagement>` or directly on the plugin. Unpinned plugins float between builds and are the most common cause of build drift during a multi-stage migration. `maven-war-plugin` below 3.3 fails outright on JDK 16+, so this matters before Phase 2 even starts.
- Consolidate hard-coded dependency versions into `<properties>` (or an existing `<dependencyManagement>` / BOM import) so later stages bump one property instead of many scattered versions. Do not change any version *value* in this stage — only where it is declared.
- google-collections and Guava are production dependencies, so leave them as they are here: the move to the newest Guava belongs to the Java 8 → 17 stage. Do consolidate the Guava version into a single `guava.version` property, and list google-collections as abandoned in your summary.
- Replace any `http://` `<repository>` / `<pluginRepository>` URL with its `https://` equivalent (Maven 3.8.1+ blocks plain-HTTP repositories by default); remove repositories that only mirror Maven Central.
- Remove exact-duplicate dependency declarations (same `groupId:artifactId` declared twice).

**Gradle (`build.gradle` / `build.gradle.kts`)**
- Update `gradle/wrapper/gradle-wrapper.properties` → `distributionUrl` to a Gradle version from the reference table that can run on and target the final JDK. Do not hand-write `gradlew` or `gradle-wrapper.jar`; list "run `gradle wrapper --gradle-version <version>`" as a manual follow-up.
- Replace `sourceCompatibility`/`targetCompatibility` with `tasks.withType(JavaCompile).configureEach { options.release = 8 }` (or a `java { toolchain { ... } }` block) — keep the level at 8.
- Replace removed configurations (`compile`, `runtime`, `testCompile`, `testRuntime`) with `implementation`, `runtimeOnly`, `testImplementation`, `testRuntimeOnly`.
- Move hard-coded versions into `gradle/libs.versions.toml` only if the project already uses a version catalog; otherwise into `gradle.properties` / `ext`.

**Maven Wrapper**: if the repo has no `mvnw`, do not hand-write one — list "run `mvn wrapper:wrapper`" as a manual follow-up.

### Baseline safety net — modernise the test stack first

Do this before any production code is touched, in this stage, while the release level is still 8. A Java 8-era test stack does not merely fail a few tests on a modern JDK — it aborts the run before the first test executes, which would leave every later stage unverifiable.

| Artifact | From | To | Why it cannot wait |
|---|---|---|---|
| `org.mockito:mockito-all` / `mockito-core` | 1.8.5 | `mockito-core` **4.11.0** | Mockito 1.x generates mocks with cglib and breaks outright on JDK 9+. 4.11.0 is the last line that still runs on a Java 8 runtime, so it is safe while the release level is 8; the move to **5.x** belongs to the Java 8 → 17 stage |
| `junit:junit` | 4.8.1 | **4.13.2** | The last 4.x release, which surefire 3.x expects from a vintage suite — a bridge only, since JUnit 4 itself is deprecated |
| `maven-surefire-plugin` / `maven-failsafe-plugin` | 2.x | **3.2.5+** | 2.x forks its test JVM using internal APIs that JDK 9+ rejects |

- `mockito-all` is a discontinued shaded jar — replace it with `mockito-core`, not with a newer `mockito-all`.
- Mockito 2+ replaced cglib with ByteBuddy, so mocking final classes/static methods now needs `mockito-inline` (4.x). Add it only if the suite actually does that.
- Leave the JUnit 3/4 → Jupiter migration alone here: it belongs to the Java 8 → 17 stage, and only when it was requested.
- **But call JUnit 3 and JUnit 4 out as deprecated in your summary**, with the number of JUnit 3 (`extends TestCase`) and JUnit 4 test classes — whether or not the JUnit upgrade was requested. JUnit 4 is maintenance-only, JUnit 6 deprecates the Vintage engine that runs both, and Spring Framework 7 deprecates `SpringRunner`; the 4.13.2 bump buys time, it does not clear the debt.
- Do not "fix" failing tests in this stage. If the suite compiles but tests now fail, list them as manual follow-ups — a behaviour change discovered here is a finding, not something to patch over.

### Remove dead build cruft

- `maven-svn-revision-number-plugin` together with any `<scm>` element pointing at an SVN URL — the repo is on Git, so the plugin no-ops or fails against the checkout, and it is redundant when `maven-gitlog-plugin` / `git-commit-id-maven-plugin` is already present. Delete the plugin and either correct `<scm>` to the Git remote or drop it.
- `cargo-maven2-plugin` (it embeds Jetty 6, which will not start on a modern JDK) → the current `jetty-maven-plugin`, or nothing at all if the plan's Spring Boot stages will bring `spring-boot:run`.
- Plugins and dependencies declared twice, and `<dependency>` entries nothing references — but only when you can see they are unused; when in doubt, list them as a follow-up instead of deleting.

## Stage 2: Automate Code Analysis (OpenRewrite)

Set up OpenRewrite so every later stage's mechanical changes can be previewed and re-run deterministically — but **never wire it into the normal build**. Load `references/openrewrite-setup.md` for the recipe IDs and exact configuration snippets.

1. Create `rewrite.yml` at the repository root declaring one composite recipe per remaining stage in the confirmed plan (Java 17, Java 25, and — only if the plan contains the Spring Boot stages — Spring Boot 2.7, Spring Boot 3.x, Spring Boot 4). Name them by purpose — `com.modernizer.migration.Java17`, `.SpringBoot27`, `.SpringBoot3`, `.Java25`, `.SpringBoot4` — not by stage number, since stage numbers differ between runs with and without the Spring Boot upgrade.
2. **Maven**: declare `org.openrewrite.maven:rewrite-maven-plugin` in `<build><plugins>` with its recipe-artifact `<dependencies>` and `<configuration><activeRecipes>` pointing at the next stage's composite recipe — with **no `<executions>` block**, so it runs only when someone explicitly invokes `mvn rewrite:dryRun` / `mvn rewrite:run`, never during `compile` or `package`.
3. **Gradle**: do NOT add the `org.openrewrite.rewrite` plugin to the `plugins {}` block — Gradle resolves plugins at configuration time, so it would affect every build. Write the standalone init script from the reference to `docs/migration/openrewrite-init.gradle` instead.
4. Write `docs/migration/openrewrite-analysis.md`: for each composite recipe, the stage it prepares, which files from that stage's File Change Manifest it is expected to touch, and the exact dry-run command. This is the automated-analysis deliverable a reviewer uses to preview each later stage before it runs.

## Output

Fold your changes into the base `java-8-to-25-modify` skill's Modify Result format. Always add a **Manual follow-ups** list (wrapper regeneration, running the OpenRewrite dry runs locally) — the pipeline compiles the project after each stage, but it does not execute OpenRewrite itself.
