# .NET 8 → .NET 9 Migration Checklist

Source: distilled from the `dotnet/skills` `migrate-dotnet8-to-dotnet9` reference set (C# compiler, ASP.NET Core, EF Core).

## Target Framework & SDK

```xml
<!-- Before -->
<TargetFramework>net8.0</TargetFramework>

<!-- After -->
<TargetFramework>net9.0</TargetFramework>
```
Bump every `Microsoft.AspNetCore.*`, `Microsoft.EntityFrameworkCore.*`, and `Microsoft.Extensions.*` package reference to the matching `9.0.x` version. Requires Visual Studio 17.12+ / .NET 9 SDK.

## C# 13 Compiler Breaking Changes

| Change | Before | After |
|---|---|---|
| `[InlineArray]` on `record struct` (CS9259) | `[InlineArray(10)] record struct Buffer() { private int _e0; }` | `[InlineArray(10)] struct Buffer { private int _e0; }` |
| Unsafe code in iterator-nested local functions | `unsafe class C { IEnumerable<int> M() { yield return 1; void local() { int* p=null; } } }` (error) | Mark the local function `unsafe void local() { int* p = null; }` |
| Collection expression (`[]`) overload resolution | Ambiguous between `Span<T>`/`ReadOnlySpan<T>` on empty literal | Use an explicit typed variable or cast |
| Method group → delegate inference with `params`/default params | `var d = SomeMethod;` (ambiguous) | Declare an explicit delegate type instead of `var` |

## Obsoletions (SYSLIB0054–SYSLIB0057)

- `Thread.VolatileRead`/`VolatileWrite` → use `Volatile.Read`/`Volatile.Write` or `Interlocked`
- Certain `X509Certificate`/`X509Certificate2` constructors → use `X509CertificateLoader`
- Deprecated ARM intrinsics → use the replacement intrinsic named in the warning
- `BinaryFormatter` now **always throws** at runtime — migrate to `System.Text.Json`, protobuf, or `MessagePack` if any usage remains from a prior .NET Framework migration

## ASP.NET Core 9

- **DI validation on by default in Development**: `ValidateOnBuild`/`ValidateScopes` now true, surfacing previously-silent DI misconfiguration at startup. Opt out only if intentional:
  ```csharp
  builder.Host.UseDefaultServiceProvider(o => { o.ValidateOnBuild = false; o.ValidateScopes = false; });
  ```
- **Forwarded Headers Middleware** now ignores `X-Forwarded-*` from proxies not in `KnownProxies`/`KnownNetworks` — add trusted proxies explicitly if headers stop propagating
- Middleware constructor selection with multiple constructors is now deterministic (previously undefined) — verify no code relied on the old behavior
- `HttpListenerRequest.UserAgent` is now nullable — add null checks

## EF Core 9

- **Pending model changes block `Migrate()`**: throws `"The model for context '...' has pending changes"` if the model built from code differs from the last migration snapshot. Avoid non-deterministic `HasData()` values (e.g. `DateTime.UtcNow`) — use fixed literals instead.
- **`Migrate()`/`MigrateAsync()` reject external transactions**: remove any `BeginTransactionAsync()` wrapping around a `Migrate()` call — EF Core now manages its own transaction internally.
- With .NET SDK 9.0.200+, add an explicit `Microsoft.EntityFrameworkCore.Design` `PackageReference` (with `PrivateAssets=all`) if `dotnet ef` commands start failing to load the assembly.
- Cosmos DB provider: discriminator property renamed `Discriminator` → `$type` (restore old name via `HasDiscriminator<string>("Discriminator")` if needed); `id` field format changed from compound (`Product|123`) to plain key value — call `HasRootDiscriminatorInJsonId(true)` to keep existing documents readable.

## Runtime Behavioral Changes

- Floating-point → integer conversions now **saturate** instead of wrapping on x86/x64 — audit any code relying on wraparound behavior
- `IHttpClientFactory` now defaults to `SocketsHttpHandler`; code that casts the returned handler to `HttpClientHandler` will throw `InvalidCastException`
- Environment variables now override matching `runtimeconfig.json` settings — check deployment scripts that set both
- Container base images no longer bundle zlib — add it explicitly in the Dockerfile if native code depends on it

## Infrastructure

- Update Docker base images to `mcr.microsoft.com/dotnet/*:9.0`
- Update CI/CD SDK version pins and `global.json`
- Visual Studio 17.12+ required; note new Terminal Logger console output format if build scripts parse MSBuild output
