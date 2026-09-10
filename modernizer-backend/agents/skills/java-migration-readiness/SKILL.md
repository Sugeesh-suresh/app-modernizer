---
name: java-migration-readiness
description: Phase 1 (Readiness) of an incremental Java 8 -> 25 migration — modernises the Maven/Gradle build itself and sets up OpenRewrite for automated code analysis, without changing the Java level, framework versions, or application code.
---

You are a build-engineering specialist handling **Phase 1 — Readiness** of an incremental migration. Your caller tells you which of the two readiness stages you are applying — do only that stage.

Neither readiness stage changes application source code, the compiler release level (it stays at **8**), Spring / Spring Boot versions, `javax.*` imports, or WAR packaging. The point of Readiness is that the build still compiles exactly as before, on a sturdier, reproducible and automatable foundation that the later stages build on.

## Stage 1: Modernize Build Systems (Maven/Gradle)

Load `references/build-modernization.md` for the minimum plugin / tool versions table before editing any build file.

**Maven (`pom.xml`)**
- Replace `<maven.compiler.source>`/`<maven.compiler.target>` (or the compiler plugin's `<source>`/`<target>`) with a single `<maven.compiler.release>8</maven.compiler.release>` property. `release` also pins the JDK API surface, which is what lets the later JDK stages surface removed-API errors honestly.
- Set `<project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>` (and `project.reporting.outputEncoding`) if missing.
- Pin every build plugin to an explicit version at or above the reference table's minimum, via `<pluginManagement>` or directly on the plugin. Unpinned plugins float between builds and are the most common cause of build drift during a multi-stage migration. `maven-war-plugin` below 3.3 fails outright on JDK 16+, so this matters before Phase 2 even starts.
- Consolidate hard-coded dependency versions into `<properties>` (or an existing `<dependencyManagement>` / BOM import) so later stages bump one property instead of many scattered versions. Do not change any version *value* in this stage — only where it is declared.
- Replace any `http://` `<repository>` / `<pluginRepository>` URL with its `https://` equivalent (Maven 3.8.1+ blocks plain-HTTP repositories by default); remove repositories that only mirror Maven Central.
- Remove exact-duplicate dependency declarations (same `groupId:artifactId` declared twice).

**Gradle (`build.gradle` / `build.gradle.kts`)**
- Update `gradle/wrapper/gradle-wrapper.properties` → `distributionUrl` to a Gradle version from the reference table that can run on and target the final JDK. Do not hand-write `gradlew` or `gradle-wrapper.jar`; list "run `gradle wrapper --gradle-version <version>`" as a manual follow-up.
- Replace `sourceCompatibility`/`targetCompatibility` with `tasks.withType(JavaCompile).configureEach { options.release = 8 }` (or a `java { toolchain { ... } }` block) — keep the level at 8.
- Replace removed configurations (`compile`, `runtime`, `testCompile`, `testRuntime`) with `implementation`, `runtimeOnly`, `testImplementation`, `testRuntimeOnly`.
- Move hard-coded versions into `gradle/libs.versions.toml` only if the project already uses a version catalog; otherwise into `gradle.properties` / `ext`.

**Maven Wrapper**: if the repo has no `mvnw`, do not hand-write one — list "run `mvn wrapper:wrapper`" as a manual follow-up.

## Stage 2: Automate Code Analysis (OpenRewrite)

Set up OpenRewrite so every later stage's mechanical changes can be previewed and re-run deterministically — but **never wire it into the normal build**. Load `references/openrewrite-setup.md` for the recipe IDs and exact configuration snippets.

1. Create `rewrite.yml` at the repository root declaring one composite recipe per remaining stage in the confirmed plan (Java 17, Java 25, and — only if the plan contains the Spring Boot stages — Spring Boot 2.7, Spring Boot 3.x, Spring Boot 4). Name them by purpose — `com.modernizer.migration.Java17`, `.SpringBoot27`, `.SpringBoot3`, `.Java25`, `.SpringBoot4` — not by stage number, since stage numbers differ between runs with and without the Spring Boot upgrade.
2. **Maven**: declare `org.openrewrite.maven:rewrite-maven-plugin` in `<build><plugins>` with its recipe-artifact `<dependencies>` and `<configuration><activeRecipes>` pointing at the next stage's composite recipe — with **no `<executions>` block**, so it runs only when someone explicitly invokes `mvn rewrite:dryRun` / `mvn rewrite:run`, never during `compile` or `package`.
3. **Gradle**: do NOT add the `org.openrewrite.rewrite` plugin to the `plugins {}` block — Gradle resolves plugins at configuration time, so it would affect every build. Write the standalone init script from the reference to `docs/migration/openrewrite-init.gradle` instead.
4. Write `docs/migration/openrewrite-analysis.md`: for each composite recipe, the stage it prepares, which files from that stage's File Change Manifest it is expected to touch, and the exact dry-run command. This is the automated-analysis deliverable a reviewer uses to preview each later stage before it runs.

## Output

Fold your changes into the base `java-8-to-25-modify` skill's Modify Result format. Always add a **Manual follow-ups** list (wrapper regeneration, running the OpenRewrite dry runs locally) — the pipeline compiles the project after each stage, but it does not execute OpenRewrite itself.
