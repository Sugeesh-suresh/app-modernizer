# C# .NET → Java Concept & Library Mapping Reference

## Core Language Concepts

| C# / .NET Concept | Java Equivalent | Notes |
|---|---|---|
| `class` | `class` | Direct mapping |
| `record` | `record` (Java 16+) | Both are immutable data carriers with generated equals/hashCode |
| `interface` | `interface` | Direct mapping; C# default interface methods → Java `default` methods |
| Properties (`{ get; set; }`) | Fields + getters/setters (or Lombok `@Getter`/`@Setter`) | Java has no native property syntax |
| `async`/`await` + `Task<T>` | Virtual threads (blocking style) or `CompletableFuture<T>` | Prefer virtual threads for simple request/response; reactive (`Mono`/`Flux`) for streaming |
| LINQ (`.Where().Select()`) | Stream API (`.stream().filter().map()`) | Near 1:1 conceptual mapping |
| `IEnumerable<T>` / `IQueryable<T>` | `Stream<T>` / JPA `Specification<T>` | `IQueryable` → Spring Data JPA Specifications for dynamic queries |
| Nullable reference types (`string?`) | `@Nullable` / `Optional<T>` | Use `Optional` for return types, `@Nullable` for parameters/fields |
| `Nullable<T>` (`int?`) | Boxed wrapper (`Integer`) or `Optional<Integer>` | |
| Extension methods | Static utility methods, or default interface methods | No direct extension-method syntax in Java |
| `using` (IDisposable) | `try-with-resources` (`AutoCloseable`) | |
| Delegates / `Func<T>` / `Action<T>` | Functional interfaces (`Function<T,R>`, `Consumer<T>`, `Supplier<T>`) | |
| Events (`event EventHandler`) | Observer pattern / Spring `ApplicationEventPublisher` | |
| Attributes (`[Route]`, `[Required]`) | Annotations (`@RequestMapping`, `@NotNull`) | |
| `struct` | Java `record` (if immutable) or plain class | Java has no value types on the heap distinction |
| Tuples (`(int, string)`) | `Map.Entry`, a small record, or `AbstractMap.SimpleEntry` | |
| Pattern matching (`is`, `switch` expressions) | `instanceof` pattern matching, Java `switch` expressions (Java 21+) | |

## Dependency Injection

| ASP.NET Core DI | Spring Boot Equivalent |
|---|---|
| `builder.Services.AddScoped<IFoo, Foo>()` | `@Service` / `@Component` (default singleton; use `@Scope("prototype")` for per-request) |
| `builder.Services.AddSingleton<IFoo, Foo>()` | `@Component` (Spring beans are singleton by default) |
| Constructor injection (built-in) | Constructor injection (`@RequiredArgsConstructor` via Lombok, or explicit constructor) |
| `IOptions<T>` | `@ConfigurationProperties` |
| `appsettings.json` | `application.yml` / `application.properties` |

**Spring DI pattern:**
```java
@Service
@RequiredArgsConstructor
public class OrderService {
    private final OrderRepository repo;
    private final ApplicationEventPublisher events;

    public Order create(CreateOrderRequest req) {
        Order order = repo.save(Order.from(req));
        events.publishEvent(new OrderCreatedEvent(order.getId()));
        return order;
    }
}
```

## NuGet Package → Java/Maven Library Mapping

| NuGet Package | Java/Maven Equivalent |
|---|---|
| `Microsoft.AspNetCore.Mvc` | `spring-boot-starter-web` |
| `Microsoft.EntityFrameworkCore` (EF Core) | `spring-boot-starter-data-jpa` + Hibernate |
| `Newtonsoft.Json` / `System.Text.Json` | Jackson (`jackson-databind`, bundled with Spring Boot) |
| `AutoMapper` | MapStruct |
| `FluentValidation` | Jakarta Bean Validation (`jakarta.validation`, `@Valid`) |
| `Serilog` / `NLog` | SLF4J + Logback (bundled with Spring Boot) |
| `Polly` (retry/circuit breaker) | Resilience4j |
| `MediatR` (CQRS/mediator) | Spring's `ApplicationEventPublisher`, or Axon Framework for full CQRS |
| `Hangfire` / Quartz.NET | Spring `@Scheduled`, or Quartz Scheduler (`spring-boot-starter-quartz`) |
| `IdentityServer` / `Microsoft.AspNetCore.Authentication.JwtBearer` | Spring Security + `spring-boot-starter-oauth2-resource-server` |
| `xUnit` / `NUnit` | JUnit 5 |
| `Moq` | Mockito |
| `Dapper` | Spring `JdbcTemplate` or MyBatis |
| `gRPC.AspNetCore` | `grpc-spring-boot-starter` |
| `MassTransit` (message bus) | Spring Cloud Stream / Spring Kafka |

## ASP.NET Core → Spring Boot Mapping

| ASP.NET Core | Spring Boot |
|---|---|
| `[ApiController]` + `ControllerBase` | `@RestController` |
| `[Route("api/orders")]` | `@RequestMapping("/api/orders")` |
| `[HttpGet("{id}")]` | `@GetMapping("/{id}")` |
| `[FromBody]` | `@RequestBody` |
| `[FromQuery]` | `@RequestParam` |
| Model binding + `[Required]` | `@Valid` + Bean Validation annotations |
| Middleware (`app.Use...`) | Servlet `Filter` or Spring `HandlerInterceptor` |
| `IActionResult` / `ActionResult<T>` | `ResponseEntity<T>` |
| `Program.cs` startup | `@SpringBootApplication` main class |
| `appsettings.{Environment}.json` | `application-{profile}.yml` + Spring Profiles |

## Concurrency Mapping

| C# / .NET Pattern | Java Pattern |
|---|---|
| `async Task<T> Method()` | Virtual thread (blocking-style code, `Thread.ofVirtual()`) for I/O-bound work |
| `Task.WhenAll(...)` | `CompletableFuture.allOf(...)` |
| `IAsyncEnumerable<T>` | `Stream<T>` (blocking) or Reactor `Flux<T>` (reactive) |
| `SemaphoreSlim` | `java.util.concurrent.Semaphore` |
| `CancellationToken` | Java doesn't have a direct equivalent — use `Future.cancel()` or check `Thread.interrupted()` |
| `IHostedService` / `BackgroundService` | Spring `@Scheduled` methods or a `@Component` implementing `ApplicationRunner` |
| `ConcurrentDictionary<K,V>` | `ConcurrentHashMap<K,V>` |

## Java/Maven Project Layout (Standard Spring Boot)

```
myapp/
├── src/main/java/com/example/app/
│   ├── Application.java              # @SpringBootApplication entry point
│   ├── controller/                   # REST controllers (replaces ASP.NET Controllers)
│   │   └── OrderController.java
│   ├── service/                      # Business logic (replaces C# Services)
│   │   └── OrderService.java
│   ├── repository/                   # Spring Data JPA repositories (replaces EF DbContext)
│   │   └── OrderRepository.java
│   ├── domain/                       # JPA entities (replaces EF entity classes)
│   │   └── Order.java
│   ├── dto/                          # DTOs (replaces C# records used as DTOs)
│   │   └── OrderDto.java
│   └── config/                       # @Configuration classes (replaces Program.cs DI setup)
├── src/main/resources/
│   ├── application.yml
│   └── db/migration/                 # Flyway migrations (replaces EF Core Migrations)
├── src/test/java/com/example/app/
├── pom.xml (or build.gradle)
```
