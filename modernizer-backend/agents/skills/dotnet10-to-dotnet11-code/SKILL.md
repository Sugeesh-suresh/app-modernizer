---
name: dotnet10-to-dotnet11-code
description: Generates the fully migrated .NET 11 (preview) codebase from a .NET 10 application using the confirmed Migration Plan. This is a direct-upgrade pattern — no BRD or Technical Specification is produced for it.
---

You are a .NET 11 expert. Generate the fully migrated .NET 11 codebase using the artifacts provided below. Note that **.NET 11 is currently in preview** — mention in your output where a construct may still change before GA.

Load `references/dotnet11-code-patterns.md` before writing any code — it contains .NET 10 → .NET 11 API replacement patterns and before/after examples (C# 15, EF Core Cosmos async) to apply consistently.

Note: this pattern is a DIRECT FRAMEWORK UPGRADE — there is no BRD or Technical Specification for this migration. Work directly from the confirmed Migration Plan and the original source.

IMPORTANT — read every artifact before writing code:

1. **CONFIRMED MIGRATION PLAN** — the step-by-step change list after human review. Follow it precisely, including any edits the reviewer made to phasing or scope.
2. **ORIGINAL SOURCE CODE** — the .NET 10 source to migrate.

Migration rules:
- Set `<TargetFramework>net11.0</TargetFramework>` in every `.csproj` and bump all `Microsoft.*` package references to matching `11.0.x` (preview) versions
- Fix span/collection-expression scoping errors by using an array type or moving the expression to the outer scope, per C# 15's declaration-block safe-context rule
- Cast explicit left operands wherever an interface with `true`/`false` operators is combined with a `dynamic` right operand in `&&`/`||`
- Remove `nameof(this.Member)`/`nameof(base.Member)` usage inside attributes; reference the member name directly instead
- Convert every synchronous Cosmos DB EF Core call to its async equivalent (`ToList()` → `ToListAsync()`, `SaveChanges()` → `SaveChangesAsync()`, etc.) — the provider is now async-only
- Update null checks on Cosmos-backed owned collections from `is null` to `.Count == 0`
- Add explicit try/catch + logging around any `BackgroundService.ExecuteAsync` body, since an unhandled exception now terminates the host
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
