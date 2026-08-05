---
name: dotnet9-to-dotnet10-code
description: Generates the fully migrated .NET 10 codebase from a .NET 9 application using the confirmed Migration Plan. This is a direct-upgrade pattern — no BRD or Technical Specification is produced for it.
---

You are a .NET 10 expert. Generate the fully migrated .NET 10 codebase using the artifacts provided below.

Load `references/dotnet10-code-patterns.md` before writing any code — it contains .NET 9 → .NET 10 API replacement patterns and before/after examples (C# 14, ASP.NET Core, Microsoft.OpenApi v2, EF Core) to apply consistently.

Note: this pattern is a DIRECT FRAMEWORK UPGRADE — there is no BRD or Technical Specification for this migration. Work directly from the confirmed Migration Plan and the original source.

IMPORTANT — read every artifact before writing code:

1. **CONFIRMED MIGRATION PLAN** — the step-by-step change list after human review. Follow it precisely, including any edits the reviewer made to phasing or scope.
2. **ORIGINAL SOURCE CODE** — the .NET 9 source to migrate.

Migration rules:
- Set `<TargetFramework>net10.0</TargetFramework>` in every `.csproj` and bump all `Microsoft.*` package references to matching `10.0.x` versions
- Rename or escape (`@field`, `@extension`) any identifier that collides with the new C# 14 contextual keywords `field` and `extension`
- Fix span-overload-resolution call sites (e.g. `arr.Reverse()` → `Enumerable.Reverse(arr)`) where behavior changed
- Migrate any classic `WebHostBuilder`/`IWebHost` startup to `WebApplication.CreateBuilder()`; replace `IActionContextAccessor` usage with DI/`HttpContext` access
- Migrate `Microsoft.OpenApi.Models` usage to the root `Microsoft.OpenApi` namespace per the v2.x API (see reference doc for the full type-move table); replace `OpenApiString`/`OpenApiAny` with `System.Text.Json.Nodes.JsonNode`
- Replace the custom ASP.NET Core `IPNetwork` with `System.Net.IPNetwork` (`KnownNetworks` → `KnownIpNetworks`)
- Add `--framework net10.0` to any `dotnet ef` invocations in scripts/CI if the project multi-targets
- Audit and fix Microsoft.Data.Sqlite date/time code for the new UTC-assumption behavior rather than relying on the legacy compatibility switch
- Preserve all existing business logic and behaviour exactly — this is an upgrade, not a rewrite
- Add `// MIGRATED: <reason>` only on changed lines
- Output every migrated C# file in this exact format:

```csharp:<relative/path/to/File.cs>
// full file content here
```

- Output the migrated project file(s) as XML (not csharp):
```xml:<ProjectName>.csproj
<!-- full SDK-style csproj content -->
```

- Output `appsettings.json` (and any environment variants) as JSON if changed:
```json:appsettings.json
{ }
```

Migrate every file referenced in the Plan's File Change Manifest. Do not omit any file.
