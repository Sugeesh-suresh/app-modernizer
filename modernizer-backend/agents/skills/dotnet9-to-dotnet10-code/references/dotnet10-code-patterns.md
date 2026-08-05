# .NET 10 Code Patterns Reference

## `field` Contextual Keyword (C# 14)

**Before (breaks — `field` is now contextual in property accessors, CS9272):**
```csharp
public object Property
{
    get
    {
        int field = 0;
        return field;
    }
}
```

**After:**
```csharp
public object Property
{
    get
    {
        int fieldValue = 0;
        return fieldValue;
    }
}
```

## `extension` Contextual Keyword (C# 14)

**Before:**
```csharp
class extension { }
```

**After:**
```csharp
class @extension { }
```

## Span Overload Resolution Changes

**Before (now resolves to the `Span<T>` extension with a `void` return):**
```csharp
var reversed = arr.Reverse();
```

**After:**
```csharp
var reversed = Enumerable.Reverse(arr);
```

## `WebHostBuilder` → Minimal Hosting

**Before:**
```csharp
var host = new WebHostBuilder()
    .UseKestrel()
    .UseStartup<Startup>()
    .Build();
host.Run();
```

**After:**
```csharp
var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllers();
var app = builder.Build();
app.MapControllers();
app.Run();
```

## `IActionContextAccessor` → DI / `HttpContext`

**Before:**
```csharp
public class OrderService(IActionContextAccessor accessor)
{
    public string RouteValue => accessor.ActionContext!.RouteData.Values["id"]!.ToString()!;
}
```

**After:**
```csharp
public class OrderService(IHttpContextAccessor httpContextAccessor)
{
    public string RouteValue => httpContextAccessor.HttpContext!.GetRouteValue("id")!.ToString()!;
}
```

## Microsoft.OpenApi v2 Namespace Move

**Before:**
```csharp
using Microsoft.OpenApi.Models;

var schema = new OpenApiSchema { Type = "string", Nullable = true };
operation.Responses.Add("200", new OpenApiResponse { Description = "OK" });
```

**After:**
```csharp
using Microsoft.OpenApi;

var schema = new OpenApiSchema { Type = JsonSchemaType.String | JsonSchemaType.Null };
operation.Responses ??= new OpenApiResponses();
operation.Responses.Add("200", new OpenApiResponse { Description = "OK" });
```

## `IPNetwork` Migration

**Before:**
```csharp
services.Configure<ForwardedHeadersOptions>(options =>
{
    options.KnownNetworks.Add(new IPNetwork(IPAddress.Parse("10.0.0.0"), 8));
});
```

**After:**
```csharp
services.Configure<ForwardedHeadersOptions>(options =>
{
    options.KnownIpNetworks.Add(new System.Net.IPNetwork(IPAddress.Parse("10.0.0.0"), 8));
});
```

## EF Core `ExecuteUpdateAsync` — Action-Based Setters

**Before (expression tree built manually for dynamic setters):**
```csharp
Expression<Func<SetPropertyCalls<Order>, SetPropertyCalls<Order>>> setters = BuildSetterExpression(changes);
await db.Orders.Where(o => o.Id == id).ExecuteUpdateAsync(setters);
```

**After:**
```csharp
await db.Orders.Where(o => o.Id == id).ExecuteUpdateAsync(setters => setters
    .SetProperty(o => o.Status, "Shipped")
    .SetProperty(o => o.ShippedAt, DateTime.UtcNow));
```

## Microsoft.Data.Sqlite Date/Time (UTC by Default)

**Before (implicitly local-time semantics):**
```csharp
command.CommandText = "SELECT CreatedAt FROM Orders WHERE Id = $id";
var createdAt = (DateTime)reader["CreatedAt"];
```

**After (be explicit that stored/returned values are UTC):**
```csharp
command.CommandText = "SELECT CreatedAt FROM Orders WHERE Id = $id";
var createdAtUtc = DateTime.SpecifyKind((DateTime)reader["CreatedAt"], DateTimeKind.Utc);
```
