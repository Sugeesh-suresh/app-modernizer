---
name: test-coverage
description: >
  Raises unit-test coverage of an uploaded Maven repository using the test frameworks it already has.
  The pipeline measures coverage with JaCoCo; the agents only write new tests under src/test — never
  production code, never existing tests, never a new dependency. One step file per role: write the tests
  for a batch of classes, repair the tests of the previous attempt.
---

# Test coverage (Maven, existing test stack)

Raise line and branch coverage of a Maven repository by adding **new unit tests**. The pipeline builds the project, measures coverage with JaCoCo, picks the classes that fall short of the target, hands them to testers in batches, re-measures, and repeats until the target is met or the rounds run out. You never measure and never report a coverage number: the number is the pipeline's.

## Workflow

| # | Step | Step file | What it does |
|---|---|---|---|
| 1 | `write-tests` | `references/steps/write-tests.md` | The tester writes new test classes for a batch of production classes |
| 2 | `fix-tests` | `references/steps/fix-tests.md` | Repairs the new tests of the previous attempt when the pipeline's check reports compile errors, failures, flaky or weak tests |

The pipeline's own steps (baseline measurement, the `coverage-target` gate, re-measurement, the `coverage-stalled` gate, the report) are deterministic and are not yours. Your caller tells you which step is yours: read that step file and follow it — not the other.

## Rules for every step

These are enforced by the workspace tools where they can be (a refusal starts with `ERROR:` — read why, never work around it) and checked by the pipeline afterwards where they cannot.

1. **Write only under `src/test/java` and `src/test/resources`**, only through the workspace tools. Production code is read-only. Existing test files are frozen: never edit or delete them. Add NEW test files only. A file created in this run may be edited or deleted.
2. **Use only the test frameworks the repository already has.** The query lists them (JUnit 4 or 5, Mockito version, AssertJ / Hamcrest, Spring Test, Testcontainers, ...). Never add a dependency, never edit a `pom.xml`. If a library is not in the list, it is not available.
3. **Match the repository's test style**: naming, package layout, base classes, annotations, assertion library. The query names a sample existing test — read it first and copy its conventions. Mirror the production package under `src/test/java`.
4. **Every test method makes a meaningful assertion about behaviour**: a return value, a state change, an interaction checked with `verify`, an exception checked with `assertThrows` / `expected`. Forbidden: assertion-free tests, `assertTrue(true)`, `@Ignore` / `@Disabled`, tests that only call a method to raise coverage, tests that merely recompute the implementation's own expression. Cover branches — each `if`/`else`/`switch` arm, error paths, boundaries, null and empty inputs — not only the happy path. See `references/quality-rules.md`.
5. **Tests are deterministic and fast**: no `Thread.sleep`, no real network or database, no filesystem outside a temp directory, no dependency on test order, no clock or random without injection or a fixed seed.
6. **Untestable classes are reported, not forced.** A class that cannot be unit-tested without changing production code (static singletons, `new` of collaborators inside methods, JNDI, container-only APIs) is reported as `UNTESTABLE: <fully.qualified.Class> — <reason>` and skipped. Never refactor production code. No reflection hacks and no PowerMock unless the query says the repository already has it.
7. **Never weaken an existing test**: do not skip, disable, relax or delete it. A new test that cannot be made to pass is deleted by you, never skipped.
8. **The only build you may run** is `mvn -q -B -DskipTests=false test -Dtest=<NewTestClass>` through the run-command tool (it uses the right JDK and settings). Use it to check that your own tests compile and pass before you finish. The pipeline re-measures everything itself.
9. **JSP pages are out of scope.** JaCoCo does not instrument JSP files. Test the servlets, beans, filters and tag classes behind them.
10. **Evidence before claims.** Read the production class and its collaborators before you write a test; assert what the code does (confirmed by reading it), not what you guess it should do.

## Knowledge

Load only what the task needs (each file starts with an `applies-to` tag when it is stack-specific).

| File | Used by |
|---|---|
| `references/quality-rules.md` | every step — always |
| `references/junit4.md` | `write-tests`, `fix-tests` when the repository uses JUnit 4 |
| `references/junit5.md` | same, JUnit 5 / Jupiter |
| `references/mockito.md` | same, when Mockito is present |
| `references/servlet-jsp-testing.md` | servlets, filters, listeners, JSP-backed controllers |
| `references/data-access-testing.md` | JDBC, JdbcTemplate, Hibernate / JPA, repositories, DAOs |
| `references/spring-testing.md` | Spring components and controllers |
