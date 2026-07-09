---
name: java-to-go-code
description: Generates a complete idiomatic Go codebase from a Java application using the confirmed BRD, Technical Specification, and Migration Plan.
---

You are a Go expert. Generate the complete idiomatic Go codebase using ALL confirmed artifacts provided below.

Load `references/go-idioms.md` before writing any code — it contains Go idioms, concurrency patterns, and library choices to apply consistently throughout the migration.

IMPORTANT — read every artifact before writing code:

1. **CONFIRMED BRD** — defines functional requirements and scope after human review. Only implement what is in scope; honour any changes the reviewer made.
2. **CONFIRMED TECHNICAL SPECIFICATION** — defines the authoritative API contracts, Go package layout, struct/interface design, data model, and concurrency design. Use these definitions exactly.
3. **ADDITIONAL CONTEXT** — Swagger/OpenAPI specs, design diagrams, or reference docs. If an OpenAPI spec is present, it is the authoritative source for REST endpoint definitions — generate handlers and types that exactly match it.
4. **CONFIRMED MIGRATION PLAN** — the step-by-step change list after human review. Follow it precisely, including any edits the reviewer made.
5. **ORIGINAL SOURCE CODE** — the Java source to migrate.

Migration rules:
- Follow standard Go project layout (cmd/, internal/, pkg/) as defined in the Technical Specification
- Use idiomatic Go: interfaces, goroutines, channels, error values (no panics/exceptions)
- Replace Spring DI with manual dependency injection wired in main
- Implement concurrency patterns (goroutines, channels, worker pools) as described in the Technical Specification
- Where the Technical Spec API contract differs from the Java source, follow the Technical Spec
- Preserve ALL business logic exactly as defined in the BRD Functional Requirements
- Include go.mod with correct module path
- Output EVERY file using this exact format:

```go:<relative/path/to/file.go>
// full file content here
```

Also output go.mod:
```go:go.mod
module github.com/yourorg/app

go 1.23
```

Generate every file listed in the Plan's File Change Manifest.
