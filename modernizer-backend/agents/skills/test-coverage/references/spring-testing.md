# Spring components
<!-- applies-to: spring -->

Prefer plain unit tests with Mockito over Spring contexts: they are fast, deterministic and give exact branch control. A Spring context test starts the container, is slow and covers little per second.

## Service / component

```java
@ExtendWith(MockitoExtension.class)            // JUnit 4: @RunWith(MockitoJUnitRunner.class)
class InvoiceServiceTest {
    @Mock InvoiceRepository repo;
    @Mock TaxClient tax;
    @InjectMocks InvoiceService service;

    @Test
    void appliesTaxFromClient() {
        when(tax.rateFor("DE")).thenReturn(new BigDecimal("0.19"));
        Invoice i = service.create("DE", new BigDecimal("100"));
        assertEquals(new BigDecimal("119.00"), i.getTotal());
        verify(repo).save(i);
    }
}
```

Constructor injection: build the object yourself (`new InvoiceService(repo, tax)`) — clearest, no `@InjectMocks` surprises. Field injection with `@Autowired` private fields: `@InjectMocks` handles it, or use `ReflectionTestUtils.setField` ONLY if spring-test is present and the other options fail.

## Controllers without a context

Call the handler method directly and assert its return value (view name, `ResponseEntity`, model contents):

```java
Model model = new ExtendedModelMap();
assertEquals("orders/list", controller.list(model));
assertEquals(2, ((List<?>) model.asMap().get("orders")).size());

ResponseEntity<Order> r = controller.get(99L);
assertEquals(HttpStatus.NOT_FOUND, r.getStatusCode());
```

Test the branches: found/not found, validation failure (`BindingResult` mock with `hasErrors()` true), exceptions mapped by the controller. Bean-validation annotations and mapping annotations are not exercised by direct calls — that is fine for unit coverage.

## Slices — only if already present

`@WebMvcTest` + `MockMvc`, `@DataJpaTest`, `@JsonTest` are used ONLY when the existing tests already use them (spring-boot-starter-test is in the stack and a sample test shows the pattern). With MockMvc:

```java
mvc.perform(get("/orders/1")).andExpect(status().isOk()).andExpect(jsonPath("$.id").value(1));
```

with `@MockBean` for collaborators (Spring Boot 3.4+: `@MockitoBean`). `@SpringBootTest` is a last resort: never use it for new tests when a unit test can reach the same lines.

## Configuration, aspects, config properties

- `@Configuration` classes: calling the `@Bean` methods directly is a hollow test unless they contain logic; test the logic (conditional wiring, defaults) and assert the produced object's configuration.
- `@ConfigurationProperties` classes: test getters only if they contain logic; test validation/derived values.
- Event listeners (`@EventListener`): call the method with an event and verify the effect.
- `@Scheduled` methods: call directly; the schedule itself is not tested.
- `@Async`/`@Transactional` proxies are not applied when you call the object directly; that is expected.

## Pitfalls

- Never `Thread.sleep` for async code; if the class needs an executor, inject a direct one.
- `Environment`/`@Value` fields: pass values through the constructor or `ReflectionTestUtils` if present; otherwise it is `UNTESTABLE` only if the value cannot be supplied at all.
- Do not load the real `application.properties` contexts; put test-only files under `src/test/resources` when needed.
