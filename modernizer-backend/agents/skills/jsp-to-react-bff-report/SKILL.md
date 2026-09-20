---
name: jsp-to-react-bff-report
description: Produces the final human-readable report summarising the architectural transformation -- what moved to React vs the BFF, final build status for both trees, and any remaining issues -- from the backend/frontend generation results and the final build result.
version: 0.1.0
maturity: experimental
---

You are writing the closing report for a completed JSP → React + BFF architectural migration run. You have no tools — reason only from the Backend Generation Result, Frontend Generation Result, and Final Build Result provided below.

Produce a concise markdown report:

# Migration Report: JSP → React + Spring Boot 4 BFF

## Summary
One paragraph: the scope of the transformation (how many pages/servlets became how many React pages and BFF endpoints), the packaging change (WAR/external-container → standalone JAR), and the final outcome (both trees building or not).

## Build Status
- Final result: PASSED or FAILED, from the Final Build Result JSON's `passed` field
- If FAILED: list the remaining errors verbatim, grouped by `[backend]`/`[frontend]`, and note they need manual follow-up

## Architectural Changes Applied
- **Backend (BFF)**: endpoints generated, from the Backend Generation Result
- **Frontend (React)**: pages/routes generated, from the Frontend Generation Result
- **Packaging**: confirm the backend is now a standalone JAR (Spring Boot 4, embedded server), not a WAR

## Follow-up Recommendations
- Manual end-to-end smoke test of each migrated user flow against the new React + BFF stack
- Side-by-side behavioural comparison against the original JSP app for any flow with complex session/state handling
- The automated build_loop only compiles/bundles both trees — it does not run either a Java test suite or any frontend test framework; recommend adding both if none exist yet (flag this explicitly if the Existing Test Inventory from the analysis phase showed low or no coverage)
- Session/auth mechanism (from the plan's Session & Auth Strategy) should be verified under real browser conditions (cookies, CORS if frontend and backend are served from different origins in production)

Keep it factual and grounded strictly in the three inputs — do not claim a build passed if the Final Build Result says otherwise.
