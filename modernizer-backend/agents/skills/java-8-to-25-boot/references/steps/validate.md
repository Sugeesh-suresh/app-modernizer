# Java 8 → 25 + Spring Boot 4 (executable JAR) — `validate` supplement

_What the validator checks beyond the base build: the executable JAR is produced and starts, and the pipeline's Boot conformance report is clean of errors._

Supplement to the `java-8-to-25` skill's `references/steps/validate.md` — follow both, including its final-response rule: your entire final response is the one JSON object. Part of the `java-8-to-25-boot` skill: read its SKILL.md for the end state.

**Knowledge for this step** (load with `load_skill_resource`): `references/boot-conformance-rules.md`.

## What to run, in addition

1. **`package`, not `test-compile`.** Run `mvn -q -DskipTests clean package` (or `./mvnw …`; `gradle clean bootJar` / `./gradlew clean bootJar`). The goal must repackage: a missing `repackage` execution fails here, not at startup. In an incremental run, the stages that are still WARs build their WAR; only the final stage owes the JAR.
2. **The artifact exists.** After a successful final-stage `package`, `list_files` (or the command's output) must show `target/<name>.jar` — a Boot executable JAR, not a `.war` and not only `<name>.jar.original`. A `.war` in `target/` means packaging is still `war`: that is a failure.
3. **Smoke check where possible.** If the tool environment can run it and a database or broker is not needed to start, run `java -jar target/<name>.jar` with a bounded timeout, and look for `Started <Application> in … seconds`, then stop it. Treat the following as a failed validation: `APPLICATION FAILED TO START`, `NoSuchBeanDefinitionException`, `UnsatisfiedDependencyException`, `BeanDefinitionOverrideException`, `ClassNotFoundException`/`NoClassDefFoundError`, `Unable to start web server`, a missing `WEB-INF` descriptor. If startup needs an unavailable external resource (a database, a broker) and nothing else is wrong, do **not** fail the validation: say in `summary` that the smoke check could not run and why — never claim it passed.
4. **Read the conformance report.** The pipeline scans the workspace and gives you the Boot conformance report — findings with codes B001–B013 (and W101). Do not recompute it; do not argue with it. The rules are in `references/boot-conformance-rules.md`.

## How findings become errors

- Every **error-level** finding (B001–B011) fails the validation: set `passed` to `false` and add one entry to `errors` per finding, prefixed `BOOT:` and starting with the code — `"BOOT: B005 — src/main/resources/applicationContext.xml: Spring XML bean file still present"`. Keep the path and the scanner's message, so the fixer can act on it.
- **Warning-level** findings (B012, B013, W101) do not fail the validation. Mention the count in `summary` ("3 warnings: B012 ×2, W101 ×1").
- A clean build with an error-level finding is **not** a pass. Never call `signal_build_success` while one is reported.
- An incremental run applies the scan to the final stage only, as the pipeline decides; an earlier stage is judged on its own build and on the guardrail the caller states.
- Build errors and `BOOT:` errors go in the same `errors` array; order build errors first.

## Example final response

```
{"passed": false, "errors": ["BOOT: B006 — pom.xml: explicit org.springframework:spring-webmvc; use spring-boot-starter-webmvc", "BOOT: B009 — src/main/java/com/acme/config/WebConfig.java:14: @EnableWebMvc"], "summary": "package succeeded and target/orders.jar exists, but 2 Boot conformance errors remain (B006, B009); 1 warning (W101)."}
```
