# .NET 9 Code Patterns Reference

## `[InlineArray]` on `record struct` (C# 13, CS9259)

**Before (breaks in C# 13):**
```csharp
[System.Runtime.CompilerServices.InlineArray(10)]
record struct Buffer() { private int _element0; }
```

**After:**
```csharp
[System.Runtime.CompilerServices.InlineArray(10)]
struct Buffer { private int _element0; }
```

## Unsafe Code Inside Iterators

**Before (breaks — iterators now enforce a safe context):**
```csharp
unsafe class C
{
    IEnumerable<int> M()
    {
        yield return 1;
        void local() { int* p = null; } // error
    }
}
```

**After:**
```csharp
unsafe class C
{
    IEnumerable<int> M()
    {
        yield return 1;
        unsafe void local() { int* p = null; } // OK
    }
}
```

## Obsoleted APIs (SYSLIB0054–SYSLIB0057)

**Before:**
```csharp
Thread.VolatileWrite(ref _flag, 1);
var cert = new X509Certificate2(bytes, password);
```

**After:**
```csharp
Volatile.Write(ref _flag, 1);
var cert = X509CertificateLoader.LoadCertificate(bytes); // or LoadPkcs12 with password
```

## `HttpClientFactory` Handler Casting

**Before (throws `InvalidCastException` — factory now defaults to `SocketsHttpHandler`):**
```csharp
var client = _httpClientFactory.CreateClient("api");
var handler = (HttpClientHandler)client.GetType()
    .GetField("handler", BindingFlags.NonPublic | BindingFlags.Instance)!
    .GetValue(client)!;
```

**After:**
```csharp
builder.Services.AddHttpClient("api")
    .ConfigurePrimaryHttpMessageHandler(() => new SocketsHttpHandler
    {
        PooledConnectionLifetime = TimeSpan.FromMinutes(5)
    });
```

## EF Core `Migrate()` — No External Transactions, Deterministic `HasData`

**Before:**
```csharp
await using var tx = await dbContext.Database.BeginTransactionAsync(ct);
await dbContext.Database.MigrateAsync(ct);
await tx.CommitAsync(ct);

modelBuilder.Entity<Order>().HasData(
    new Order { Id = 1, CreatedAt = DateTime.UtcNow });
```

**After:**
```csharp
await dbContext.Database.MigrateAsync(ct); // EF Core manages its own transaction

modelBuilder.Entity<Order>().HasData(
    new Order { Id = 1, CreatedAt = new DateTime(2024, 1, 1, 0, 0, 0, DateTimeKind.Utc) });
```

## ASP.NET Core DI Validation (Development)

**Before (silent misconfiguration in dev):**
```csharp
var builder = WebApplication.CreateBuilder(args);
```

**After (only if you must opt out of the new default validation):**
```csharp
var builder = WebApplication.CreateBuilder(args);
builder.Host.UseDefaultServiceProvider(o =>
{
    o.ValidateOnBuild = false;
    o.ValidateScopes = false;
});
```

## Forwarded Headers — Trusted Proxies Required

**Before:**
```csharp
app.UseForwardedHeaders(new ForwardedHeadersOptions
{
    ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto
});
```

**After:**
```csharp
builder.Services.Configure<ForwardedHeadersOptions>(options =>
{
    options.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
    options.KnownProxies.Add(IPAddress.Parse("10.0.0.1"));
});
```

## Floating-Point → Integer Conversion (Now Saturates)

**Before (relied on wraparound on x86/x64):**
```csharp
double d = 1e20;
int i = unchecked((int)d); // previously wrapped to an implementation-defined value
```

**After (be explicit about the intended clamp/overflow behavior):**
```csharp
double d = 1e20;
int i = (int)d; // now saturates to int.MaxValue — add explicit clamping/validation if wraparound was actually intended
```
