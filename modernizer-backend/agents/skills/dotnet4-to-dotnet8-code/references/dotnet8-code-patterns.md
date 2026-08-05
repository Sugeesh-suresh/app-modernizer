# .NET 8 Code Patterns Reference

## Minimal Hosting Model (replaces Global.asax + Startup.cs)

**Before (.NET Framework, `Global.asax.cs`):**
```csharp
public class MvcApplication : System.Web.HttpApplication
{
    protected void Application_Start()
    {
        AreaRegistration.RegisterAllAreas();
        RouteConfig.RegisterRoutes(RouteTable.Routes);
        FilterConfig.RegisterGlobalFilters(GlobalFilters.Filters);
    }
}
```

**After (.NET 8, `Program.cs`):**
```csharp
var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllersWithViews();
builder.Services.AddDbContext<AppDbContext>(opts =>
    opts.UseSqlServer(builder.Configuration.GetConnectionString("Default")));
builder.Services.Configure<ApiSettings>(builder.Configuration.GetSection("ApiSettings"));
builder.Services.AddScoped<IOrderService, OrderService>();

var app = builder.Build();

if (!app.Environment.IsDevelopment())
    app.UseExceptionHandler("/Home/Error");

app.UseHttpsRedirection();
app.UseStaticFiles();
app.UseRouting();
app.UseAuthorization();
app.MapControllerRoute(name: "default", pattern: "{controller=Home}/{action=Index}/{id?}");
app.Run();
```

## Web API 2 → ASP.NET Core Web API

**Before:**
```csharp
public class OrdersController : ApiController
{
    private readonly IOrderService _service;
    public OrdersController(IOrderService service) { _service = service; }

    [HttpGet]
    [Route("api/orders/{id}")]
    public IHttpActionResult Get(int id)
    {
        var order = _service.GetById(id);
        if (order == null) return NotFound();
        return Ok(order);
    }
}
```

**After:**
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
}
```

## WCF Service → gRPC

**Before (`IOrderService.svc` contract):**
```csharp
[ServiceContract]
public interface IOrderService
{
    [OperationContract]
    Order GetOrder(int id);
}
```

**After (`order.proto` + gRPC service):**
```protobuf
service OrderService {
  rpc GetOrder (OrderRequest) returns (OrderReply);
}
message OrderRequest { int32 id = 1; }
message OrderReply { int32 id = 1; string customer_name = 2; double total = 3; }
```
```csharp
public class OrderGrpcService(IOrderRepository repo) : OrderService.OrderServiceBase
{
    public override async Task<OrderReply> GetOrder(OrderRequest request, ServerCallContext context)
    {
        var order = await repo.FindAsync(request.Id);
        return new OrderReply { Id = order.Id, CustomerName = order.CustomerName, Total = (double)order.Total };
    }
}
```

## EF6 → EF Core 8

**Before:**
```csharp
public class AppDbContext : DbContext
{
    public AppDbContext() : base("name=DefaultConnection") { }
    public DbSet<Order> Orders { get; set; }
}

using (var db = new AppDbContext())
{
    var orders = db.Orders.Where(o => o.Status == "Open").ToList();
}
```

**After:**
```csharp
public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public DbSet<Order> Orders => Set<Order>();
}

// Program.cs
builder.Services.AddDbContext<AppDbContext>(opts =>
    opts.UseSqlServer(builder.Configuration.GetConnectionString("Default")));

// Usage (constructor-injected, async)
var orders = await db.Orders.Where(o => o.Status == "Open").ToListAsync();
```

## Background Work: `System.Threading.Timer` → `IHostedService` / `BackgroundService`

**Before:**
```csharp
private static Timer _timer;
protected void Application_Start()
{
    _timer = new Timer(_ => ProcessQueue(), null, 0, 60000);
}
```

**After:**
```csharp
public class QueueProcessorService(IQueueClient client, ILogger<QueueProcessorService> logger) : BackgroundService
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
// Program.cs
builder.Services.AddHostedService<QueueProcessorService>();
```

## Logging: log4net / custom → `Microsoft.Extensions.Logging`

**Before:**
```csharp
private static readonly ILog log = LogManager.GetLogger(typeof(OrderService));
log.Info("Order created: " + order.Id);
```

**After:**
```csharp
public class OrderService(ILogger<OrderService> logger)
{
    public void Create(Order order) =>
        logger.LogInformation("Order created: {OrderId}", order.Id);
}
```

## Dependency Injection: Unity/Ninject container → built-in DI

**Before:**
```csharp
var container = new UnityContainer();
container.RegisterType<IOrderService, OrderService>();
container.RegisterType<IOrderRepository, SqlOrderRepository>();
```

**After:**
```csharp
builder.Services.AddScoped<IOrderService, OrderService>();
builder.Services.AddScoped<IOrderRepository, SqlOrderRepository>();
```
