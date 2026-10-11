CREATE SEQUENCE customer_seq START WITH 1000 INCREMENT BY 1;
CREATE SEQUENCE txn_seq START WITH 1 INCREMENT BY 1;

CREATE TABLE customers (
  id          NUMBER(19)    PRIMARY KEY,
  full_name   VARCHAR2(120) NOT NULL,
  email       VARCHAR2(200) NOT NULL UNIQUE,
  segment     VARCHAR2(20)  DEFAULT 'RETAIL' NOT NULL,
  created_at  TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE TABLE accounts (
  account_number VARCHAR2(20) PRIMARY KEY,
  customer_id    NUMBER(19)   NOT NULL REFERENCES customers(id),
  balance        NUMBER(15,2) DEFAULT 0 NOT NULL,
  status         VARCHAR2(10) DEFAULT 'OPEN' NOT NULL,
  CONSTRAINT chk_balance CHECK (balance >= 0)
);

CREATE TABLE transactions (
  id            NUMBER(19)   PRIMARY KEY,
  from_account  VARCHAR2(20) REFERENCES accounts(account_number),
  to_account    VARCHAR2(20) REFERENCES accounts(account_number),
  amount        NUMBER(15,2) NOT NULL,
  booked_at     TIMESTAMP    DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE INDEX ix_txn_from ON transactions(from_account, booked_at);

CREATE TABLE audit_log (
  id         NUMBER(19) GENERATED ALWAYS AS IDENTITY,
  action     VARCHAR2(40),
  detail     VARCHAR2(400),
  logged_at  TIMESTAMP DEFAULT SYSTIMESTAMP
);
