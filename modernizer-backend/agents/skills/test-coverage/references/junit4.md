# JUnit 4 tests
<!-- applies-to: junit4, org.junit.test, runwith -->

Use when the repository's tests import `org.junit.Test` / `org.junit.Assert` (JUnit 4.x). Never mix in Jupiter annotations: they do not run under the JUnit 4 engine.

## Skeleton

```java
import static org.junit.Assert.*;
import org.junit.Before;
import org.junit.Test;

public class PriceCalculatorTest {
    private PriceCalculator calc;

    @Before
    public void setUp() {
        calc = new PriceCalculator(new FixedTaxPolicy(0.2));
    }

    @Test
    public void addsTaxToNetPrice() {
        assertEquals(120.0, calc.gross(100.0), 0.001);
    }

    @Test(expected = IllegalArgumentException.class)
    public void rejectsNegativePrice() {
        calc.gross(-1.0);
    }
}
```

## Annotations and runners

- `@Test`, `@Before`, `@After`, `@BeforeClass` / `@AfterClass` (static). Test classes and methods are `public`; methods return `void`.
- `@RunWith(MockitoJUnitRunner.class)` for Mockito mocks (see `mockito.md`); `@RunWith(Parameterized.class)` for table-driven cases; `@RunWith(SpringJUnit4ClassRunner.class)` only if spring-test is present.
- `@Rule TemporaryFolder tmp = new TemporaryFolder();` for files; `@Rule ExpectedException` exists in 4.11+ but prefer the options below.
- `@Ignore` is forbidden in this pipeline.

## Exceptions

JUnit 4.13+ has `assertThrows`. Use it when it is available so the message and cause can be checked:

```java
IllegalStateException e = assertThrows(IllegalStateException.class, () -> svc.close());
assertEquals("already closed", e.getMessage());
```

On 4.12 and older (no `assertThrows`), use `@Test(expected = ...)` when only the type matters, or try/catch with `fail()`:

```java
try {
    svc.close();
    fail("expected IllegalStateException");
} catch (IllegalStateException e) {
    assertEquals("already closed", e.getMessage());
}
```

`@Test(expected=...)` passes if the exception is thrown anywhere in the method, including setup lines: keep such tests to a single call.

## Assertions

- `assertEquals(expected, actual)` — expected first. Doubles/floats need a delta. Use `assertArrayEquals` for arrays.
- `assertSame` / `assertNotSame` for identity; `assertNull` / `assertNotNull`; `assertTrue(message, cond)`.
- If Hamcrest or AssertJ is in the stack list, `assertThat(...)` gives clearer failures; otherwise do not import it.

## Parameterized (several inputs, one behaviour)

```java
@RunWith(Parameterized.class)
public class GradeTest {
    @Parameterized.Parameters(name = "{0} -> {1}")
    public static Collection<Object[]> data() {
        return Arrays.asList(new Object[][] {{59, "F"}, {60, "D"}, {90, "A"}});
    }
    private final int score; private final String grade;
    public GradeTest(int score, String grade) { this.score = score; this.grade = grade; }
    @Test public void mapsScoreToGrade() { assertEquals(grade, Grade.of(score)); }
}
```

## Pitfalls

- Test instances are created per method, so fields are fresh; static fields leak between tests — avoid them or reset in `@After`.
- Do not rely on method order (`@FixMethodOrder` is for fixing legacy tests, not for new ones).
- `@Test(timeout=...)` is acceptable as a guard but never as a way to sleep.
- Surefire only runs classes matching its includes (`*Test`, `Test*`, `*Tests`, `*TestCase`): follow the repository's suffix.
