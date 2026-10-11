package com.acme.bank.service;

import com.acme.bank.domain.Account;
import com.acme.bank.domain.BalanceView;
import com.acme.bank.repo.AccountRepository;
import java.math.BigDecimal;
import java.util.Map;
import javax.sql.DataSource;
import org.springframework.jdbc.core.simple.SimpleJdbcCall;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AccountService {
    private final AccountRepository accounts;
    private final SimpleJdbcCall transferCall;

    public AccountService(AccountRepository accounts, DataSource dataSource) {
        this.accounts = accounts;
        this.transferCall = new SimpleJdbcCall(dataSource).withCatalogName("PKG_TRANSFER").withProcedureName("TRANSFER_FUNDS");
    }

    public BalanceView balance(String accountNumber) {
        Account a = accounts.findOpen(accountNumber).orElseThrow(() -> new IllegalArgumentException("Unknown account"));
        BalanceView v = new BalanceView();
        v.accountNumber = a.getAccountNumber();
        v.balance = a.getBalance();
        v.status = a.getStatus();
        return v;
    }

    @Transactional
    public long transfer(String from, String to, BigDecimal amount) {
        if (amount.signum() <= 0) {
            throw new IllegalArgumentException("Amount must be positive");
        }
        Map<String, Object> out = transferCall.execute(Map.of("P_FROM", from, "P_TO", to, "P_AMOUNT", amount));
        return ((Number) out.get("P_TXN_ID")).longValue();
    }
}
