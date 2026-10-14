# Test coverage — `fix-tests` step

_Repairs the new tests of the previous attempt when the pipeline's check reported compile errors, failing new tests, flaky tests or weak tests._

Part of the `test-coverage` skill: read its SKILL.md for the rules every step follows.

**Knowledge for this step**: `references/quality-rules.md` always; `junit4.md` / `junit5.md`, `mockito.md` and the stack-specific files for the error at hand.

You are the TESTER again. The pipeline ran the build and checked the new tests; its report is in your query. Fix what it reported, nothing else.

## What the query gives you

The check report: compile errors (file, line, message), failing new tests (class, method, assertion/exception and stack excerpt), flaky tests (passed and failed across repeated runs), weak tests (no assertion, trivial assertion, disabled), the list of new test files from this run, the test-stack facts, and the `step_id`.

## How to work

1. **Only new test files are editable** — the ones created in this run. Never change production code, a `pom.xml`, or an existing (pre-run) test; a refusal from the workspace tool (`ERROR:`) is final.
2. For each reported item, `read_file` the CURRENT test (an earlier fix may have changed it) and the production code it exercises.
3. **Compile errors**: wrong imports, wrong method signatures, missing checked exception handling, a library that is not in the test stack (use what the repository has instead — never add a dependency), mismatched generics, `UnnecessaryStubbingException`-style strictness problems (see `mockito.md`).
4. **Failing test**: first establish what the production code actually does by reading it. If the test's expectation, setup or mock stubbing was wrong, fix the test. Do not "fix" it by loosening the assertion until it passes, by catching the failure, or by asserting something the code merely happens to return for the wrong reason.
5. **Real production bug**: if the code contradicts its clear contract (name, Javadoc, callers), do NOT fix it. If a test documenting the correct behaviour passes, keep it. Otherwise delete that one new test and list it under `PRODUCTION-ISSUE:` with the evidence (file, line, expected vs. actual).
6. **Flaky test**: remove the cause — time, randomness, ordering, shared static state, real I/O, threads. Inject or seed, reset state in setup, use a temp directory. If you cannot make it stable, delete it.
7. **Weak test**: add the missing meaningful assertion (value, state, `verify`, `assertThrows`) or delete the test. Never replace it with `assertTrue(true)` or `assertNotNull` on something that cannot be null.
8. A new test you cannot make pass or stable is **deleted**, never `@Ignore`d / `@Disabled`.
9. Verify: `mvn -q -B -DskipTests=false test -Dtest=<NewTestClass>` for each class you touched, until it compiles and passes. The pipeline re-measures; do not report coverage.

## Output (`save_output`, using the query's `step_id`)

```markdown
## Fixed
- src/test/java/com/acme/order/OrderServiceBranchTest.java — shouldRejectNegativeAmount: expected IllegalStateException, code throws IllegalArgumentException (OrderService.java:48); expectation corrected

## Deleted
- src/test/java/com/acme/util/ClockHelperTest.java#formatsCurrentDate — depended on the system clock and the class has no injection point

## PRODUCTION-ISSUE:
PRODUCTION-ISSUE: com.acme.order.Pricing#round — returns 10.99 for 10.995 although the Javadoc says round half up (Pricing.java:31); test deleted
```

Use the exact `PRODUCTION-ISSUE: ` prefix, one issue per line; write `none` under a section that has no entries.
