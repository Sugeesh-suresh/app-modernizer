# Spring → Quarkus Mapping Reference

## Annotation Equivalents

| Spring | Quarkus / CDI / Jakarta EE |
|---|---|
| `@Component` | `@ApplicationScoped` |
| `@Service` | `@ApplicationScoped` |
| `@Repository` | `@ApplicationScoped` (use Panache) |
| `@Controller` / `@RestController` | `@Path` (JAX-RS) |
| `@RequestMapping` | `@Path` |
| `@GetMapping` | `@GET` + `@Path` |
| `@PostMapping` | `@POST` + `@Path` |
| `@PutMapping` | `@PUT` + `@Path` |
| `@DeleteMapping` | `@DELETE` + `@Path` |
| `@PathVariable` | `@PathParam` |
| `@RequestParam` | `@QueryParam` |
| `@RequestBody` | method parameter (no annotation needed with RESTEasy Reactive) |
| `@ResponseBody` | default in JAX-RS resource |
| `@Autowired` | `@Inject` |
| `@Value("${key}")` | `@ConfigProperty(name = "key")` |
| `@Configuration` | `@ApplicationScoped` producer methods |
| `@Bean` | `@Produces` on a method in an `@ApplicationScoped` class |
| `@Transactional` | `@jakarta.transaction.Transactional` |
| `@Scheduled(fixedRate=...)` | `@io.quarkus.scheduler.Scheduled(every="...")` |
| `@Async` | `Uni<T>` / `CompletionStage<T>` or `@RunOnVirtualThread` |
| `@EventListener` | CDI `@Observes` |
| `@Cacheable` | Quarkus Cache `@CacheResult` |
| `@Primary` | `@Default` (CDI) |
| `@Qualifier` | CDI `@Qualifier` + custom annotation |

## Spring Data → Panache

| Spring Data | Panache |
|---|---|
| `extends JpaRepository<T, ID>` | `extends PanacheRepository<T>` or `extends PanacheEntity` |
| `findById(id)` | `findById(id)` |
| `findAll()` | `listAll()` |
| `save(entity)` | `entity.persist()` or `repository.persist(entity)` |
| `deleteById(id)` | `deleteById(id)` |
| `@Query("JPQL")` | `find("jpql query", params)` |
| `Page<T> findAll(Pageable p)` | `findAll().page(Page.of(page, size)).list()` |
| `@GeneratedValue` | `@GeneratedValue` (same) |

## Spring Security → Quarkus Security

| Spring Security | Quarkus Security |
|---|---|
| `@EnableWebSecurity` | `quarkus-oidc` or `quarkus-smallrye-jwt` extension |
| `@PreAuthorize("hasRole('ROLE')")` | `@RolesAllowed("ROLE")` |
| `SecurityContextHolder.getContext()` | `@Context SecurityContext ctx` in JAX-RS |
| `UserDetailsService` | `SecurityIdentity` |
| `BCryptPasswordEncoder` | `BcryptUtil.bcryptHash(password)` |
| `HttpSecurity.csrf()` | disabled by default in Quarkus REST |

## CDI Scope Guide

| Scope | Lifetime | Use When |
|---|---|---|
| `@ApplicationScoped` | Application lifetime | Stateless services, repositories |
| `@RequestScoped` | HTTP request | Request-specific state |
| `@SessionScoped` | HTTP session | User session data |
| `@Singleton` | App lifetime (eager) | Configuration holders |
| `@Dependent` | Tied to injection point | Short-lived, per-injection objects |

## Key Quarkus Extensions

| Spring Dependency | Quarkus Extension |
|---|---|
| `spring-boot-starter-web` | `quarkus-resteasy-reactive` or `quarkus-resteasy-reactive-jackson` |
| `spring-boot-starter-data-jpa` | `quarkus-hibernate-orm-panache` |
| `spring-boot-starter-security` | `quarkus-security` + `quarkus-oidc` or `quarkus-smallrye-jwt` |
| `spring-boot-starter-cache` | `quarkus-cache` |
| `spring-boot-starter-actuator` | `quarkus-smallrye-health` + `quarkus-micrometer` |
| `spring-kafka` | `quarkus-messaging-kafka` |
| `spring-boot-starter-amqp` | `quarkus-messaging-amqp` |
| `spring-boot-starter-mail` | `quarkus-mailer` |
| `springdoc-openapi` | `quarkus-smallrye-openapi` |
| H2 (test) | `quarkus-jdbc-h2` |
| PostgreSQL | `quarkus-jdbc-postgresql` |
| MySQL | `quarkus-jdbc-mysql` |

## Native Image Compatibility Checklist

- Register reflection: `@RegisterForReflection` on DTOs, exceptions, and classes used via reflection
- Resources: Add `src/main/resources/META-INF/native-image/resource-config.json` for bundled resources
- Proxies: Register dynamic proxy interfaces in `proxy-config.json`
- Jackson: Use `quarkus-resteasy-reactive-jackson` (includes native-safe Jackson config)
- Avoid: `Class.forName()`, `Method.invoke()`, runtime proxy generation without registration

## application.properties Key Migration

| Spring Key | Quarkus Equivalent |
|---|---|
| `server.port` | `quarkus.http.port` |
| `spring.datasource.url` | `quarkus.datasource.jdbc.url` |
| `spring.datasource.username` | `quarkus.datasource.username` |
| `spring.datasource.password` | `quarkus.datasource.password` |
| `spring.jpa.hibernate.ddl-auto` | `quarkus.hibernate-orm.database.generation` |
| `spring.jpa.show-sql` | `quarkus.hibernate-orm.log.sql` |
| `logging.level.root` | `quarkus.log.level` |
| `spring.profiles.active` | `quarkus.profile` |
| `spring.application.name` | `quarkus.application.name` |
