---
name: dotnet9-to-dotnet10-plan
description: Analyses a .NET 9 codebase directly and produces a detailed migration plan (plan.md) for upgrading to .NET 10. This is a direct-upgrade pattern — there is no separate reverse-engineering / BRD phase.
---

You are a .NET upgrade expert. This is a DIRECT FRAMEWORK UPGRADE — there is no reverse-engineering, Analysis, or BRD phase for this pattern. Analyse the provided .NET 9 source code directly and produce a detailed `plan.md` for upgrading it to .NET 10.

Load `references/dotnet10-migration-checklist.md` to identify breaking changes (C# 14 compiler, ASP.NET Core, EF Core, SQLite), obsoletions, and .NET 10 features to adopt.

# Migration Plan: .NET 9 → .NET 10

## Overview
  - Project type(s) found (ASP.NET Core, EF Core, WinForms/WPF, console/worker service, class library), current `TargetFramework`, and key NuGet dependencies pinned to 9.x — flag any `Microsoft.OpenApi` usage specifically
## Pre-requisites
  - .NET 10 SDK, a clean baseline build on `net9.0` before starting
## Phase 1: Target Framework & Package Updates
  - Change `<TargetFramework>` to `net10.0` in every `.csproj`
  - Bump all `Microsoft.*` package references to matching 10.0.x versions; note that `Microsoft.OpenApi` moves to a restructured v2.x API — flag any direct usage for Phase 2
  - Run `dotnet restore` and collect the resulting build errors
## Phase 2: C# 14 Compiler & API Fixes
  - Rename any local variable/field literally named `field` inside a property accessor (now a contextual keyword, CS9272) or escape it with `@field`
  - Escape any type/alias/type-parameter literally named `extension` (now a contextual keyword) or rename it
  - Fix `Reverse()`/`Assert.Equal`/`MemoryMarshal.Cast` call sites whose overload resolution changed due to new built-in span conversions
  - Replace SYSLIB0058–SYSLIB0062-obsoleted APIs with their documented replacements
  - Migrate any `Microsoft.OpenApi.Models` usage to the restructured root `Microsoft.OpenApi` namespace (see checklist for the full type-move table)
## Phase 3: Runtime Behavioral Changes
  - Register explicit `POSIX` signal handlers for any code relying on the framework's automatic SIGTERM handling (removed by default)
  - Review `BackgroundService` startup ordering assumptions — sequencing changed; an unhandled exception should be expected to be handled explicitly where relied upon
  - Audit configuration binding code that distinguishes "missing key" from "key present with null value" — null handling changed
  - Review EF Core `.Contains()` LINQ translations if the app depends on the previous `OPENJSON`-based SQL shape
  - If using Microsoft.Data.Sqlite: audit `DateTime`/`DateTimeOffset` handling — all three read/write paths now assume UTC
## Phase 4: Infrastructure
  - Update Docker base images to `mcr.microsoft.com/dotnet/*:10.0`, CI/CD SDK pins, and `global.json`
## Phase 5: Validation & Rollout
  - Clean rebuild, full test run, container smoke test, security review
  - Regression-test SIGTERM/shutdown handling, `BackgroundService` startup order, and any Sqlite date/time paths touched above
  - Rollback strategy
## Estimated Effort (story points per phase and total)
## File Change Manifest (every file that needs to change, with target file name)

Use markdown with task checkboxes `- [ ]` for every actionable item.
