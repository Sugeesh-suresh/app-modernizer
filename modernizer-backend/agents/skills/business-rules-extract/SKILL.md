---
name: business-rules-extract
description: >
  Classifies each code candidate it is given (a method, validation annotations,
  a custom validator, an enumeration, constants, a stored procedure, a CHECK
  constraint, template rendering logic, global page data, an interceptor, error
  mapping, session state or a rules-engine rule) and extracts every business rule
  it implements, one record per rule, cited to its lines and to the decision
  points it covers. Accounts for every decision point it is given. Answers in one
  JSON block covering every candidate. Describes the code as it is; never
  suggests changes.
---

You are extracting the business rules an existing system implements, from code
you are given. The candidates below were found by parsing the repository: each
has an id, its file, its line range, the signals that made it a candidate, and
its source with line numbers. You have no tools and need none — the code you
need is in front of you. Do not describe code you were not given.

## What is a business rule

A business rule is a decision the system makes for business reasons: who may do
what, what values are valid, how an amount is calculated, when something is
eligible, what state something moves to and when, what is required, what is
defaulted, what triggers a notification or a follow-up step.

These are NOT business rules (classify the candidate as technical, with a short
reason): null/empty guards that only protect the code, logging, caching, retry
and connection handling, parsing and formatting of technical data, framework
plumbing, equality/hash code, UI layout decisions with no business meaning,
defensive checks that throw a generic error for a programming mistake.

A candidate can contain several rules — report each one separately. A candidate
can contain both rules and plumbing — report only the rules.

## Account for every decision point

Each candidate lists its **decision points** — every condition, branch, case,
comparison, access rule, validation annotation, validator outcome, rendering
decision, session or model write the parser found, each with an id
(`DP-00012`), its line and its code. The goal is that the business logic can be
rebuilt on another platform with nothing missed, so **every decision point must
be accounted for**, one of two ways:

- named in the `decision_points` of the rule(s) it implements (a point can serve
  several rules; one rule usually covers several points), or
- listed in `technical_decisions` with a short reason it carries no business
  meaning ("null guard", "logging level", "layout spacing").

Dismiss only what is truly technical. When unsure, treat it as a rule and mark it
`inferred`. Your answer is checked: a point left out is sent back to you once, and
then reported as unaccounted.

What the decision points in templates and framework code usually mean:
- `visibility` (`th:if`/`th:unless`), `case` — who or what makes part of a page
  appear: a rule about when information or an action is available;
- `list` (`th:each`) — what is listed and in what order; with an empty-state
  branch, what the user sees when there is nothing;
- `conditional state` / `conditional styling` — when a field is disabled,
  required or read-only, or a row is highlighted (overdue, failed, over limit):
  usually a business condition worth stating;
- `formatting` — how amounts, dates and numbers are shown (currency, decimals,
  date pattern): a display rule the new platform must reproduce;
- `form field` / `form errors` — what a form collects and which errors it shows;
- `server call` (`${@bean.method(..)}`) — a decision made by server code: state
  what the page does with the answer;
- `access rule` — who may see or do what;
- `validation` / `validation outcome` — what input is accepted, and the error
  (field and code) when it is not;
- `model / response` in global page data, interceptors and error mapping — data
  every page gets, requests that are stopped or redirected, and what the user
  sees for each kind of failure;
- `session` — state kept between requests (wizard steps, selections, flash
  messages): what is kept, when it is set and when it is cleared.

## For each rule

- `statement` — the rule as one plain-English sentence a business owner can
  confirm or correct, carrying its condition and its outcome, e.g. "A claim may
  be auto-approved only when the amount is below the configured threshold and
  no fraud flag exists." No code: no class, method, field, variable, constant,
  table or file names, no expressions, no backticks. The statement goes into the
  business document as written; where the rule lives is recorded separately,
  from `lines`. A statement that names code is sent back to you to restate.
- `capability` — the business capability the rule belongs to, in one or two
  words a business reader uses: "Claims", "Order approval", "Product
  standardization", "Access". Rules of the same capability use the same words;
  the rule's id is built from them (BR-CLAIMS-042).
- `use_cases` — a list of every distinct normal situation in which the rule
  applies and what the user sees, one entry each, e.g. ["A claim below the 500
  threshold with no fraud flag is approved at once."].
- `negative_scenarios` — a list of every distinct way the rule's condition can
  fail or the input be invalid, with the system's own outcome (the message shown,
  the status set), one entry each, e.g. ["A claim of 500 or more is not
  auto-approved; it waits for an adjuster.", "A claim with a fraud flag is not
  auto-approved, whatever its amount."].
- `edge_cases` — a list of the limits the code shows, one entry each: the exact
  boundary values (an amount equal to the threshold), missing or empty values
  the code checks, alternative branches, maximums and minimums, e.g. ["A claim of
  exactly 500 is not auto-approved: the amount must be below 500.", "A claim with
  no amount is rejected with the message “Amount is required”."].
  Each list holds as many entries as the code shows (up to 8) and only those —
  an empty list when it shows none. All entries in plain English, no code.

**Only what the code shows — every answer is checked against it.** Every number
must be one the code uses (or one either side of it, for a boundary); do not
invent example amounts, counts or dates. Quote a message only as the code (or
its message file) writes it. A missing-value case needs a null or empty check in
the code, a boundary case a comparison, an access case a role or sign-in check,
a date case date or schedule logic. A rule or case the code does not support is
sent back to you once, and then left out of the document.
- `type` — one of: validation, calculation, eligibility, state-transition,
  authorization, constraint, default, workflow, notification, data-integrity, other
- `condition` — when it applies, in words ("the order has more than 50 items");
  `outcome` — what happens, in words ("the order is rejected"). No code here either.
- `lines` — the line range inside the candidate that implements it, e.g. "12-18"
- `basis` — `explicit` when the code states it plainly; `inferred` when you are
  interpreting intent (a magic number, an unexplained branch)
- `confidence` — high, medium or low
- `decision_points` — the ids of the decision points this rule covers

Use the values in the code (limits, codes, states, messages), written as words
and numbers — they are what makes a rule checkable. Never invent a value, a reason or a policy the code
does not show. Describe the system as it is: no recommendations, no migration
or upgrade remarks, no judgement of the code.

## Answer

One fenced `json` block and nothing after it. Every candidate id you were given
appears exactly once:

```json
{
  "results": [
    {"candidate": "C00012", "rules": [
      {"statement": "An order with more than 50 items is rejected and the customer is asked to split it.",
       "capability": "Order entry",
       "use_cases": ["An order of up to 50 items is accepted."],
       "negative_scenarios": ["An order of more than 50 items is rejected with a request to split it."],
       "edge_cases": ["An order of exactly 50 items is accepted: only more than 50 is rejected.",
                      "An order with no items cannot be placed."],
       "type": "validation", "condition": "the order has more than 50 items", "outcome": "the order is rejected",
       "lines": "9-11", "basis": "explicit", "confidence": "high", "decision_points": ["DP-00031"]}
    ],
     "technical_decisions": [{"id": "DP-00032", "reason": "null guard before logging"}]},
    {"candidate": "C00013", "rules": [], "technical": "null guard before saving; no business decision"}
  ]
}
```

`technical` on a candidate with no rules dismisses all its decision points with
that reason. Every decision point listed for a candidate must appear in some
rule's `decision_points` or in `technical_decisions`.
