# OpenRewrite Setup (Automate Code Analysis stage)

OpenRewrite is set up here as an **analysis and preview tool** for the stages
that follow. The migration agents still make the actual changes stage by stage;
OpenRewrite lets a human preview (`dryRun`) or reproduce each stage's
mechanical changes deterministically.

## Recipes per stage (in run order)

| Stage | Composite recipe | Upstream recipe(s) | Recipe artifact |
|---|---|---|---|
| Java 8 → Java 17 LTS | `com.modernizer.migration.Java17` | `org.openrewrite.java.migrate.UpgradeToJava17` | `org.openrewrite.recipe:rewrite-migrate-java` |
| Upgrade to Spring Boot 2.7 | `com.modernizer.migration.SpringBoot27` | `org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7` | `org.openrewrite.recipe:rewrite-spring` |
| Upgrade to Spring Boot 3.x | `com.modernizer.migration.SpringBoot3` | `org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_5` (includes the javax → jakarta migration) | `org.openrewrite.recipe:rewrite-spring` |
| Java 17 → Java 25 LTS | `com.modernizer.migration.Java25` | `org.openrewrite.java.migrate.UpgradeToJava25` (use `UpgradeToJava21` if the pinned `rewrite-migrate-java` version doesn't ship the 25 recipe yet) | `org.openrewrite.recipe:rewrite-migrate-java` |
| Upgrade to Spring Boot 4.x | `com.modernizer.migration.SpringBoot4` | The Spring Boot 4.0 upgrade recipe from `rewrite-spring`, if the pinned version ships one — otherwise leave the composite with a comment saying it's agent-driven only | `org.openrewrite.recipe:rewrite-spring` |
| Convert WAR → Executable JAR | *(none)* | No upstream recipe covers the packaging change — document it as agent-driven | — |

Only declare the Spring Boot composites if the confirmed plan contains the Spring Boot stages.

Upstream `UpgradeSpringBoot_*` recipes may also bump the Java version. That's fine for a preview, but note it in the analysis document: in this pipeline the Java version only ever changes in the JDK stages.

**Never** include recipes that reformat unrelated code (e.g. `org.openrewrite.java.format.*`, `org.openrewrite.staticanalysis.*` cleanup recipes) — they create diff noise that buries the real migration changes.

## `rewrite.yml` (repository root)

```yaml
---
type: specs.openrewrite.org/v1beta/recipe
name: com.modernizer.migration.Java17
displayName: "Java 8 → Java 17 LTS"
recipeList:
  - org.openrewrite.java.migrate.UpgradeToJava17
---
type: specs.openrewrite.org/v1beta/recipe
name: com.modernizer.migration.Java25
displayName: "Java 17 → Java 25 LTS"
recipeList:
  - org.openrewrite.java.migrate.UpgradeToJava25
```

Add one more document per Spring Boot stage in the same shape, if the plan includes them.

## Maven — declared, but never bound to the lifecycle

```xml
<properties>
  <rewrite-maven-plugin.version><!-- current 6.x release --></rewrite-maven-plugin.version>
  <rewrite-migrate-java.version><!-- current release --></rewrite-migrate-java.version>
  <rewrite-spring.version><!-- current release; only if Spring Boot stages are planned --></rewrite-spring.version>
</properties>

<plugin>
  <groupId>org.openrewrite.maven</groupId>
  <artifactId>rewrite-maven-plugin</artifactId>
  <version>${rewrite-maven-plugin.version}</version>
  <configuration>
    <activeRecipes>
      <recipe>com.modernizer.migration.Java17</recipe>
    </activeRecipes>
  </configuration>
  <dependencies>
    <dependency>
      <groupId>org.openrewrite.recipe</groupId>
      <artifactId>rewrite-migrate-java</artifactId>
      <version>${rewrite-migrate-java.version}</version>
    </dependency>
  </dependencies>
  <!-- Intentionally no <executions>: runs only via `mvn rewrite:dryRun` / `mvn rewrite:run`. -->
</plugin>
```

Fill the version properties with real released versions you are confident exist. If you are not certain, still declare the properties and list "verify OpenRewrite plugin/recipe versions" under manual follow-ups. Because the plugin has no executions, a wrong version cannot break `compile` or `package`, but it would break the dry-run command.

Preview any stage: `mvn rewrite:dryRun -Drewrite.activeRecipes=com.modernizer.migration.Java25` → writes `target/rewrite/rewrite.patch`.

## Gradle — standalone init script, never applied by the build

Write this to `docs/migration/openrewrite-init.gradle` (not `build.gradle`):

```groovy
initscript {
    repositories { maven { url "https://plugins.gradle.org/m2" } }
    dependencies { classpath("org.openrewrite:plugin:latest.release") }
}
rootProject {
    plugins.apply(org.openrewrite.gradle.RewritePlugin)
    dependencies {
        rewrite("org.openrewrite.recipe:rewrite-migrate-java:latest.release")
    }
    rewrite {
        activeRecipe("com.modernizer.migration.Java17")
    }
    afterEvaluate {
        if (repositories.isEmpty()) { repositories { mavenCentral() } }
    }
}
```

Preview: `./gradlew --init-script docs/migration/openrewrite-init.gradle rewriteDryRun`.

## `docs/migration/openrewrite-analysis.md`

One section per composite recipe:
- **Stage / goal** — the plan stage it prepares.
- **Expected touch points** — files from that stage's File Change Manifest the recipe will likely modify.
- **Preview command** — the exact Maven or Gradle dry-run command above.
- **Not covered by OpenRewrite** — anything in that stage's manifest the recipe won't do (e.g. `web.xml` translation, WAR → JAR), which the stage's agent handles directly.
