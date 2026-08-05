# Java/Spring Boot Idioms — Coming From C# .NET

## Controller

**Before (ASP.NET Core):**
```csharp
[ApiController]
[Route("api/orders")]
public class OrdersController(IOrderService service) : ControllerBase
{
    [HttpGet("{id}")]
    public async Task<ActionResult<OrderDto>> Get(int id)
    {
        var order = await service.GetByIdAsync(id);
        return order is null ? NotFound() : Ok(order);
    }

    [HttpPost]
    public async Task<ActionResult<OrderDto>> Create([FromBody] CreateOrderRequest req)
    {
        var order = await service.CreateAsync(req);
        return CreatedAtAction(nameof(Get), new { id = order.Id }, order);
    }
}
```

**After (Spring Boot):**
```java
@RestController
@RequestMapping("/api/orders")
@RequiredArgsConstructor
public class OrderController {
    private final OrderService service;

    @GetMapping("/{id}")
    public ResponseEntity<OrderDto> get(@PathVariable Long id) {
        return service.findById(id)
            .map(ResponseEntity::ok)
            .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @PostMapping
    public ResponseEntity<OrderDto> create(@Valid @RequestBody CreateOrderRequest req) {
        OrderDto order = service.create(req);
        return ResponseEntity.created(URI.create("/api/orders/" + order.id())).body(order);
    }
}
```

## Entity / Repository

**Before (EF Core):**
```csharp
public class Order
{
    public int Id { get; set; }
    public string CustomerName { get; set; }
    public decimal Total { get; set; }
    public List<OrderLine> Lines { get; set; } = new();
}

public interface IOrderRepository
{
    Task<Order?> GetByIdAsync(int id);
}

public class OrderRepository(AppDbContext db) : IOrderRepository
{
    public Task<Order?> GetByIdAsync(int id) =>
        db.Orders.Include(o => o.Lines).FirstOrDefaultAsync(o => o.Id == id);
}
```

**After (Spring Data JPA):**
```java
@Entity
@Table(name = "orders")
@Getter @Setter
public class Order {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String customerName;
    private BigDecimal total;

    @OneToMany(mappedBy = "order", cascade = CascadeType.ALL, fetch = FetchType.LAZY)
    private List<OrderLine> lines = new ArrayList<>();
}

public interface OrderRepository extends JpaRepository<Order, Long> {
    @Query("select o from Order o left join fetch o.lines where o.id = :id")
    Optional<Order> findByIdWithLines(@Param("id") Long id);
}
```

## DTO / Record Mapping

**Before:**
```csharp
public record OrderDto(int Id, string CustomerName, decimal Total);

public class OrderMappingProfile : Profile
{
    public OrderMappingProfile()
    {
        CreateMap<Order, OrderDto>();
    }
}
```

**After:**
```java
public record OrderDto(Long id, String customerName, BigDecimal total) {}

@Mapper(componentModel = "spring")
public interface OrderMapper {
    OrderDto toDto(Order order);
    Order toEntity(OrderDto dto);
}
```

## LINQ → Streams

**Before:**
```csharp
var topCustomers = orders
    .Where(o => o.Status == OrderStatus.Completed)
    .GroupBy(o => o.CustomerId)
    .Select(g => new { CustomerId = g.Key, Total = g.Sum(o => o.Total) })
    .OrderByDescending(x => x.Total)
    .Take(10)
    .ToList();
```

**After:**
```java
List<CustomerTotal> topCustomers = orders.stream()
    .filter(o -> o.getStatus() == OrderStatus.COMPLETED)
    .collect(Collectors.groupingBy(Order::getCustomerId,
        Collectors.summingDouble(o -> o.getTotal().doubleValue())))
    .entrySet().stream()
    .map(e -> new CustomerTotal(e.getKey(), e.getValue()))
    .sorted(Comparator.comparingDouble(CustomerTotal::total).reversed())
    .limit(10)
    .toList();
```

## Validation

**Before (FluentValidation):**
```csharp
public class CreateOrderValidator : AbstractValidator<CreateOrderRequest>
{
    public CreateOrderValidator()
    {
        RuleFor(x => x.CustomerName).NotEmpty().MaximumLength(200);
        RuleFor(x => x.Total).GreaterThan(0);
    }
}
```

**After (Jakarta Bean Validation):**
```java
public record CreateOrderRequest(
    @NotBlank @Size(max = 200) String customerName,
    @Positive BigDecimal total
) {}
```

## Global Exception Handling

**Before (ASP.NET Core middleware):**
```csharp
app.UseExceptionHandler(errApp => errApp.Run(async ctx =>
{
    var ex = ctx.Features.Get<IExceptionHandlerFeature>()?.Error;
    ctx.Response.StatusCode = ex is NotFoundException ? 404 : 500;
    await ctx.Response.WriteAsJsonAsync(new { error = ex?.Message });
}));
```

**After (`@ControllerAdvice`):**
```java
@RestControllerAdvice
public class GlobalExceptionHandler {
    @ExceptionHandler(NotFoundException.class)
    public ResponseEntity<ErrorResponse> handleNotFound(NotFoundException ex) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(new ErrorResponse(ex.getMessage()));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleGeneric(Exception ex) {
        return ResponseEntity.internalServerError().body(new ErrorResponse(ex.getMessage()));
    }
}
```

## Background Work

**Before (`IHostedService`):**
```csharp
public class QueueProcessor(IQueueClient client) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            await client.ProcessNextAsync(stoppingToken);
            await Task.Delay(TimeSpan.FromMinutes(1), stoppingToken);
        }
    }
}
```

**After (`@Scheduled`):**
```java
@Component
@RequiredArgsConstructor
public class QueueProcessor {
    private final QueueClient client;

    @Scheduled(fixedDelay = 60_000)
    public void processNext() {
        client.processNext();
    }
}
```
