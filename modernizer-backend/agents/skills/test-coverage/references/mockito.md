# Mockito
<!-- applies-to: mockito -->

Check the Mockito version in the query first; it decides the API.

## Versions

| Version | Runner / extension | Notes |
|---|---|---|
| 1.x (`org.mockito.Matchers`, `mockito-all`) | `@RunWith(MockitoJUnitRunner.class)` | lenient; `anyString()` matches null; no `Mockito.lenient()` |
| 2.x – 4.x (`mockito-core`) | JUnit 4: `MockitoJUnitRunner` (strict by default since 2.x); JUnit 5: `@ExtendWith(MockitoExtension.class)` (needs `mockito-junit-jupiter`) | `anyString()` no longer matches null; `Matchers` deprecated → `ArgumentMatchers` |
| 5.x | same | inline mock maker is the default: final classes, final methods and (with `mockStatic`) static methods can be mocked |

Mocking `final` classes/methods or statics is allowed ONLY if the repository has `mockito-inline` or Mockito 5. Otherwise the class is `UNTESTABLE` or tested through a different seam.

## Basic use

```java
@RunWith(MockitoJUnitRunner.class)            // JUnit 5: @ExtendWith(MockitoExtension.class)
public class OrderServiceTest {
    @Mock private OrderRepository repo;
    @Mock private Notifier notifier;
    @InjectMocks private OrderService service;

    @Test
    public void savesAndNotifiesOnPlace() {
        when(repo.save(any(Order.class))).thenAnswer(i -> i.getArgument(0));
        Order placed = service.place(new Order("A1", 3));
        assertEquals("A1", placed.getSku());
        verify(notifier).sent(placed);
        verifyNoMoreInteractions(notifier);
    }
}
```

Without a runner/extension: `Mockito.mock(X.class)` and construct the class under test by hand — often the clearest choice.

## Stubbing

- `when(m.f()).thenReturn(a)`, `.thenThrow(new X())`, `.thenReturn(a, b)` for consecutive calls, `thenAnswer` to compute from arguments.
- `void` methods: `doThrow(new X()).when(m).f()`, `doNothing()`, `doAnswer(...)`.
- Spies: `doReturn(v).when(spy).f()` (not `when(spy.f())`, which calls the real method).
- Matchers: once one argument uses a matcher, all must (`eq(1)`, `anyString()`, `isNull()`).

## Strict stubs

Mockito 2+ runners/extensions fail with `UnnecessaryStubbingException` for a stub the test never used. Fix by removing the stub, not by silencing: `lenient()` / `Strictness.LENIENT` only for a stub in shared `@Before` that some tests legitimately skip. `PotentialStubbingProblem` (arg mismatch with strict stubs, Mockito 3+) means the code called the stub with different arguments — read the code and fix the stub.

## @InjectMocks pitfalls

- Tries constructor injection (biggest constructor), then setter, then field; silently leaves a dependency `null` when types do not match. If the object under test misbehaves with NPE, construct it explicitly.
- Two mocks of the same type are matched by field name.
- It does not inject into constructors that need primitives/final config; build the object yourself.
- Never put `@InjectMocks` on an interface or on a spy you expect to be real.

## Verify and capture

```java
verify(repo).save(order);                       // exactly once
verify(repo, times(2)).find(anyLong());
verify(repo, never()).delete(any());
verify(repo, atLeastOnce()).find(1L);
InOrder in = inOrder(repo, notifier);           // only when order is behaviour
in.verify(repo).save(order); in.verify(notifier).sent(order);

ArgumentCaptor<Order> cap = ArgumentCaptor.forClass(Order.class);
verify(repo).save(cap.capture());
assertEquals("PENDING", cap.getValue().getStatus());
```

Verify the interactions that ARE the behaviour (a message sent, a row saved); do not verify every getter call. Do not `verify` a stub you already asserted through the return value.

## Static and constructor mocking (Mockito 5 or mockito-inline only)

```java
try (MockedStatic<Ids> ids = Mockito.mockStatic(Ids.class)) {
    ids.when(Ids::next).thenReturn(7L);
    assertEquals(7L, service.create().getId());
}
```

Always in try-with-resources; the mock is thread-local and must be closed.
