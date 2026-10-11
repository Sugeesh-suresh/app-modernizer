CREATE TABLE claim (
  id NUMBER(19) PRIMARY KEY,
  policy_no VARCHAR2(20) NOT NULL,
  amount NUMBER(12,2),
  created_by VARCHAR2(50),
  CONSTRAINT fk_policy FOREIGN KEY (policy_no) REFERENCES policy(policy_no)
);
CREATE INDEX ix_claim_policy ON claim (policy_no);
CREATE TABLE claim_audit (id NUMBER(19), claim_id NUMBER(19), action VARCHAR2(10), at TIMESTAMP);
CREATE OR REPLACE TRIGGER trg_claim_audit AFTER INSERT OR UPDATE ON claim FOR EACH ROW
BEGIN INSERT INTO claim_audit VALUES (1, :new.id, 'U', SYSTIMESTAMP); END;
/
