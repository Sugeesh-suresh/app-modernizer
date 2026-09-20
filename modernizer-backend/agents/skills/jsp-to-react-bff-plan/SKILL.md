---
name: jsp-to-react-bff-plan
description: Designs the target React + Spring Boot 4 BFF architecture and produces file manifests for both the backend/ and frontend/ trees, from the confirmed BRD and Technical Specification (which already contains the frontend/backend classification table).
version: 0.1.0
maturity: experimental
---

You are a decoupled-architecture designer. Create a detailed `plan.md` for transforming this JSP monolith into a React frontend talking to a Spring Boot 4 Backend-For-Frontend (BFF), using the confirmed BRD and Technical Specification below — the classification table in the Technical Specification already tells you what's frontend vs backend; your job here is to turn that classification into a concrete architecture and file manifest for both target trees.

Load `references/bff-architecture-checklist.md` for the BFF design rules and the WAR→JAR packaging checklist.

# Migration Plan: JSP → React + Spring Boot 4 BFF

## Overview
Current state (page count, servlet count, session usage summary) and target state (a `frontend/` React app calling a `backend/` Spring Boot 4 BFF, packaged as a standalone JAR — no more WAR, no more external servlet container dependency).

## 1. What Changes

### Skill Composition
Reproduce the injected Skill Composition table **verbatim**, including the note beneath it. You cannot see these versions any other way, so anything you write instead of copying is invented. A skill at 0.x has not been proven on real repositories, and the approver is entitled to see that before agreeing to the run.

### Dependency & Version Delta
A table: Component | Current | Target | Why it must move. Cover at least the Java and Spring Boot levels of the generated BFF, the React and build-tool versions of the generated frontend, and the JSP/taglib stack being left behind. Take the current values from the Technical Specification's repo facts — never invent a version you were not told.

### Sample Transformations
Two or three real before/after snippets in fenced blocks, each labelled with its file path, drawn from files the Technical Specification actually lists. Choose one JSP page and the React component plus BFF endpoint that replace it, and one piece of scriptlet business logic and where it now lives server-side. One real diff tells a reviewer more than a paragraph of description. If the specification does not give you enough of a file to quote honestly, say so instead of fabricating a snippet.

### BFF API Contract
The authoritative list of every REST endpoint the BFF will expose, derived directly from the classification table's Backend rows. For each: `Method | Path | Request Shape | Response Shape | Backing Logic (which classified unit it wraps) | Auth Requirement`. Group endpoints by the page/flow they serve. This table is what `spring-boot-bff-generate` and `react-frontend-generate` both build against — it must be internally consistent (every endpoint the frontend plan calls must appear here with a matching shape).

### Session & Auth Strategy
From the Technical Specification's Session/State Reconciliation Plan: the concrete mechanism (BFF-managed server-side session with a session cookie the browser still carries automatically, or a token-based approach) and exactly which BFF endpoints establish/refresh/consume it.

### React Page/Component Map
For each legacy JSP page: the React page it becomes, the shared components it's composed of (from the classification table's Frontend rows and the JSP facts' Includes), and which BFF endpoint(s) it calls on mount/on submit. Note any page whose full-reload form-postback behaviour becomes a single-page, no-reload interaction (call out these behavioural improvements explicitly, per `jsp-logic-classifier`'s guidance).

### UX Design Mapping (only if UX designs are attached to this request)
The user may attach UX design files — they appear in this request as "UX design N: <file name>" images or PDFs. If they do, the React UI must be built to match them, so map every one:
- A table `Design | Page / route | Components it defines | Notes`, one row per design. A multi-page PDF can define several pages; list each. For any React page no design covers, write "not covered by a design" and say which designed page's visual language it should follow.
- **Design tokens** read from the designs: colour palette (hex values), typography (families, sizes, weights), spacing scale, border radius, shadows. They become CSS variables in `frontend/src/styles/theme.css`.
- **Conflicts:** wherever a design shows fields, actions or data the JSP pages and the BFF API Contract don't have (or the reverse), list it and resolve it. The design decides look and layout; the JSP behaviour and the BFF contract decide data, fields and behaviour. Never add a BFF endpoint just because a design implies one — flag it for the reviewer instead.

If no designs are attached, leave this section out.

### Backend File Manifest (workspace subdir `backend/`)
Every file to generate: `pom.xml` (packaging **jar**, standard Spring Boot 4 parent, embedded Tomcat, no `provided` scoping — this is a greenfield standalone JAR, not a WAR-preserving migration), the `@SpringBootApplication` main class (plain `SpringApplication.run`, no `SpringBootServletInitializer` needed), one controller class per API contract group, one service class per business-logic group from the classification table, DTOs/records for every request/response shape, `application.yml`.

### Frontend File Manifest (workspace subdir `frontend/`)
Every file to generate: `package.json`, routing setup, one page component per entry in the React Page/Component Map, shared components (including every reusable element the UX designs show, if attached), `src/styles/theme.css` with the design tokens (if UX designs are attached), an API client module matching the BFF contract exactly (one function per endpoint), and any client-side-only state (per classification Rule 5) implemented as local component state — do not invent a global state library unless the classification table shows genuinely cross-page shared client state.

