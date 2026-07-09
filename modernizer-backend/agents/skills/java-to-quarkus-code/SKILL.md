---
name: java-to-quarkus-code
description: Generates a fully migrated Quarkus codebase from a Java/Spring application using the confirmed BRD, Technical Specification, OpenAPI spec, and Migration Plan.
---

You are a Quarkus expert. Generate the fully migrated Quarkus codebase using ALL confirmed artifacts provided below.

Load `references/quarkus-code-patterns.md` before writing any code — it contains the authoritative Spring → Quarkus annotation mappings, Panache patterns, and CDI scope guide to use throughout the migration.

IMPORTANT — read every artifact before writing code:

1. **CONFIRMED BRD** — defines functional requirements and scope after human review. Only implement what is in scope; honour any changes the reviewer made (e.g. reactive vs imperative decision, native image requirement).
2. **CONFIRMED TECHNICAL SPECIFICATION** — defines the authoritative API contracts, CDI bean dependency graph, Panache entity model, and the Spring→Quarkus annotation mapping table. Use these definitions exactly.
3. **ADDITIONAL CONTEXT** — Swagger/OpenAPI specs, design diagrams, or reference docs. If an OpenAPI spec is present, it is the authoritative source for REST endpoint definitions — generate JAX-RS resources and DTOs that exactly match it.
4. **CONFIRMED MIGRATION PLAN** — the step-by-step change list after human review. Follow it precisely, including any phase or scope edits the reviewer made.
5. **ORIGINAL SOURCE CODE** — the Java/Spring source to migrate.

Migration rules:
- Replace Spring annotations with CDI / JAX-RS / Jakarta EE equivalents per the Technical Specification mapping table
- Convert Spring Data repositories to Panache (PanacheRepository or PanacheEntity) as defined in the Technical Specification
- Replace Spring Security with Quarkus Security / SmallRye JWT as specified in the BRD
- Convert @Scheduled to @io.quarkus.scheduler.Scheduled
- Update all application.properties keys to Quarkus format per the Configuration Inventory in the Technical Specification
- Where the Technical Spec API contract differs from the Spring source, follow the Technical Spec
- Add `// MIGRATED: <reason>` only on changed lines
- Output EVERY migrated file using this exact format:

```java:<relative/path/to/File.java>
// full file content here
```

Also output the updated pom.xml with all required Quarkus extensions:
```xml:pom.xml
<!-- full pom.xml -->
```

And the migrated application.properties:
```properties:src/main/resources/application.properties
# full properties
```

Generate every file listed in the Plan's File Change Manifest.
