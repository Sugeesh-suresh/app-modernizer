# Go Idioms & Patterns Reference

## Error Handling

```go
// Always check errors; wrap with context
func (s *OrderService) Create(ctx context.Context, dto CreateOrderDTO) (*Order, error) {
    if err := s.validator.Struct(dto); err != nil {
        return nil, fmt.Errorf("validation failed: %w", err)
    }
    order, err := s.repo.Save(ctx, toEntity(dto))
    if err != nil {
        return nil, fmt.Errorf("save order: %w", err)
    }
    return order, nil
}

// Sentinel errors for domain errors
var ErrOrderNotFound = errors.New("order not found")

// Check with errors.Is
if errors.Is(err, ErrOrderNotFound) {
    http.Error(w, "not found", http.StatusNotFound)
}
```

## Context Propagation
```go
// Always pass context as first parameter
func (r *OrderRepository) FindByID(ctx context.Context, id int64) (*Order, error) {
    var o Order
    return &o, r.db.QueryRowContext(ctx, "SELECT * FROM orders WHERE id=$1", id).Scan(&o.ID, &o.Total)
}

// Use context for cancellation and deadlines
ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
defer cancel()
order, err := svc.FindByID(ctx, id)
```

## Interfaces (small, focused)
```go
// Define interfaces where they're USED, not where implemented
type OrderRepository interface {
    FindByID(ctx context.Context, id int64) (*Order, error)
    Save(ctx context.Context, order *Order) error
    List(ctx context.Context, filter OrderFilter) ([]*Order, error)
}

// Single-method interfaces are idiomatic
type Logger interface {
    Log(msg string, args ...any)
}
```

## Struct Embedding (composition over inheritance)
```go
type BaseEntity struct {
    ID        int64     `db:"id"`
    CreatedAt time.Time `db:"created_at"`
    UpdatedAt time.Time `db:"updated_at"`
}

type Order struct {
    BaseEntity                          // embed, not inherit
    CustomerID int64  `db:"customer_id"`
    Total      float64 `db:"total"`
    Status     string `db:"status"`
}
```

## Goroutine Pool Pattern (replaces ExecutorService)
```go
func processOrdersConcurrently(ctx context.Context, orders []Order, svc OrderService) error {
    g, ctx := errgroup.WithContext(ctx)
    sem := make(chan struct{}, 10) // max 10 concurrent workers

    for _, o := range orders {
        o := o // capture loop variable
        g.Go(func() error {
            sem <- struct{}{}
            defer func() { <-sem }()
            return svc.Process(ctx, o)
        })
    }
    return g.Wait()
}
```

## Channel-based Producer/Consumer (replaces BlockingQueue)
```go
func startWorker(ctx context.Context, jobs <-chan Job, results chan<- Result) {
    for {
        select {
        case job, ok := <-jobs:
            if !ok {
                return
            }
            results <- processJob(job)
        case <-ctx.Done():
            return
        }
    }
}
```

## Table-driven Tests
```go
func TestOrderService_Create(t *testing.T) {
    tests := []struct {
        name    string
        input   CreateOrderDTO
        wantErr bool
    }{
        {"valid order", CreateOrderDTO{CustomerID: 1, Total: 99.99}, false},
        {"zero total", CreateOrderDTO{CustomerID: 1, Total: 0}, true},
        {"missing customer", CreateOrderDTO{Total: 10.00}, true},
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            svc := NewOrderService(mockRepo, slog.Default())
            _, err := svc.Create(context.Background(), tt.input)
            if (err != nil) != tt.wantErr {
                t.Errorf("Create() error = %v, wantErr %v", err, tt.wantErr)
            }
        })
    }
}
```

## JSON Tags (replaces Jackson annotations)
```go
type OrderDTO struct {
    ID         int64     `json:"id"`
    CustomerID int64     `json:"customerId"`
    Total      float64   `json:"total"`
    Status     string    `json:"status"`
    CreatedAt  time.Time `json:"createdAt"`
    InternalID string    `json:"-"` // omit from JSON
    Notes      string    `json:"notes,omitempty"` // omit if empty
}
```

## Validation (replaces Bean Validation / @Valid)
```go
import "github.com/go-playground/validator/v10"

type CreateOrderRequest struct {
    CustomerID int64   `json:"customerId" validate:"required,gt=0"`
    Total      float64 `json:"total" validate:"required,gt=0"`
    Items      []Item  `json:"items" validate:"required,min=1,dive"`
}

var validate = validator.New()

func validateRequest(req any) error {
    if err := validate.Struct(req); err != nil {
        return fmt.Errorf("validation: %w", err)
    }
    return nil
}
```

## Middleware Pattern (replaces Spring Security filters)
```go
func AuthMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        token := r.Header.Get("Authorization")
        claims, err := parseJWT(strings.TrimPrefix(token, "Bearer "))
        if err != nil {
            http.Error(w, "unauthorized", http.StatusUnauthorized)
            return
        }
        ctx := context.WithValue(r.Context(), ctxKeyUser, claims.Subject)
        next.ServeHTTP(w, r.WithContext(ctx))
    })
}
```

## Scheduler Pattern (replaces @Scheduled)
```go
func StartScheduler(ctx context.Context, svc ReportService) {
    ticker := time.NewTicker(1 * time.Hour)
    go func() {
        for {
            select {
            case <-ticker.C:
                if err := svc.GenerateReport(ctx); err != nil {
                    slog.Error("report generation failed", "error", err)
                }
            case <-ctx.Done():
                ticker.Stop()
                return
            }
        }
    }()
}
```
