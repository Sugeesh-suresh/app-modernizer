# Oracle 19c → 23ai PL/SQL Patterns

## LONG RAW → BLOB
```sql
-- Before
ALTER TABLE documents ADD (content LONG RAW);

-- After
ALTER TABLE documents ADD (content BLOB);
```

## Removing a stale optimizer pin
```sql
-- Before
ALTER SESSION SET OPTIMIZER_FEATURES_ENABLE = '11.2.0.4';

-- After
-- (removed — re-validated on 23ai; if a specific plan regression is found,
--  pin only the minimal feature needed via a hint, not a blanket version pin)
```

## Optional: native BOOLEAN column (only if the plan calls for it)
```sql
-- Before
is_active NUMBER(1) DEFAULT 1 CHECK (is_active IN (0, 1))

-- After (Oracle 23ai)
is_active BOOLEAN DEFAULT TRUE
```

## Optional: JSON-relational duality view (only if the plan calls for it)
```sql
-- After (Oracle 23ai) — exposes a JSON document view over relational tables
CREATE JSON RELATIONAL DUALITY VIEW customer_dv AS
SELECT JSON {
  '_id'   : c.customer_id,
  'name'  : c.customer_name,
  'orders': [ SELECT JSON { 'orderId': o.order_id, 'total': o.total_amount }
              FROM orders o WHERE o.customer_id = c.customer_id ]
}
FROM customers c WITH INSERT UPDATE DELETE;
```
