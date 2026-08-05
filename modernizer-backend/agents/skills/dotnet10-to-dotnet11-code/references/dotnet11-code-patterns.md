# .NET 11 (Preview) Code Patterns Reference

## Span Collection-Expression Scoping (C# 15)

**Before (breaks — safe-context is now declaration-block):**
```csharp
scoped Span<int> items1 = default;
foreach (var x in new[] { 1, 2 })
{
    Span<int> items = [x];
    items1 = items; // error: safe-context is declaration-block
}
```

**After:**
```csharp
int[] items1Backing = Array.Empty<int>();
foreach (var x in new[] { 1, 2 })
{
    int[] items = [x]; // array converts implicitly to Span<int> where needed
    items1Backing = items;
}
Span<int> items1 = items1Backing;
```

## Interface `true`/`false` Operators with `dynamic`

**Before (error CS7083):**
```csharp
I1 x = new C1();
dynamic y = new C1();
_ = x && y;
```

**After:**
```csharp
I1 x = new C1();
dynamic y = new C1();
_ = (C1)x && y;
```

## `nameof(this.Member)` in Attributes

**Before (no longer allowed):**
```csharp
public class OrderService
{
    [DisplayName(nameof(this.CustomerName))]
    public string CustomerName { get; set; } = "";
}
```

**After:**
```csharp
public class OrderService
{
    [DisplayName(nameof(CustomerName))]
    public string CustomerName { get; set; } = "";
}
```

## EF Core Cosmos — Sync → Async

**Before (throws — Cosmos provider is async-only in EF Core 11):**
```csharp
var items = context.Items.ToList();
context.SaveChanges();
```

**After:**
```csharp
var items = await context.Items.ToListAsync();
await context.SaveChangesAsync();
```

## EF Core Cosmos — Owned Collection Null Checks

**Before:**
```csharp
if (order.LineItems is null)
{
    order.LineItems = new List<LineItem>();
}
```

**After:**
```csharp
if (order.LineItems.Count == 0)
{
    // owned collection is never null on Cosmos in EF Core 11 — populate directly
    order.LineItems.AddRange(newLineItems);
}
```

## `BackgroundService` — Explicit Exception Handling Required

**Before (unhandled exception now terminates the host):**
```csharp
public class QueueProcessorService(IQueueClient client) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            await client.ProcessNextAsync(stoppingToken);
        }
    }
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
            try
            {
                await client.ProcessNextAsync(stoppingToken);
            }
            catch (Exception ex) when (!stoppingToken.IsCancellationRequested)
            {
                logger.LogError(ex, "Queue processing failed; continuing.");
            }
        }
    }
}
```
