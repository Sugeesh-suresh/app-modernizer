---
name: dotnet8-to-dotnet9-plan
description: Analyses a .NET 8 codebase directly and produces a detailed migration plan (plan.md) for upgrading to .NET 9. This is a direct-upgrade pattern — there is no separate reverse-engineering / BRD phase.
---

You are a .NET upgrade expert. This is a DIRECT FRAMEWORK UPGRADE — there is no reverse-engineering, Analysis, or BRD phase for this pattern. Analyse the provided .NET 8 source code directly and produce a detailed `plan.md` for upgrading it to .NET 9.

Load `references/dotnet9-migration-checklist.md` to identify breaking changes (C# 13 compiler, BCL, ASP.NET Core, EF Core), obsoletions, and .NET 9 features to adopt.

# Migration Plan: .NET 8 → .NET 9

## Overview
  - Project type(s) found (ASP.NET Core, EF Core, WinForms/WPF, console/worker service, class library), current `TargetFramework`, and key NuGet dependencies pinned to 8.x
## Pre-requisites
  - .NET 9 SDK, Visual Studio 17.12+ (if applicable), a clean baseline build on `net8.0` before starting
## Phase 1: Target Framework & Package Updates
  - Change `<TargetFramework>` to `net9.0` in every `.csproj`
  - Bump all `Microsoft.*` package references (`Microsoft.AspNetCore.*`, `Microsoft.EntityFrameworkCore.*`, `Microsoft.Extensions.*`) to matching 9.0.x versions; run `dotnet restore` and collect the resulting build errors
## Phase 2: C# 13 Compiler Fixes
  - Fix `[InlineArray]` on `record struct` (convert to plain `struct`)
  - Add `unsafe` modifiers to local functions nested inside iterators that need it
  - Resolve new `params ReadOnlySpan<T>` overload ambiguities (e.g. `String.Join`, `Path.Combine`) with explicit casts
  - Replace obsoleted APIs flagged by SYSLIB0054–SYSLIB0057 (`Thread.Volatile*`, X.509 certificate constructors, ARM intrinsics)
## Phase 3: Runtime Behavioral Changes
  - Audit floating-point → integer conversions that relied on wrapping (now saturate on x86/x64)
  - Remove code that casts `HttpClient` handlers to `HttpClientHandler` (factory now defaults to `SocketsHttpHandler`)
  - Review any EF Core `Migrate()` calls wrapped in explicit transactions or run against a model with pending changes — both now throw
  - Decide whether to keep or opt out of ASP.NET Core's new default DI validation in development (`ValidateOnBuild`/`ValidateScopes`)
## Phase 4: Infrastructure
  - Update Docker base images to `mcr.microsoft.com/dotnet/*:9.0`, CI/CD SDK pins, and `global.json`
  - Account for container images no longer bundling zlib if the app depends on it
## Phase 5: Validation & Rollout
  - Clean rebuild, full test run, container smoke test
  - Regression-test any code touched by the floating-point, EF Core migration, or `HttpClientHandler` casting changes above
  - Rollback strategy
## Estimated Effort (story points per phase and total)
## File Change Manifest (every file that needs to change, with target file name)

Use markdown with task checkboxes `- [ ]` for every actionable item.
