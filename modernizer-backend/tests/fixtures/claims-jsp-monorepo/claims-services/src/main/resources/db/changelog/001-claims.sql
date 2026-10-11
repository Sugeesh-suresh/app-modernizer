--liquibase formatted sql
--changeset claims:1
CREATE SEQUENCE claim_seq START WITH 1 INCREMENT BY 1;
CREATE TABLE claims (
  id             NUMBER(19)    PRIMARY KEY,
  policy_number  VARCHAR2(20)  NOT NULL,
  description    CLOB,
  amount         NUMBER(12,2)  NOT NULL,
  status         VARCHAR2(12)  DEFAULT 'OPEN' NOT NULL,
  decided_at     TIMESTAMP
);
CREATE TABLE claim_notes (
  id        NUMBER(19) PRIMARY KEY,
  claim_id  NUMBER(19) NOT NULL REFERENCES claims(id),
  note_text VARCHAR2(500) NOT NULL,
  added_at  TIMESTAMP DEFAULT SYSTIMESTAMP
);
CREATE INDEX ix_claims_policy ON claims(policy_number);
CREATE OR REPLACE VIEW v_open_claims AS SELECT id, policy_number, amount FROM claims WHERE status = 'OPEN';
