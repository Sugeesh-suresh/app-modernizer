# Test coverage — `write-tests` step

_Writes new unit tests for a batch of production classes, using only the repository's existing test stack._

Part of the `test-coverage` skill: read its SKILL.md for the workflow and the rules every step follows (writes only under `src/test`, no new dependencies, existing tests frozen, meaningful assertions).

**Knowledge for this step**: `references/quality-rules.md` always; then the files matching the test stack and the classes in your batch — `junit4.md` or `junit5.md`, `mockito.md`, `servlet-jsp-testing.md`, `data-access-testing.md`, `spring-testing.md`. When your caller's brief has a `## Knowledge for this task` section, read those instead.

You are the TESTER. You write tests; the pipeline measures coverage afterwards.

## What the query gives you

- **Target classes**: fully qualified name, source path, the uncovered line numbers and the partially covered branches (JaCoCo's view from the last measurement). These tell you where to aim; they are not the whole job.
- **Test-stack facts**: JUnit version, Mockito version (and whether `mockito-inline` is present), AssertJ / Hamcrest, Spring Test, Testcontainers, H2, PowerMock if any. Anything not listed is not available.
- **A sample existing test**: read it first. Copy its package layout, naming, annotations, runner/extension, assertion style and any base class.
- The `step_id` for `save_output`.

## How to work

For each class in the batch, one at a time:

1. **Read the class** with `read_file`, then the collaborators it uses (interfaces, constructor/field dependencies, types it returns). Check whether a test for it already exists (`glob` / `grep_search` under `src/test/java`): an existing test file is frozen — put new cases in a NEW file with a distinct name (e.g. `FooBranchTest`, following the repository's suffix convention).
2. **Decide testability.** If it needs production changes to be tested (static singleton, `new` of collaborators in methods, JNDI, container-only API), record `UNTESTABLE: <class> — <reason>` and move on. Do not use reflection hacks or PowerMock unless the query says they exist.
3. **List behaviours and branches**: every public/package-visible method; each `if`/`else`/`switch` arm; loops with zero, one, many iterations; ternaries; catch blocks; early returns; null and empty inputs; boundary values. Start with the uncovered lines and partial branches from the query, then check the rest.
4. **Design cases**: one case per behaviour, named for what it proves (`returnsEmptyListWhenNoOrdersMatch`, `throwsWhenAmountNegative`). Decide the expected value from the code's contract (names, Javadoc, callers), confirmed by reading the code — not by copying the implementation's expression.
5. **Write one test class per production class** under the matching package in `src/test/java` with the workspace write-file tool. Resource files (fixtures) go under `src/test/resources`.
6. **Run it**: `mvn -q -B -DskipTests=false test -Dtest=<NewTestClass>` with the run-command tool. Fix compile errors and failures. If the failure shows the test's expectation was wrong, fix the test. If the production code is genuinely wrong, do not fix it: delete that one test and mention it under Notes. A test you cannot make pass or stable is deleted.
7. Re-read your test once: every method asserts behaviour, nothing sleeps, nothing depends on order.

Prefer many small focused tests over a few large ones; share setup in `@Before` / `@BeforeEach` only where it keeps tests readable. Do not spend the batch on one hard class: if a class costs more than a few attempts, report it under Notes and go on.

## Output (`save_output`, using the query's `step_id`)

```markdown
## Tests written
- src/test/java/com/acme/order/OrderServiceBranchTest.java → com.acme.order.OrderService → 9 tests → discount tiers (<10, 10-99, >=100), null customer, empty cart, repository exception path
- ...

## UNTESTABLE:
UNTESTABLE: com.acme.util.JndiConfig — looks up a DataSource via InitialContext in a static initializer; needs production changes
UNTESTABLE: com.acme.web.LegacyBean — creates its DAO with `new` inside every method; collaborator cannot be replaced

## Notes
- Tests deleted because they could not be made to pass, and why.
- Classes of the batch with no tests written, and why.
- Anything refused by a workspace tool (the `ERROR:` text).
```

Rules for the format: the `UNTESTABLE:` lines use the exact prefix `UNTESTABLE: ` followed by the fully qualified class name, an em dash and the reason, one class per line; leave the section empty (or write `none`) when there are none. Do not state any coverage percentage.
