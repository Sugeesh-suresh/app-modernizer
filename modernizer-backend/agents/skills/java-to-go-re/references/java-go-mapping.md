# Java → Go Concept & Library Mapping Reference

## Core Language Concepts

| Java Concept | Go Equivalent | Notes |
|---|---|---|
| Class | Struct | No class hierarchy in Go |
| Interface | Interface | Go interfaces are implicit (duck typing) |
| Abstract class | Interface + struct embedding | Use composition |
| Inheritance (`extends`) | Struct embedding | `type Dog struct { Animal }` |
| Checked exceptions | Multiple return values `(T, error)` | Errors are values, not exceptions |
| Unchecked exceptions | `panic` / `recover` | Use sparingly; prefer error returns |
| `Optional<T>` | Pointer `*T` or `(T, bool)` | nil pointer means absent |
| `List<T>` | `[]T` | Slice |
| `Map<K,V>` | `map[K]V` | Built-in map type |
| `Set<T>` | `map[T]struct{}` | No built-in Set |
| Generics (`<T>`) | Generics (`[T any]`) | Available since Go 1.18 |
| `synchronized` | `sync.Mutex` / `sync.RWMutex` | Explicit locking |
| Thread | Goroutine | `go func() { ... }()` |
| `BlockingQueue` | Channel `chan T` | Built-in concurrency primitive |
| `ExecutorService` | Goroutine pool | `sync.WaitGroup` + channels |
| `CompletableFuture` | Channel or `errgroup` | `golang.org/x/sync/errgroup` |
| Enum | `const` + `iota` | Type-safe constants |
| Annotation | Struct tags | `` `json:"name"` ``, `` `db:"name"` `` |
| `@Builder` (Lombok) | Constructor function | `NewOrder(...)` factory pattern |
| Lambda / Stream API | Closures + loops | No built-in stream; use slices |
| `instanceof` check | Type switch / type assertion | `switch v := x.(type) { ... }` |

## Dependency Injection

| Spring DI Pattern | Go Equivalent |
|---|---|
| `@Autowired` field | Constructor parameter |
| `@Component` / `@Service` | Exported struct with constructor func |
| `@Configuration` / `@Bean` | `main.go` wiring with `New*()` factories |
| Application context | Manual dependency graph in `main` |
| `@Scope("prototype")` | Create new instance with `New*()` each time |

**Go DI pattern:**
```go
// service.go
type OrderService struct {
    repo OrderRepository
    log  *slog.Logger
}

func NewOrderService(repo OrderRepository, log *slog.Logger) *OrderService {
    return &OrderService{repo: repo, log: log}
}

// main.go
func main() {
    db := database.Open(cfg.DSN)
    repo := repository.NewOrderRepository(db)
    svc := service.NewOrderService(repo, slog.Default())
    handler := api.NewOrderHandler(svc)
    // wire into HTTP router
}
```

## Java Library → Go Library Mapping

| Java Library | Go Equivalent | Import Path |
|---|---|---|
| Spring Web / Tomcat | `net/http` (stdlib) or `chi` | `github.com/go-chi/chi/v5` |
| Spring Data JPA | `sqlx` or `gorm` | `github.com/jmoiron/sqlx` |
| Hibernate | `gorm` | `gorm.io/gorm` |
| Flyway | `golang-migrate` | `github.com/golang-migrate/migrate/v4` |
| Jackson | `encoding/json` (stdlib) | Built-in |
| Lombok | None needed | No boilerplate in Go |
| SLF4J / Logback | `log/slog` (stdlib, Go 1.21+) | Built-in |
| Micrometer | `prometheus/client_golang` | `github.com/prometheus/client_golang` |
| Spring Security / JWT | `golang-jwt/jwt` | `github.com/golang-jwt/jwt/v5` |
| Spring Kafka | `confluent-kafka-go` | `github.com/confluentinc/confluent-kafka-go` |
| Spring Retry | Manual retry loops or `avast/retry-go` | `github.com/avast/retry-go` |
| Bean Validation | `go-playground/validator` | `github.com/go-playground/validator/v10` |
| Testcontainers | `testcontainers-go` | `github.com/testcontainers/testcontainers-go` |
| MockMvc | `net/http/httptest` (stdlib) | Built-in |
| Mockito | `gomock` or `testify/mock` | `go.uber.org/mock` |

## Go Project Layout (Standard)

```
myapp/
├── cmd/
│   └── server/
│       └── main.go          # Entry point, wires dependencies
├── internal/
│   ├── api/                 # HTTP handlers (replaces @RestController)
│   │   └── order_handler.go
│   ├── service/             # Business logic (replaces @Service)
│   │   └── order_service.go
│   ├── repository/          # Data access (replaces JpaRepository)
│   │   └── order_repository.go
│   └── domain/              # Domain models (replaces @Entity / DTO)
│       └── order.go
├── pkg/                     # Exported shared utilities
│   └── errors/
│       └── errors.go
├── migrations/              # SQL migration files (Flyway → golang-migrate)
├── go.mod
└── go.sum
```

## Concurrency Patterns

| Java Pattern | Go Pattern |
|---|---|
| Thread pool (`ExecutorService`) | Goroutine pool with `sync.WaitGroup` |
| `Future<T>` | Channel `chan T` |
| `CompletableFuture.allOf(...)` | `errgroup.Group` |
| `synchronized` method | `sync.Mutex.Lock()` / `Unlock()` |
| `volatile` field | `sync/atomic` operations |
| Producer-consumer queue | Buffered channel `make(chan T, bufSize)` |
| `ScheduledExecutorService` | `time.Ticker` / `time.AfterFunc` |
