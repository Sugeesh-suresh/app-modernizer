# .NET 9 → .NET 10 Migration Checklist

Source: distilled from the `dotnet/skills` `migrate-dotnet9-to-dotnet10` reference set (C# compiler, ASP.NET Core, EF Core).

## Target Framework & SDK

```xml
<!-- Before -->
<TargetFramework>net9.0</TargetFramework>

<!-- After -->
<TargetFramework>net10.0</TargetFramework>
```
Bump every `Microsoft.AspNetCore.*`, `Microsoft.EntityFrameworkCore.*`, and `Microsoft.Extensions.*` package reference to the matching `10.0.x` version.

## C# 14 Compiler Breaking Changes

| Change | Before | After |
|---|---|---|
| `field` contextual keyword in property accessors (CS9272) | `get { int field = 0; return field; }` | Rename the local: `get { int fieldValue = 0; return fieldValue; }` (or escape as `@field`) |
| `extension` contextual keyword | `class extension { }` | `class @extension { }` (or rename) |
| Span/`ReadOnlySpan` overload resolution changes | `var reversed = arr.Reverse();` (resolves to `Span` extension, `void` return) | `var reversed = Enumerable.Reverse(arr);` (explicit call) |

Also review: disposed enumerators now correctly return `false` from `MoveNext()`; obsolete `DisposeAsync` implementations now raise diagnostics in `await foreach`; redundant `or`-pattern branches now warn.

## Obsoletions (SYSLIB0058–SYSLIB0062)

Check build warnings for each SYSLIB05xx code introduced in .NET 10 and replace with the API named in the warning message — the specific set depends on which BCL areas the app touches (cryptography, threading, formatting).

## ASP.NET Core 10

- **`WebHostBuilder`/`IWebHost` deprecated** — migrate any remaining classic hosting to `WebApplication.CreateBuilder()`:
  ```csharp
  // Before
  var host = new WebHostBuilder().UseKestrel().UseStartup<Startup>().Build();
  // After
  var builder = WebApplication.CreateBuilder(args);
  var app = builder.Build();
  app.Run();
  ```
- **`IActionContextAccessor` obsolete** — access `ActionContext` via DI or `HttpContext` instead
- **OpenAPI tooling**: `WithOpenApi()` deprecated; `<IncludeOpenAPIAnalyzers>` MSBuild property removed; `Microsoft.Extensions.ApiDescription.Client` deprecated
- **`IPNetwork` migration**: replace the custom ASP.NET Core `IPNetwork` type with `System.Net.IPNetwork`:
  ```csharp
  // Before
  KnownNetworks = { new IPNetwork(IPAddress.Parse("10.0.0.0"), 8) }
  // After
  KnownIpNetworks = { new System.Net.IPNetwork(IPAddress.Parse("10.0.0.0"), 8) }
  ```
- **Razor runtime compilation obsolete** (`AddRazorRuntimeCompilation()`) — rely on precompilation + `dotnet watch` for the dev inner loop instead
- **API endpoints no longer redirect to a login page** — a request to an endpoint marked via `IApiEndpointMetadata` now returns `401` directly instead of a redirect
- **Exception diagnostics**: if `IExceptionHandler.TryHandleAsync` returns `true`, the diagnostics middleware no longer emits its own diagnostic event — ensure handlers explicitly log anything security-relevant

### Microsoft.OpenApi v2.x Namespace Restructuring

All types previously under `Microsoft.OpenApi.Models` (`OpenApiSchema`, `OpenApiParameter`, `OpenApiResponse`, `OpenApiSecurityScheme`, etc.) move to the root `Microsoft.OpenApi` namespace.

- `using Microsoft.OpenApi.Models;` → `using Microsoft.OpenApi;`
- `OpenApiString`/`OpenApiAny` removed — use `System.Text.Json.Nodes.JsonNode`
- `OpenApiSecurityScheme.Reference` → `OpenApiSecuritySchemeReference`
- Collections on response/schema objects are now nullable — null-check before use, e.g. `operation.Responses ??= new OpenApiResponses();`
- `OpenApiSchema.Nullable` removed (OpenAPI 3.1 represents nullability via type arrays instead)
- Security requirement scopes need `List<string>` — call `.ToList()` where an array was used before

## EF Core 10

- **Multi-targeted projects**: `dotnet ef` commands now require `--framework net10.0` explicitly when the project targets more than one TFM
- **Connection string application name**: EF now injects version info into the connection string by default — set an explicit `Application Name` if this creates unwanted separate connection pools or leaks version info into logs
- **JSON column mapping**: on Azure SQL / compatibility level 170+, columns previously mapped as `nvarchar(max)` now use the native `json` type — revert via explicit `HasColumnType("nvarchar(max)")` if needed
- **`.Contains()` collection parameters**: now generates multiple parameters instead of `OPENJSON` — revert with `o.UseParameterizedCollectionMode(ParameterTranslationMode.Parameter)` if large collections cause issues
- **`ExecuteUpdateAsync` lambda signature**: changed from `Expression<Func<...>>` to `Action<...>` — dynamic setter code building expression trees manually can be simplified
- **Complex type column naming**: duplicate property names across complex types now get numeric suffixes, and nested paths use full dotted paths (e.g. `Complex_NestedComplex_Property`) — use `HasColumnName()` to keep legacy column names
- **Microsoft.Data.Sqlite date/time handling (high impact)**: textual timestamps without offsets are now treated as UTC (not local); `DateTimeOffset` written to `REAL` columns is converted to UTC; `GetDateTime` with offsets returns UTC-converted values. Mitigate with `AppContext.SetSwitch("Microsoft.Data.Sqlite.Pre10TimeZoneHandling", true)` only as a stopgap — prefer auditing and fixing the actual date/time assumptions.

## Runtime Behavioral Changes

- Automatic SIGTERM signal handling removed — register `PosixSignalRegistration`/`AppDomain.ProcessExit` handlers explicitly if graceful shutdown depended on it
- `BackgroundService` startup sequencing changed — verify ordering assumptions against other hosted services
- Configuration null-value handling updated — re-check code paths that distinguish "key absent" from "key present but null"

## Infrastructure

- Update Docker base images to `mcr.microsoft.com/dotnet/*:10.0`
- Update CI/CD SDK version pins and `global.json`
