# .NET 10 → .NET 11 Migration Checklist (Preview)

Source: distilled from the `dotnet/skills` `migrate-dotnet10-to-dotnet11` reference set (C# compiler, EF Core). **.NET 11 is currently in preview** — this checklist reflects breaking changes through Preview 3 and should be re-validated against the GA release.

## Target Framework & SDK

```xml
<!-- Before -->
<TargetFramework>net10.0</TargetFramework>

<!-- After -->
<TargetFramework>net11.0</TargetFramework>
```
Bump every `Microsoft.*` package reference to the matching `11.0.x` (preview) version.

## C# 15 Compiler Breaking Changes

| Change | Before | After |
|---|---|---|
| Span/`ReadOnlySpan` collection-expression safe-context now enforces declaration-block scope | ```scoped Span<int> outer = default; foreach (var x in vals) { Span<int> items = [x]; outer = items; } // error``` | Use an array type instead (converts implicitly to `Span<T>`), or move the expression to the outer scope: `int[] items = [x];` |
| `ref readonly` synthesized delegates require `InAttribute` | Delegate type generation fails with CS0518 if `System.Runtime.InteropServices.InAttribute` isn't available | Ensure the reference assembly containing `InAttribute` is available, or avoid the implicit delegate synthesis |
| Interface `true`/`false` operators + `dynamic` right operand in `&&`/`||` | `I1 x = new C1(); dynamic y = new C1(); _ = x && y;` (error CS7083) | Cast explicitly: `_ = (C1)x && y;` |
| `nameof(this.Member)` / `nameof(base.Member)` in attributes | `[MyAttr(nameof(this.Foo))]` | Not allowed — reference the member name directly or restructure: `[MyAttr(nameof(Foo))]` |
| `with(...)` inside collection expressions | Previously could be read as a method call | Now parsed as constructor arguments — verify any code using this shape still compiles to the intended construct |

## Runtime & Infrastructure Behavioral Changes

- **Compression**: header-writing behavior changed — re-test any code that manually inspects or generates compression headers
- **TAR archives**: checksum validation is stricter — archives that previously passed loosely-validated checksums may now be rejected
- **Minimum hardware requirement raised to x86-64-v2** — confirm target deployment hardware/VM SKUs meet this before upgrading
- **`BackgroundService` unhandled exceptions now terminate the host** (previously could be silently swallowed depending on configuration) — audit every `BackgroundService` implementation for proper try/catch and logging around `ExecuteAsync`

## EF Core 11

- **Cosmos DB provider is now async-only** — every synchronous call throws:
  ```csharp
  // Before
  var items = context.Items.ToList();
  context.SaveChanges();
  // After
  var items = await context.Items.ToListAsync();
  await context.SaveChangesAsync();
  ```
  Common conversions: `ToList()` → `ToListAsync()`, `First()`/`FirstOrDefault()` → `FirstAsync()`/`FirstOrDefaultAsync()`, `SaveChanges()` → `SaveChangesAsync()`.
- **Cosmos owned collections**: an entity's owned collection with no items now returns an empty collection instead of `null` — update `if (entity.Items is null)` checks to `if (entity.Items.Count == 0)`
- **`Migrate()` throws when no migrations exist** — suppress via `ConfigureWarnings()` if the app intentionally calls `Migrate()` on a migration-less context
- **`Microsoft.EntityFrameworkCore.Design`** must now be referenced explicitly if the project previously relied on it transitively
- **MSBuild property rename**: `EFOptimizeContext` → replaced by `EFScaffoldModelStage` and `EFPrecompileQueriesStage`
- **`SqlVector<T>` properties** are excluded from `SELECT *` by default — add explicit projections to include them
- **`Microsoft.Data.SqlClient` 7.0**: Entra ID dependencies removed from the base package — add `Microsoft.Data.SqlClient.Extensions.Azure` if Entra ID authentication is used
- **SQLite encryption**: built-in encryption bundles removed — migrate to SQLCipher or the `SQLite3MultipleCiphers` NuGet package if database encryption is in use

## Infrastructure

- Update Docker base images and CI/CD SDK pins to a .NET 11 preview build (and plan to re-pin once GA ships)
- Update `global.json` to the preview SDK version in use
