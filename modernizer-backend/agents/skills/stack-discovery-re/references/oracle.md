# Oracle Database — what to document

Where to look:
- DDL/DML scripts (`*.sql`, `*.pls`, `*.pks`, `*.pkb`, `*.trg`, `*.vw`), schema-change tool directories (Flyway `db/migration`, Liquibase changelogs) — these are repository artifacts; describe what they create
- JDBC configuration: data-source definitions, `jdbc:oracle:` URLs, driver coordinates, connection-pool settings
- Application data access: DAOs, repositories, JPA entities and named queries, MyBatis mappers, `CallableStatement` calls
- Oracle-specific client usage: `oracle.jdbc.*`, `oracle.sql.*`, AQ, UCP, wallet configuration, `tnsnames.ora`

What to record:
- Schemas, tables (columns, types, keys, constraints, indexes), views, sequences, synonyms
- PL/SQL packages, procedures, functions and triggers: purpose, parameters, the tables they touch
- Every SQL statement issued by the application: where it is, the tables it uses, and whether it reads or writes
- Data-access patterns: transactions, batching, fetch sizes, LOB handling, pagination, hints
- Connection configuration with credentials redacted, pool sizing, and how the connection is obtained (JNDI, direct, Spring)
- Which application capabilities depend on which tables and procedures
- Tests that touch the database and what they need (embedded DB, real instance, mocks)
- Security in the database: schema owners and application users, roles and `GRANT`s, synonyms that expose objects, Virtual Private Database / row-level policies, encrypted columns or tablespaces (TDE), wallet use, password handling in scripts (redacted)
- Auditing in the database: `AUDIT` statements and unified audit policies, history/journal tables and the triggers or procedures that fill them, `created_by`/`updated_at`-style columns and what sets them
- Logging and monitoring from PL/SQL: `DBMS_OUTPUT`, logging tables and packages, `DBMS_APPLICATION_INFO`, error-logging tables (`LOG ERRORS`), scheduler jobs (`DBMS_SCHEDULER`/`DBMS_JOB`) and their logs
- Links to other systems: database links, external tables, `UTL_HTTP`/`UTL_FILE`/`UTL_SMTP`, Advanced Queuing — each is an integration
