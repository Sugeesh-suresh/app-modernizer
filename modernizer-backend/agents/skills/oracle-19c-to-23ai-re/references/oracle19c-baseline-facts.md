# Oracle 19c Baseline — Patterns to Look For

## Deprecated / legacy constructs
- `LONG` / `LONG RAW` columns — deprecated for a very long time; migrate to `CLOB`/`BLOB` if touched during this migration
- `DBMS_LOB.SUBSTR(..., 32767)` or other hard-coded 32767-byte boundaries — a legacy `VARCHAR2` ceiling; 23ai's extended data handling may make some of these artificial
- `CONNECT BY` hierarchical queries without `NOCYCLE` where cycles are possible
- `RAW(16) DEFAULT SYS_GUID()` as a manual UUID/primary-key pattern — 23ai's native support may simplify this, but it is not broken, just worth flagging as an optional modernisation
- `ALTER SESSION SET OPTIMIZER_FEATURES_ENABLE = '11.x...'` or similar old pinned optimizer versions — review whether still required
- `DBMS_JAVA` usage — review against 23ai's JVM-in-database changes
- Old AQ (Advanced Queuing) setup with an old `compatible` parameter passed to `DBMS_AQADM.CREATE_QUEUE_TABLE`

## Schema/version tells
- `init.ora`/`spfile` snippets or comments referencing `compatible = 19.0.0` or similar
- `USER_OBJECTS`/`ALL_OBJECTS` queries filtering by `EDITIONABLE` in ways that assume pre-23ai edition-based redefinition limits
- No use of JSON-relational duality views (`CREATE JSON DUALITY VIEW`) — new in 23ai; not a required migration, but worth flagging in the BRD as an optional adoption
- No use of native `VECTOR` data type or `VECTOR_DISTANCE` functions — new in 23ai for AI Vector Search; flag as an optional forward-looking adoption if the application does embeddings/similarity search elsewhere (e.g. in application code, calling out to an external vector DB) that could be consolidated
- Boolean columns implemented as `NUMBER(1)`/`CHAR(1)` check-constrained columns — 23ai adds a native `BOOLEAN` column type; optional modernisation, not required

## Application/JDBC tells
- Old Oracle JDBC driver version pinned in `pom.xml`/`build.gradle` (`ojdbc8`/`ojdbc7` at very old point releases)
- Manual connection pooling instead of UCP (Universal Connection Pool) — not required to change, but worth noting

## What is explicitly OUT of scope for the automated code migration
- The actual database engine upgrade/patching (19c → 23ai binaries) is a DBA/infrastructure operation, not a source-code change — call this out clearly in the BRD's Scope section
- Live data migration/validation against a running instance — this pipeline's build_loop only statically checks SQL/PLSQL syntax
