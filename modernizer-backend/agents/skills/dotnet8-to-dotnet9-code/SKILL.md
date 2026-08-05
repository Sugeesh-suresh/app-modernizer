---
name: dotnet8-to-dotnet9-code
description: Generates the fully migrated .NET 9 codebase from a .NET 8 application using the confirmed Migration Plan. This is a direct-upgrade pattern — no BRD or Technical Specification is produced for it.
---

You are a .NET 9 expert. Generate the fully migrated .NET 9 codebase using the artifacts provided below.

Load `references/dotnet9-code-patterns.md` before writing any code — it contains .NET 8 → .NET 9 API replacement patterns and before/after examples (C# 13 fixes, ASP.NET Core, EF Core) to apply consistently.

Note: this pattern is a DIRECT FRAMEWORK UPGRADE — there is no BRD or Technical Specification for this migration. Work directly from the confirmed Migration Plan and the original source.

IMPORTANT — read every artifact before writing code:

1. **CONFIRMED MIGRATION PLAN** — the step-by-step change list after human review. Follow it precisely, including any edits the reviewer made to phasing or scope.
2. **ORIGINAL SOURCE CODE** — the .NET 8 source to migrate.

Migration rules:
- Set `<TargetFramework>net9.0</TargetFramework>` in every `.csproj` and bump all `Microsoft.*` package references to matching `9.0.x` versions
- Fix C# 13 compiler breaks: convert `[InlineArray]` `record struct` to plain `struct`; add `unsafe` to iterator-nested local functions that need it; resolve `params ReadOnlySpan<T>` overload ambiguities with explicit casts
- Replace SYSLIB0054–SYSLIB0057-obsoleted APIs (`Thread.Volatile*` → `Volatile`/`Interlocked`; old `X509Certificate` constructors → `X509CertificateLoader`) with their replacements
- Remove any remaining `BinaryFormatter` usage — it now always throws at runtime; migrate to `System.Text.Json` or a supported serializer
- Fix code that casts an `HttpClientFactory`-created client's handler to `HttpClientHandler` (now `SocketsHttpHandler` by default)
- Remove explicit transactions wrapped around EF Core `Migrate()`/`MigrateAsync()` calls; replace non-deterministic `HasData()` values (e.g. `DateTime.UtcNow`) with fixed literals to avoid the "pending model changes" migration error
- Audit and fix any code relying on floating-point-to-integer wraparound (now saturates on x86/x64)
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
