CREATE TABLE policies (
  id            NUMBER(19) PRIMARY KEY,
  policy_number VARCHAR2(20) NOT NULL UNIQUE,
  holder_name   VARCHAR2(200) NOT NULL,
  premium       NUMBER(12,2),
  status        VARCHAR2(12) DEFAULT 'ACTIVE',
  terms         LONG
);
CREATE SEQUENCE policy_seq START WITH 1;

CREATE OR REPLACE PROCEDURE lapse_overdue_policies AS
BEGIN
  UPDATE policies SET status = 'LAPSED'
   WHERE status = 'ACTIVE' AND id IN (SELECT policy_id FROM premium_due WHERE due_date < SYSDATE - 30);
  COMMIT;
END;
/
