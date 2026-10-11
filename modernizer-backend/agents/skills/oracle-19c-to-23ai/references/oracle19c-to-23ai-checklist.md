# Oracle 19c → 23ai Migration Checklist

## Compatibility & Deprecated Constructs (required)

| Item | Action |
|---|---|
| `LONG`/`LONG RAW` columns touched by in-scope objects | Migrate to `CLOB`/`BLOB` |
| Hard-coded 32767-byte `VARCHAR2`/`DBMS_LOB.SUBSTR` boundaries | Review against 23ai's extended limits; only change if it constrains a requirement |
| Pinned old `OPTIMIZER_FEATURES_ENABLE` session/system settings | Re-validate query plans on 23ai; remove the pin if no longer needed |
| `compatible` init parameter / AQ queue table compatibility level | Bump to a 23ai-compatible level (infrastructure change — document, do not script a live `ALTER SYSTEM`) |
| `DBMS_JAVA` usage | Review against 23ai's JVM-in-database changes; update calls if signatures changed |

## Optional 23ai Feature Adoption (only if the BRD calls for it — do not force these)

| Feature | When to propose it |
|---|---|
| JSON-relational duality views | Tables with a corresponding hand-written JSON serialization layer in application code |
| Native `VECTOR` type + `VECTOR_DISTANCE` | Application does embeddings/similarity search via an external vector store that could be consolidated |
| Native `BOOLEAN` column type | `NUMBER(1)`/`CHAR(1)` check-constrained boolean columns found |
| `SELECT ... GROUP BY` enhancements / new analytic SQL | Only if the technical spec identifies a specific query that would clearly benefit |

## Application/Driver Changes

| Item | Action |
|---|---|
| Old Oracle JDBC driver version (`ojdbc7`/old `ojdbc8`) | Bump to a 23ai-certified driver version (e.g., `ojdbc11:23.3.0.0`) in `pom.xml`/`build.gradle` |
| Application Java version | Align application's `maven.compiler.source`/`target` with the target runtime and chosen JDBC driver, if not already compatible. This may require a separate, broader Java upgrade effort. |
| Outdated connection pool (e.g., `commons-dbcp` 1.4) | Replace with a modern connection pool (e.g., HikariCP 5.x.x or Oracle UCP) and map properties accordingly (e.g., `commons-dbcp` `initialSize` to `HikariCP` `minimumIdle`, `maxActive` to `maximumPoolSize`). |
| Outdated JUnit version (e.g., JUnit 3.x) | Upgrade to JUnit 5 (e.g., `junit-jupiter-api` and `junit-jupiter-engine` `5.10.0`) and update test cases as needed. |

## Explicitly Out of Scope (document, do not attempt)
- The database engine upgrade/patch itself (19c binaries → 23ai binaries) — infrastructure/DBA operation
- Live data migration, `impdp`/`expdp`, or Data Pump scripting
- Any `ALTER SYSTEM`/`ALTER DATABASE` statement — these require a live instance and DBA sign-off, not an automated code-migration agent

## Validation
Static syntax/heuristic checks only (balanced PL/SQL blocks, statement terminators, deprecated-construct scan) — there is no live Oracle instance in this pipeline. A real syntax check (`SQL*Plus`/`sqlcl` compile, or a DBA review) is a required manual follow-up before this is considered production-ready.
