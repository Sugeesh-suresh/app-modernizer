# Go Project Layout Reference

## Standard Directory Structure

```
myapp/
├── cmd/
│   └── server/
│       └── main.go          # Binary entry point; wires all dependencies
├── internal/                # Private application code (not importable externally)
│   ├── api/                 # HTTP handlers and routing
│   │   ├── handler.go
│   │   ├── middleware.go
│   │   └── routes.go
│   ├── service/             # Business logic layer
│   │   └── order_service.go
│   ├── repository/          # Data access layer
│   │   ├── order_repository.go
│   │   └── db.go
│   ├── domain/              # Domain models, value objects, interfaces
│   │   └── order.go
│   └── config/              # Application configuration structs
│       └── config.go
├── pkg/                     # Exported shared packages (reusable across services)
│   ├── errors/
│   └── logger/
├── migrations/              # SQL migration files (numbered: 001_create_orders.up.sql)
├── docker/
│   └── Dockerfile
├── .github/
│   └── workflows/
│       └── ci.yml
├── go.mod
└── go.sum
```

## go.mod Template
```go
module github.com/yourorg/myapp

go 1.23

require (
    github.com/go-chi/chi/v5 v5.1.0
    github.com/jmoiron/sqlx v1.4.0
    github.com/lib/pq v1.10.9
    github.com/golang-migrate/migrate/v4 v4.18.1
    github.com/go-playground/validator/v10 v10.22.1
    github.com/golang-jwt/jwt/v5 v5.2.1
    log/slog v0.0.0   // stdlib in Go 1.21+
)
```

## HTTP Router (chi) Template
```go
// internal/api/routes.go
func NewRouter(orderHandler *OrderHandler, authMiddleware func(http.Handler) http.Handler) http.Handler {
    r := chi.NewRouter()
    r.Use(middleware.Logger)
    r.Use(middleware.Recoverer)
    r.Use(middleware.RequestID)

    r.Route("/api/v1", func(r chi.Router) {
        r.Use(authMiddleware)
        r.Route("/orders", func(r chi.Router) {
            r.Get("/", orderHandler.List)
            r.Post("/", orderHandler.Create)
            r.Get("/{id}", orderHandler.GetByID)
            r.Put("/{id}", orderHandler.Update)
            r.Delete("/{id}", orderHandler.Delete)
        })
    })
    return r
}
```

## Handler Template
```go
// internal/api/order_handler.go
type OrderHandler struct {
    svc OrderService
    log *slog.Logger
}

func NewOrderHandler(svc OrderService, log *slog.Logger) *OrderHandler {
    return &OrderHandler{svc: svc, log: log}
}

func (h *OrderHandler) Create(w http.ResponseWriter, r *http.Request) {
    var req CreateOrderRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        http.Error(w, "invalid request body", http.StatusBadRequest)
        return
    }
    order, err := h.svc.Create(r.Context(), req)
    if err != nil {
        h.log.Error("create order failed", "error", err)
        http.Error(w, "internal error", http.StatusInternalServerError)
        return
    }
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusCreated)
    json.NewEncoder(w).Encode(order)
}
```

## Repository Template (sqlx)
```go
// internal/repository/order_repository.go
type OrderRepository struct {
    db *sqlx.DB
}

func NewOrderRepository(db *sqlx.DB) *OrderRepository {
    return &OrderRepository{db: db}
}

func (r *OrderRepository) FindByID(ctx context.Context, id int64) (*domain.Order, error) {
    var order domain.Order
    err := r.db.GetContext(ctx, &order, "SELECT * FROM orders WHERE id = $1", id)
    if err == sql.ErrNoRows {
        return nil, nil
    }
    return &order, err
}

func (r *OrderRepository) Save(ctx context.Context, order *domain.Order) error {
    _, err := r.db.NamedExecContext(ctx,
        "INSERT INTO orders (customer_id, total, status) VALUES (:customer_id, :total, :status)",
        order)
    return err
}
```

## Config Loading Pattern
```go
// internal/config/config.go
type Config struct {
    Server   ServerConfig
    Database DatabaseConfig
    JWT      JWTConfig
}

type ServerConfig struct {
    Port    int    `env:"PORT" envDefault:"8080"`
    Host    string `env:"HOST" envDefault:"0.0.0.0"`
}

type DatabaseConfig struct {
    DSN          string `env:"DATABASE_URL,required"`
    MaxOpenConns int    `env:"DB_MAX_OPEN_CONNS" envDefault:"10"`
}

// Load using github.com/caarlos0/env or os.Getenv + defaults
```

## Dockerfile (multi-stage)
```dockerfile
FROM golang:1.23-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /app/server ./cmd/server

FROM gcr.io/distroless/static-debian12
COPY --from=builder /app/server /server
EXPOSE 8080
ENTRYPOINT ["/server"]
```
