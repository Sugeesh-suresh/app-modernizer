---
name: business-rules-extract
description: >
  Classifies each code candidate it is given (a method, validation annotations,
  an enumeration, constants, a stored procedure, a CHECK constraint, view logic
  or a rules-engine rule) and extracts every business rule it implements, one
  record per rule, cited to its lines. Answers in one JSON block covering every
  candidate. Describes the code as it is; never suggests changes.
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
       "lines": "9-11", "basis": "explicit", "confidence": "high"}
    ]},
    {"candidate": "C00013", "rules": [], "technical": "null guard before saving; no business decision"}
  ]
}
```