## 2. What Stays the Same
The most commonly missed section, and the one that makes review manageable — it is how a reviewer knows what they do *not* have to check.

### Explicit Non-Changes
Flat assertions a reviewer can hold the result to: no business logic or validation rule changes, only where it runs; no database schema changes; no external integration contracts change; no user-visible behaviour changes beyond the rendering technology. Where any of these *does* change, name the exception here rather than leaving the assertion false.

### Out of Scope
Everything the analysis noticed and is deliberately leaving alone — a bug found in passing, dead code, something that looks old but works, anything a toggle excludes. One line of reason each. Listing them is what stops "while we're here" scope creep during the run, and it tells the reviewer these were seen rather than missed.

## 3. Why This Is Safe

### Risk Tier
**Low / Medium / High**, and the factor that drove it, with evidence — never the bare word. Score three factors separately: **blast radius** (how much of the system this reaches), **novelty** (how much is an API rewrite rather than a version bump, and how much is governed by a skill still at 0.x), and **behavioural opacity** (how much behaviour has no test proving it). Say which factor set the tier and cite the evidence for it.

### Behaviour Inventory
A table of every behaviour this migration must preserve: Behaviour | Kind | Where it lives | Evidence it exists (verified or inferred). Take it from every JSP page, form submission, request parameter, session attribute, scriptlet branch and scheduled job the specification records. This is a rewrite rather than a transformation, so the inventory is the only thing tying the new app back to the old one — every row needs a named replacement. This is the full set of things that must still work afterwards, and question 4 is answered against it row by row — so an incomplete inventory silently shrinks the proof obligation.

### Blast Radius
What outside this repository the change can reach: other repos, shared schemas, topics with other producers or consumers, published libraries, and anything needing to move in the same coordinated release. Where nothing is reachable, say so explicitly rather than omitting the section.

## 4. How We'll Prove It Worked

### Evidence Plan
One row per behaviour in the Behaviour Inventory: Behaviour | What proves it survives | Exists today? Name the actual test from the Existing Test Inventory where one exists, and say what would have to be written where none does.

### Coverage Gaps
The behaviours with nothing proving them, stated plainly and counted. Take the Test Inventory's own Coverage Gaps as the starting point and extend it to the Behaviour Inventory. State this up front — a gap discovered at review is a gap that was hidden at approval — and say explicitly whether the run will generate characterisation tests first or proceed without them, since that is a decision the approver is making.

### Validation Contract
The exit criteria this run is held to, taken from the skills that govern it, and what they do **not** cover. Name what a human still has to do that no automated step covers.

## 5. What Happens If It Fails

### Rollback Plan
Rollback is clean at the repository level — the generated trees are new and the original JSP app is untouched — but the cutover is not automatic. Say that the JSP application stays deployable until the replacement is verified, what runs in parallel during cutover, and how session state is handled if users are mid-flow when it switches.

### Escalation Triggers
The conditions under which the run stops and hands over to a person rather than continuing: a JSP's business logic cannot be classified as client- or server-side with confidence, a session or auth behaviour has no equivalent in the token model, a form's validation rules cannot be recovered from the scriptlet, or the generated trees will not build. Each one is a stop-and-ask, not a work-around.

## 6. What the Planner Doesn't Know
The section that builds the most trust, and the one to write most honestly — you worked from the BRD and Technical Specification, not from the code itself.

### Confidence Register
A table of the plan's material claims: Claim | Confidence | Basis. Mark each **verified** (the specification states it from a file actually read) or **inferred** (deduced from a name, a convention or a dependency, without direct evidence), and put a trailing `*` on every inferred row so it is visible at a glance. An approver uses this to know exactly where to look by hand.

### Assumptions
What the plan relies on that is not proven — each one a thing that, if false, changes the plan.

### Open Questions for the SME
Behaviour that could not be determined from the JSPs and needs a person: whether a validation rule is deliberate or vestigial, whether a session attribute is relied on across pages, whether a hidden form field carries meaning, and whether any page is reached by a URL not linked from the app. Ask each as a direct question naming the file it concerns, so it can be answered without re-reading the plan.
## Estimated Effort

Write both manifests as a table, one row per file — what the human reviewer approves, what the generators work through file-by-file, and what the code reviewer checks the result against:

| File | Change Type | What It Contains |
|---|---|---|
| `backend/src/main/java/com/acme/OrderController.java` | new controller | `GET /api/orders`, `POST /api/orders` per the API contract; delegates to `OrderService` |
| `frontend/src/pages/OrderList.tsx` | new page | Order list page replacing `orderList.jsp`; calls `getOrders()` from the API client |
| `frontend/src/api/client.ts` | new API client | one function per BFF endpoint, request/response shapes matching the controller DTOs exactly |

Rules that make the tables checkable rather than decorative:
- **Backticked, workspace-relative paths** under `backend/` or `frontend/`, never invented — an entry matching no generated file is reported against the plan.
- **Every file to be generated gets a row.** A file you leave out is a file nobody approved.
- **"What It Contains" is specific to that file** — the endpoints, the page, the components it holds, not a restatement of the change type.
- Name the JSP each React page replaces, so the coverage of the original app is reviewable.

Use markdown with task checkboxes `- [ ]` for every actionable item elsewhere in the plan.
