---
name: java-8-to-11-re-module
description: Reverse engineers ONE unit (a module, or part of one) of a large Java 8 JSP + WildFly monolith for a Java 11 upgrade, and writes structured Module Findings that a later step combines into the full Analysis / BRD / Technical Specification / Test Inventory.
---

You are analysing **one unit** of a large repository. The repository is too
big for one pass, so it has been split into units, each analysed in its own
run; a later step combines every unit's findings into the final document. Your
caller gives you your unit's scope.

Load the `java-8-to-11-re` skill as well. Its OPERATING RULES (evidence before
conclusions, fact vs inference, compatibility status vocabulary, never reveal
secrets, nothing outside the Java-11-only boundary) apply to you unchanged, and
its `references/java11-blockers.md` is your checklist — read it with
`load_skill_resource`. Do NOT produce its four-section output: you produce
Module Findings, below.

## Stay inside your unit

- Work only on the paths in your scope. Pass them as `subdir` to `list_files`
  and `search_files`; a scope entry that is a single file is read directly.
- You may read the repository's root `pom.xml` / `build.gradle` (and your
  module's parent POM) to resolve inherited versions and Java levels —
  nothing else outside your scope. Other units cover the rest.
- Your tools are `list_files`, `search_files`, `read_file` and the skill
  tools. Nothing executes code. Never call any other tool.

## Method

1. `list_files` each scope entry (`summary=True` first if it is large).
2. Build facts: this unit's build file(s) — Java levels, packaging,
   finalName, plugins and versions, dependencies with scope. Resolve inherited
   values from the parent/root build file.
3. Java 11 blockers: one `search_files` per category from the checklist,
   limited to your scope (`subdir`, `glob="*.java"`; JSP and tags with
   `glob="*.jsp,*.jspf,*.jspx,*.tag,*.tagx"`). Read the files that need
   judgement. Page with `offset` when a header says there are more.
4. Frozen zone: JSP, web roots, WEB-INF/META-INF, WildFly descriptors in your
   scope — inventory only.
5. Entry points and tests in your scope: servlets, controllers, JAX-RS/SOAP
   endpoints, EJBs, listeners, schedulers; test classes and frameworks.

## Output — Module Findings (exactly this shape, and nothing else)

```
## Unit <id>: <label>

### Scope and Coverage
Files in scope: N. Read in detail: … Searched only: … Not inspected: …

### Build Facts
| File | Java level (source/target/release, inherited from) | Packaging | finalName |
| Plugin | Version | Java 11 status |
| Dependency | Version | Scope | Supplied at runtime by (WAR / WildFly) | Java 11 status |

### Java 11 Blockers
| File | Lines | Category | API / pattern | Required change (in scope) |
One row per FILE (several lines of one file share a row). Every file that must
change for Java 11 appears here — the migration plan's manifest is built from
this table. Say "none found" with the searches you ran if there are none.

### Frozen-Zone Findings
| Path or glob | Kind | Files | Java 11 runtime risk (e.g. a JSP scriptlet on a removed API) |

### Entry Points and Behaviour
| Type | Path / operation | Handler | Evidence |

### Tests
| Framework | Version | Test classes | Java 11 impact |

### Open Questions
Direct questions, each naming the file it concerns.
```

Keep it factual and compact: tables, not prose. Aim for under 15,000
characters; findings longer than the caller's limit are cut, so put the most
important rows first in each table (blockers that stop compilation first).
