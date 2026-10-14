# What makes a unit test meaningful

A test is meaningful if it would FAIL when the behaviour it names breaks. Coverage is only a side effect.

## Hollow tests (never write)

- No assertion, or only `assertNotNull(new Foo())`, `assertTrue(true)`.
- Calling a method and asserting only that it did not throw, when it returns a value or changes state.
- Re-implementing the production expression in the test (`assertEquals(a * rate + b, calc.total(a, b))`): it passes for any bug the test copied. Use concrete, independently computed values (`assertEquals(120.0, calc.gross(100.0), 0.001)`).
- Asserting on a mock you just stubbed (`when(m.f()).thenReturn(1); assertEquals(1, m.f())`).
- Verifying only that a getter/setter round-trips, on classes with no logic. Allowed only when the accessor contains logic (defensive copy, null → default).
- `@Ignore` / `@Disabled`, empty bodies, commented-out assertions, `catch (Exception e) {}` around the call.
- Over-specified tests: `verifyNoMoreInteractions` on every mock, exact SQL whitespace, asserting private details — they break on harmless refactors.

## Branch-coverage checklist (per method)

- Each `if` / `else if` / `else`: one case that takes it, one that does not.
- `switch`: every `case`, `default`, fall-through.
- `&&` / `||`: each operand decides the outcome at least once (short-circuit).
- Ternaries and `Optional` (`present` / `empty`).
- Loops: zero, one, many iterations; `break` / `continue` paths.
- `try` / `catch` / `finally`: the exception path, with the observable result (rethrown type, wrapped cause, logged-and-default).
- Early returns and guard clauses.
- Inputs: `null`, empty string / collection / array, blank, single element, duplicates.
- Boundaries: `0`, `1`, `-1`, `MAX`, just below / on / just above each threshold in a comparison (`x < 10` → 9, 10, 11).
- Equality / hashCode / compareTo: equal, unequal, null, other type, same instance, consistent hash.
- Enums with switch: one case per constant.

## Exceptions

```java
IllegalArgumentException e = assertThrows(IllegalArgumentException.class, () -> svc.withdraw(-5));
assertEquals("amount must be positive", e.getMessage());   // assert type AND something specific
```

Also assert that state did not change after a failure (`assertEquals(100, account.balance())`).

## Structure and naming

- Arrange / Act / Assert, separated by blank lines; one behaviour per test; one reason to fail.
- Name by behaviour: `returnsZeroForEmptyCart`, `throwsWhenUserUnknown`, `redirectsToLoginWhenNotAuthenticated`. Not `test1`, not `testGetName`.
- Follow the repository's convention (`should...`, `given_when_then`, `test...`) if the sample test has one.
- Minimal setup; a helper method or builder for repeated object creation; no logic (loops, ifs) in tests.
- Assert expected values from the contract (names, Javadoc, callers), after reading the code — not from running it and pasting the output.

## Determinism

- No `Thread.sleep`, no waiting on real time. Inject a `Clock` / supplier, or pass the timestamp.
- Random: inject a seeded `Random` or assert properties (range, length), not values.
- No real network, database, or environment variables; files only in a temp dir (`TemporaryFolder` / `@TempDir`), cleaned up.
- No order dependence, no shared mutable statics; restore any static or system property you change (`System.setProperty` → reset in `@After`).
- Default `Locale`, `TimeZone`, line separator and charset can differ between machines: set or avoid them (`String.format(Locale.ROOT, ...)`, explicit `UTC`).
- Unordered collections (`HashSet`, `HashMap` iteration): compare as sets/maps, or sort first.
- Threads: avoid; if the class is concurrent by design, use a latch with a timeout, never a sleep.

## Fast

A unit test finishes in milliseconds. No Spring contexts unless the existing tests already use them and nothing lighter reaches the lines.

## Before you finish

For each new test class: it compiles and passes with `mvn -q -B -DskipTests=false test -Dtest=<Class>`; every method has a behavioural assertion; the branches you listed are each covered by a named test; nothing in it is skipped or disabled.
