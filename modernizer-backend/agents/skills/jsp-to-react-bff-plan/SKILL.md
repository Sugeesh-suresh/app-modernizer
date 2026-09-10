---
name: jsp-to-react-bff-plan
description: Designs the target React + Spring Boot 4 BFF architecture and produces file manifests for both the backend/ and frontend/ trees, from the confirmed BRD and Technical Specification (which already contains the frontend/backend classification table).
---

You are a decoupled-architecture designer. Create a detailed `plan.md` for transforming this JSP monolith into a React frontend talking to a Spring Boot 4 Backend-For-Frontend (BFF), using the confirmed BRD and Technical Specification below — the classification table in the Technical Specification already tells you what's frontend vs backend; your job here is to turn that classification into a concrete architecture and file manifest for both target trees.

Load `references/bff-architecture-checklist.md` for the BFF design rules and the WAR→JAR packaging checklist.

# Migration Plan: JSP → React + Spring Boot 4 BFF

## Overview
Current state (page count, servlet count, session usage summary) and target state (a `frontend/` React app calling a `backend/` Spring Boot 4 BFF, packaged as a standalone JAR — no more WAR, no more external servlet container dependency).

## BFF API Contract
The authoritative list of every REST endpoint the BFF will expose, derived directly from the classification table's Backend rows. For each: `Method | Path | Request Shape | Response Shape | Backing Logic (which classified unit it wraps) | Auth Requirement`. Group endpoints by the page/flow they serve. This table is what `spring-boot-bff-generate` and `react-frontend-generate` both build against — it must be internally consistent (every endpoint the frontend plan calls must appear here with a matching shape).

## Session & Auth Strategy
From the Technical Specification's Session/State Reconciliation Plan: the concrete mechanism (BFF-managed server-side session with a session cookie the browser still carries automatically, or a token-based approach) and exactly which BFF endpoints establish/refresh/consume it.

## React Page/Component Map
For each legacy JSP page: the React page it becomes, the shared components it's composed of (from the classification table's Frontend rows and the JSP facts' Includes), and which BFF endpoint(s) it calls on mount/on submit. Note any page whose full-reload form-postback behaviour becomes a single-page, no-reload interaction (call out these behavioural improvements explicitly, per `jsp-logic-classifier`'s guidance).

## Backend File Manifest (workspace subdir `backend/`)
Every file to generate: `pom.xml` (packaging **jar**, standard Spring Boot 4 parent, embedded Tomcat, no `provided` scoping — this is a greenfield standalone JAR, not a WAR-preserving migration), the `@SpringBootApplication` main class (plain `SpringApplication.run`, no `SpringBootServletInitializer` needed), one controller class per API contract group, one service class per business-logic group from the classification table, DTOs/records for every request/response shape, `application.yml`.

## Frontend File Manifest (workspace subdir `frontend/`)
Every file to generate: `package.json`, routing setup, one page component per entry in the React Page/Component Map, shared components, an API client module matching the BFF contract exactly (one function per endpoint), and any client-side-only state (per classification Rule 5) implemented as local component state — do not invent a global state library unless the classification table shows genuinely cross-page shared client state.

## Validation & Rollout
Real build validation happens automatically in build_loop (`mvn compile` in `backend/`, `npm run build` in `frontend/`, iterated with the fixer) — this section covers what's outside that: manual end-to-end smoke test of each migrated flow, side-by-side behavioural comparison against the original JSP app, rollback strategy (keep the JSP app deployable until the React+BFF replacement is verified).

## Estimated Effort

Use markdown with task checkboxes `- [ ]` for every actionable item in both manifests — they are what `backend_generator_agent` and `frontend_generator_agent` will work through file-by-file.
