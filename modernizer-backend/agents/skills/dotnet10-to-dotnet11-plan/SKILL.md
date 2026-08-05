---
name: dotnet10-to-dotnet11-plan
description: Analyses a .NET 10 codebase directly and produces a detailed migration plan (plan.md) for upgrading to .NET 11 (currently in preview). This is a direct-upgrade pattern — there is no separate reverse-engineering / BRD phase.
---

You are a .NET upgrade expert. This is a DIRECT FRAMEWORK UPGRADE — there is no reverse-engineering, Analysis, or BRD phase for this pattern. Analyse the provided .NET 10 source code directly and produce a detailed `plan.md` for upgrading it to .NET 11.

Note in the plan's Overview that **.NET 11 is in preview** (this checklist covers breaking changes through Preview 3) — flag that final validation should be re-run once .NET 11 GA ships and packages are re-pinned to the GA release versions.

Load `references/dotnet11-migration-checklist.md` to identify breaking changes (C# 15 compiler, EF Core, runtime/hardware requirements), obsoletions, and .NET 11 features to adopt.

# Migration Plan: .NET 10 → .NET 11 (Preview)

## Overview
  - Project type(s) found (ASP.NET Core, EF Core, WinForms/WPF, console/worker service, class library), current `TargetFramework`, key NuGet dependencies pinned to 10.x, and a note that .NET 11 is currently pre-release
## Pre-requisites
  - .NET 11 SDK (preview), a clean baseline build on `net10.0` before starting
## Phase 1: Target Framework & Package Updates
  - Change `<TargetFramework>` to `net11.0` in every `.csproj`
  - Bump all `Microsoft.*` package references to matching 11.0.x (preview) versions; run `dotnet restore` and collect the resulting build errors
## Phase 2: C# 15 Compiler Fixes
  - Fix span/`ReadOnlySpan` collection-expression scoping errors where a span was assigned from an inner block to an outer-scoped variable
  - Add the required `InAttribute` reference (or restructure) anywhere a synthesized `ref readonly` delegate type now fails with CS0518
  - Cast the left operand explicitly wherever an interface with `true`/`false` operators is combined with a `dynamic` right operand in `&&`/`||`
  - Remove any `nameof(this.Member)`/`nameof(base.Member)` usage inside attributes (no longer permitted)
  - Review any `with(...)` usage inside a collection expression — now parsed as constructor arguments rather than a method call
## Phase 3: Runtime & Infrastructure Behavioral Changes
  - Verify compression code — header-writing behavior changed
  - Verify TAR archive handling — checksum validation is now stricter
  - Confirm target/build machines meet the new minimum hardware requirement (x86-64-v2) if deploying to older hardware or constrained VM SKUs
  - Ensure any `BackgroundService` implementation has explicit exception handling — an unhandled exception now terminates the host instead of being silently swallowed
## Phase 4: EF Core 11
  - Convert every synchronous Cosmos DB call (`ToList()`, `First()`, `SaveChanges()`, etc.) to its async equivalent — the Cosmos provider is now async-only
  - Update null checks on Cosmos-backed owned collections — empty collections now return `[]` instead of `null`
  - Add an explicit `Microsoft.EntityFrameworkCore.Design` package reference if it was previously relied upon transitively
  - Review any `SqlVector<T>` usage — no longer included in `SELECT *` by default
## Phase 5: Infrastructure
  - Update Docker base images, CI/CD SDK pins, and `global.json` to a .NET 11 preview build; plan to re-pin to GA once released
## Phase 6: Validation & Rollout
  - Full build/test run focused on compression, TAR handling, EF Core async paths, and certificate validation
  - Rollback strategy, with explicit note that this upgrade targets a preview SDK
## Estimated Effort (story points per phase and total)
## File Change Manifest (every file that needs to change, with target file name)

Use markdown with task checkboxes `- [ ]` for every actionable item.
