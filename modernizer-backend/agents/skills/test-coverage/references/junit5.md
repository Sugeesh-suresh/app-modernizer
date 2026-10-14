# JUnit 5 (Jupiter) tests
<!-- applies-to: junit5, jupiter, extendwith -->

Use when tests import `org.junit.jupiter.api.*`. Do not use `org.junit.Test` or `@RunWith` there: the Jupiter engine ignores them (unless the vintage engine is present, which the query would say).

## Skeleton

```java
import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class PriceCalculatorTest {
    private PriceCalculator calc;

    @BeforeEach
    void setUp() {
        calc = new PriceCalculator(new FixedTaxPolicy(0.2));
    }

    @Test
    void addsTaxToNetPrice() {
        assertEquals(120.0, calc.gross(100.0), 0.001);
    }

    @Test
    void rejectsNegativePrice() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class, () -> calc.gross(-1.0));
        assertTrue(e.getMessage().contains("negative"));
    }
}
```

Test classes and methods may be package-private; follow the visibility the existing tests use.

## Lifecycle and extensions

- `@BeforeEach`, `@AfterEach`, `@BeforeAll` / `@AfterAll` (static unless `@TestInstance(PER_CLASS)`).
- `@ExtendWith(MockitoExtension.class)` for Mockito (see `mockito.md`); `@ExtendWith(SpringExtension.class)` only if spring-test is present.
- `@TempDir Path dir;` for files.
- `@Disabled` is forbidden in this pipeline.

## Parameterized tests (only if `junit-jupiter-params` is a dependency)

```java
@ParameterizedTest(name = "{0} -> {1}")
@CsvSource({"59,F", "60,D", "90,A"})
void mapsScoreToGrade(int score, String grade) {
    assertEquals(grade, Grade.of(score));
}
```

`@MethodSource("cases")` for objects; `@NullAndEmptySource` / `@ValueSource` for null/empty/blank strings. If params is not in the dependency list, write separate tests or loop with `assertAll`.

## Assertions

- `assertEquals(expected, actual)`, `assertSame`, `assertNull`, `assertIterableEquals`, `assertArrayEquals`; the message is the LAST argument.
- `assertAll("order", () -> assertEquals(..), () -> assertEquals(..))` to report every failed field together.
- `assertThrows` returns the exception: check message/cause. `assertDoesNotThrow` alone is a hollow assertion unless the point is "does not throw for this boundary input" — then also assert the result.
- `assertTimeout` is allowed as a guard; never sleep.
- If AssertJ is present, `assertThat(list).containsExactly(...)` reads better; otherwise do not import it.

## Nested and display names

```java
@Nested
class WhenCartIsEmpty {
    @Test void totalIsZero() { assertEquals(0, new Cart().total()); }
}
```

Use `@Nested` only if the repository's tests do. `@DisplayName` is optional.

## Pitfalls

- A method annotated with `@Test` from the wrong package silently does not run — check imports.
- Default lifecycle is per-method instance; keep it that way, no shared mutable state.
- `@Order` / `MethodOrderer` must not be needed for correctness.
- Surefire needs 2.22+ for JUnit 5; if existing Jupiter tests run, yours will.
