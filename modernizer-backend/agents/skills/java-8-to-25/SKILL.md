---
name: java-8-to-25
description: >
  Migrates a Java 8 application to Java 25 — bigbang or incremental by stages — and, when asked, its
  Spring application to the newest Spring Boot 4.x as an executable JAR: the
  migration plan, applying the plan (with the readiness and Spring Boot stage guides), real builds and
  repair, and the final report — one step file per pipeline step, sharing one body of Java migration
  knowledge.
---

# Java 8 → 25 (optionally Spring Boot 4)

Move a Java 8 application to Java 25. A **bigbang** run applies the whole plan in one pass; an **incremental** run applies it stage by stage (build readiness and a test safety net, then the JDK hops, then — when a Spring Boot upgrade was requested — Spring Boot 2.7, 3.x with the Jakarta rename, and 4.x), with a real build after every stage. When a Spring Boot upgrade is requested the final state is always the newest Spring Boot 4.x on Jakarta EE 11, deployed as an executable JAR. The stage guides (`readiness`, `springboot-incremental`, `springboot-boot4`) are steps of this skill that the modify and fix steps follow alongside their own when the stage calls for them.

## Workflow

The pipeline runs the steps in this order, holds every change until a person approves the plan, and runs the validate → fix loop until the validation passes or its limit is reached. Your caller tells you which step is yours: load that step file with `load_skill_resource` and follow it — not the others.

| # | Step | Step file | What it does |
|---|---|---|---|
| 1 | `plan` | `references/steps/plan.md` | The migration plan a person approves before anything changes |
| 2 | `modify` | `references/steps/modify.md` | Applies the approved plan (or one task of it) to the workspace |
| 3 | `readiness` | `references/steps/readiness.md` | Stage guide — build modernisation, test safety net and OpenRewrite (incremental runs) |
| 4 | `springboot-incremental` | `references/steps/springboot-incremental.md` | Stage guide — Spring Boot 2.7, then 3.x with the Jakarta rename (incremental runs) |
| 5 | `springboot-boot4` | `references/steps/springboot-boot4.md` | Stage guide — the Spring Boot 4.x target and the WAR to executable-JAR conversion |
| 6 | `validate` | `references/steps/validate.md` | Validates the workspace for real and reports pass/fail as JSON |
| 7 | `fix` | `references/steps/fix.md` | Repairs what the validation reported, inside the loop |
| 8 | `report` | `references/steps/report.md` | The final migration report |

Two more steps run in every migration and belong to shared skills: `code-review` (an independent review of the result against the plan) after the loop, and `skill-curator` (refines this skill from the run's evidence) at the very end.

## Rules for every step

- **Evidence before claims.** Read a file before you describe it or change it; never reconstruct a file's contents
  from memory. Cite the file (and line) for what you state.
- **Nothing changes before a person approves the plan.** The pipeline holds every write until the plan is approved;
  the plan step only reads.
- **Change only what your step is given.** The modify and fix steps apply the confirmed plan (or the one task they
  are given) and nothing else; anything more is reported, not done.
- **The validator's result is the truth.** No step reports success the validation did not show.
- **Knowledge lives in `references/`.** Each step file lists the knowledge files it needs; load them with
  `load_skill_resource` (Gemini CLI: read them from the skill's folder).

## Knowledge

| File | Used by the steps |
|---|---|
| `references/boot27-on-war.md` | `springboot-incremental` |
| `references/boot3-jakarta-transition.md` | `springboot-incremental` |
| `references/boot4-dependency-cleanup.md` | `springboot-incremental`, `springboot-boot4` |
| `references/build-modernization.md` | `readiness` |
| `references/common-build-fixes.md` | `fix` |
| `references/intermediate-war-stages.md` | `springboot-incremental` |
| `references/jakarta-ee11-namespace-map.md` | `springboot-incremental`, `springboot-boot4` |
| `references/java8-baseline-facts.md` | `plan` |
| `references/java8-to-java25-checklist.md` | `plan`, `modify`, `fix` |
| `references/jsp-to-thymeleaf.md` | `springboot-incremental`, `springboot-boot4` |
| `references/legacy-library-modernization.md` | `modify`, `fix` |
| `references/migration-patterns.md` | `modify`, `fix` |
| `references/openrewrite-setup.md` | `readiness` |
| `references/spring-data-jpa-migration.md` | `springboot-incremental`, `springboot-boot4` |
| `references/war-to-executable-jar.md` | `springboot-incremental`, `springboot-boot4` |
| `references/webxml-to-javaconfig.md` | `springboot-incremental`, `springboot-boot4` |
