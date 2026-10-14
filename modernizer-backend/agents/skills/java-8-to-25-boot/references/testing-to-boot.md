# Testing → Spring Boot test support
<!-- applies-to: junit, springrunner, contextconfiguration, springjunit4classrunner -->

Target: `spring-boot-starter-test` (test scope) with JUnit Jupiter. Test classes only change in this profile where they load a Spring context — a plain unit test is not touched (and JUnit 3/4 migration is governed by the base skill's JUnit toggle, not by this file). Scanner finding B012 (warning) is the old runner; B005 (error) is any XML context a test still loads.

## Runner and context

```java
// Before
@RunWith(SpringJUnit4ClassRunner.class)
@ContextConfiguration(locations = {"classpath:applicationContext.xml", "classpath:test-context.xml"})
@Transactional
public class OrderServiceTest { @Autowired OrderService service; @Test public void places() { … } }

// After
@SpringBootTest
@Transactional
class OrderServiceTest {
    @Autowired OrderService service;
    @Test void places() { … }          // org.junit.jupiter.api.Test
}
```
- Without the JUnit upgrade a JUnit 4 test that must keep running stays on `@RunWith(SpringRunner.class)` — a deprecation (B012) listed in the report, not an error; never downgrade Spring or JUnit to silence it. With the upgrade, use `@SpringBootTest` (the Jupiter extension is built in) and `org.junit.jupiter.api` assertions/annotations.
- `@ContextConfiguration(classes = AppConfig.class)` → `@SpringBootTest`; a test-only `@Configuration` becomes `@TestConfiguration` imported with `@Import`. XML test contexts are deleted once their beans are test configuration or properties.
- `@TestPropertySource(properties = …)`, `@ActiveProfiles("test")` stay; `src/test/resources/application-test.yml` replaces `test.properties`.
- `@WebAppConfiguration` + hand-built `MockMvc` → `@AutoConfigureMockMvc` with `@SpringBootTest`, or a slice.

## Slices, so tests stay small

| Layer | Annotation | Notes |
|---|---|---|
| Controllers | `@WebMvcTest(OrderController.class)` + `MockMvc` | loads MVC and Security only; services are `@MockitoBean` |
| JPA repositories | `@DataJpaTest` | in-memory database by default (`@AutoConfigureTestDatabase(replace = NONE)` to use the configured one); rolls back |
| JDBC | `@JdbcTest` | `JdbcTemplate` and a `DataSource` |
| JSON | `@JsonTest` | the Jackson 3 `JsonMapper` Boot configures |
| REST client | `@RestClientTest` | mocked server for a `RestClient` |
| Everything | `@SpringBootTest` (`webEnvironment = RANDOM_PORT` + `TestRestTemplate`/`RestTestClient` for end-to-end) | slowest |

Boot 4 moved the test-support annotation packages into per-technology modules: take the import the compiler/IDE reports rather than copying an old package name.

## Mocks

`@MockBean`/`@SpyBean` are gone in Spring Boot 4 — use `@MockitoBean`/`@MockitoSpyBean` (Spring Framework test support, on the field), and `Mockito` 5. Hand-built `Mockito.mock` in XML (`<bean factory-method="mock">`) → `@MockitoBean`.

```java
@WebMvcTest(OrderController.class)
class OrderControllerTest {
    @Autowired MockMvc mvc;
    @MockitoBean OrderService service;
    @Test void listsOrders() throws Exception {
        given(service.all()).willReturn(List.of());
        mvc.perform(get("/orders")).andExpect(status().isOk());
    }
}
```
With Spring Security: add `spring-security-test`; `@WithMockUser(roles = "ADMIN")`, `.with(csrf())` on state-changing requests.

## What must not happen

- No `@ContextConfiguration` pointing at a deleted XML file; no `@ImportResource` kept alive for tests.
- A test never "fixed" by `spring.main.allow-bean-definition-overriding=true` or by re-declaring an auto-configured bean in a test config — fix the production wiring.
- Do not delete or weaken a test to make a build pass; do not add tests the plan did not list.
- The validation builds with `-DskipTests`: a test that cannot compile still fails the build, but one that would fail at runtime is a human follow-up, which the report names.
