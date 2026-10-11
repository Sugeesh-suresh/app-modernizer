CREATE OR REPLACE PACKAGE pkg_transfer AS
  PROCEDURE transfer_funds(p_from IN VARCHAR2, p_to IN VARCHAR2, p_amount IN NUMBER, p_txn_id OUT NUMBER);
END pkg_transfer;
/
CREATE OR REPLACE PACKAGE BODY pkg_transfer AS
  PROCEDURE transfer_funds(p_from IN VARCHAR2, p_to IN VARCHAR2, p_amount IN NUMBER, p_txn_id OUT NUMBER) IS
    v_balance NUMBER;
  BEGIN
    SELECT balance INTO v_balance FROM accounts WHERE account_number = p_from FOR UPDATE;
    IF v_balance < p_amount THEN
      RAISE_APPLICATION_ERROR(-20001, 'Insufficient funds');
    END IF;
    UPDATE accounts SET balance = balance - p_amount WHERE account_number = p_from;
    UPDATE accounts SET balance = balance + p_amount WHERE account_number = p_to;
    p_txn_id := txn_seq.NEXTVAL;
    INSERT INTO transactions (id, from_account, to_account, amount) VALUES (p_txn_id, p_from, p_to, p_amount);
  END transfer_funds;
END pkg_transfer;
/
CREATE OR REPLACE TRIGGER trg_accounts_audit
AFTER UPDATE OF status ON accounts FOR EACH ROW
BEGIN
  INSERT INTO audit_log (action, detail) VALUES ('ACCOUNT_STATUS', :OLD.account_number || ' ' || :OLD.status || '->' || :NEW.status);
END;
/
