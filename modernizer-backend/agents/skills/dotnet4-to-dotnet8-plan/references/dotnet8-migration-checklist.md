# .NET Framework 4.x → .NET 8 Migration Checklist

## Project File (.csproj) Conversion

**Before (legacy, .NET Framework 4.8):**
```xml
<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <TargetFrameworkVersion>v4.8</TargetFrameworkVersion>
    <OutputType>Library</OutputType>
  </PropertyGroup>
  <ItemGroup>
    <Reference Include="Newtonsoft.Json, Version=12.0.0.0, ..." />
  </ItemGroup>
  <ItemGroup>
    <Compile Include="Services\OrderService.cs" />
    <Compile Include="Models\Order.cs" />
  </ItemGroup>
</Project>
```

**After (SDK-style, .NET 8):**
```xml
<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
  </ItemGroup>
</Project>
```
Note: SDK-style projects auto-include all `.cs` files under the project directory — explicit `<Compile Include>` entries are no longer needed.

## APIs Removed or Unavailable in .NET 8

| API / Feature | Status | Replacement |
|---|---|---|
| `System.Web` (ASP.NET classic: `HttpContext.Current`, `HttpModule`, `HttpHandler`) | Not available | ASP.NET Core middleware, `IHttpContextAccessor` |
| WCF server-side (`System.ServiceModel`) | Not available | ASP.NET Core gRPC, Web API, or `CoreWCF` (community port) |
| .NET Remoting | Removed | gRPC or REST |
| `AppDomain.CreateDomain` (plugin isolation) | Not supported | `AssemblyLoadContext` |
| Code Access Security (CAS, `[PermissionSet]`) | Removed | OS-level sandboxing / containers |
| `BinaryFormatter` | Removed (security) | `System.Text.Json`, protobuf, or `MessagePack` |
| `Enterprise Services` (COM+) | Not available | Redesign as in-process services |
| `System.Drawing.Common` (on non-Windows) | Restricted | `SkiaSharp` or `ImageSharp` |
| Web Forms (`.aspx`, `ViewState`, `Page_Load`) | Not available | Razor Pages / Blazor |

## Configuration Migration

**Before (`web.config` / `app.config`):**
```xml
<configuration>
  <appSettings>
    <add key="ApiBaseUrl" value="https://api.example.com" />
  </appSettings>
  <connectionStrings>
    <add name="Default" connectionString="Server=...;Database=...;" />
  </connectionStrings>
</configuration>
```

**After (`appsettings.json` + Options pattern):**
```json
{
  "ApiSettings": { "BaseUrl": "https://api.example.com" },
  "ConnectionStrings": { "Default": "Server=...;Database=...;" }
}
```
```csharp
// Program.cs
builder.Services.Configure<ApiSettings>(builder.Configuration.GetSection("ApiSettings"));

// Consumption via DI instead of ConfigurationManager.AppSettings["ApiBaseUrl"]
public class OrderService(IOptions<ApiSettings> apiSettings) { ... }
```

## NuGet Package Compatibility Matrix

| Package | .NET Framework Version | .NET 8 Compatible Version |
|---|---|---|
| Newtonsoft.Json | 12.x | 13.0.3+ (or migrate to `System.Text.Json`) |
| EntityFramework (EF6) | 6.x | `Microsoft.EntityFrameworkCore` 8.x (API differs — see below) |
| log4net | 2.x | 2.0.15+ (works, but prefer `Microsoft.Extensions.Logging` + `Serilog`) |
| Unity / Ninject / Autofac | any | `Microsoft.Extensions.DependencyInjection` (built-in) or Autofac 8.x |
| NUnit / MSTest | any | latest major version (test SDKs are framework-agnostic) |
| RestSharp | 106.x | 110.x+ |
| Dapper | 1.x/2.x | 2.1+ (fully compatible) |

## Entity Framework 6 → EF Core 8

| EF6 | EF Core 8 |
|---|---|
| `DbContext` + `DbSet<T>` | Same API shape, different namespace (`Microsoft.EntityFrameworkCore`) |
| `.edmx` / Database First | Reverse-engineer with `dotnet ef dbcontext scaffold` |
| `Database.SetInitializer` | `context.Database.Migrate()` + EF Core Migrations |
| Lazy loading (on by default) | Opt-in via `UseLazyLoadingProxies()` — prefer explicit `.Include()` |
| `SqlFunctions` | `EF.Functions` |

## ASP.NET → ASP.NET Core Mapping

| ASP.NET (Framework) | ASP.NET Core (.NET 8) |
|---|---|
| `Global.asax` `Application_Start` | `Program.cs` top-level statements |
| `Web.config` `<system.web>` | `Program.cs` middleware pipeline (`app.Use...`) |
| `System.Web.Mvc.Controller` | `Microsoft.AspNetCore.Mvc.Controller` (mostly source-compatible) |
| `ApiController` (Web API 2) | `ControllerBase` with `[ApiController]` |
| `HttpContext.Current.Session` | `HttpContext.Session` via `IHttpContextAccessor` |
| `[Authorize]` + Forms Authentication | `[Authorize]` + ASP.NET Core Identity / JWT Bearer |
| `IHttpModule` | Custom middleware (`app.UseMiddleware<T>()`) |
| `Bundling/Minification` (`BundleConfig`) | Front-end build tooling (Vite/webpack) or `WebOptimizer` |

## C# Language Features to Adopt (up to C# 12)

```csharp
// Nullable reference types
public string? MiddleName { get; set; }

// Records for immutable DTOs
public record OrderDto(int Id, string CustomerName, decimal Total);

// Pattern matching
var discount = customer switch
{
    { IsVip: true, YearsActive: > 5 } => 0.20m,
    { IsVip: true } => 0.10m,
    _ => 0m
};

// Primary constructors (C# 12)
public class OrderService(IOrderRepository repo, ILogger<OrderService> logger)
{
    public async Task<Order> GetAsync(int id) => await repo.FindAsync(id);
}

// Top-level statements (Program.cs)
var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllers();
var app = builder.Build();
app.MapControllers();
app.Run();
```
