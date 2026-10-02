# Database / data store / search engine — what to document

Where to look:
- Connection configuration: data sources, connection URLs, driver/client coordinates, pool settings, ORM configuration
- Schema artifacts: DDL scripts, schema-change tool directories (Flyway, Liquibase, Alembic, Rails/Django migrations — these are repository artifacts; describe what they create), index/mapping definitions, seed data
- Data access code: repositories, DAOs, ORM entities and mappings, query builders, raw queries, stored procedure calls

What to record:
- Which product and how the application connects (client library, URL with credentials redacted, pooling, how the connection is obtained)
- Every schema object or collection/index defined in the repository: fields, types, keys, constraints, indexes
- Every query or data operation the application issues: location, objects touched, read or write, transactions
- Stored procedures, functions, triggers, views
- Which application capabilities depend on which objects
- Caching, batching, pagination and consistency settings
- Tests that touch the store and what they need to run
