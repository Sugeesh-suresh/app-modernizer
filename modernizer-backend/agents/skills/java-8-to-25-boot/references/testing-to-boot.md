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
- **Which tests change.** A Spring test that loads an XML context (`@ContextConfiguration("classpath:….xml")`) must change whatever the options say, because the XML context is going away: convert it to `@SpringBootTest` or a slice (`@JdbcTest`, `@WebMvcTest`, …) on Jupiter. A JUnit 4 Spring test that uses annotation configuration, and a plain JUnit 4 test with no Spring (Mockito only), may stay on JUnit 4 while the JUnit upgrade is off: a Spring one on `@RunWith(SpringRunner.class)` is a deprecation (B012, a warning) listed in the report, not an error; never downgrade Spring or JUnit to silence it. With the JUnit upgrade, convert them all (`@SpringBootTest`, `@ExtendWith`, Jupiter assertions).
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
- The validation builds with the command in the validator's `## Build command` section: with `VALIDATE_RUN_TESTS` on (the default) it runs the suite, so a converted test that fails fails the stage; with it off, only compilation is checked and a runtime failure is a human follow-up the report names.


## Boot 4 package and starter names (found by building)

- Slice test starters are modular: `spring-boot-starter-webmvc-test`, `spring-boot-starter-jdbc-test`, … next to `spring-boot-starter-test`.
- `org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest`, `org.springframework.boot.jdbc.test.autoconfigure.JdbcTest`, `org.springframework.test.context.bean.override.mockito.MockitoBean`.
- A repository with JUnit 4 tests may keep them next to Jupiter ones through `junit-vintage-engine` (version managed by the BOM) while the JUnit upgrade is off — see "Which tests change" above for the ones that must convert anyway.
