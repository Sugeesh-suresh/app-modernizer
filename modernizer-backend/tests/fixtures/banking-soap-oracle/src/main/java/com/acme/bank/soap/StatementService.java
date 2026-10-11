package com.acme.bank.soap;

import java.time.LocalDate;
import java.util.List;
import javax.jws.WebMethod;
import javax.jws.WebParam;
import javax.jws.WebService;
import org.springframework.jdbc.core.JdbcTemplate;

@WebService(serviceName = "StatementService", targetNamespace = "http://acme.com/bank/statements")
public class StatementService {
    private final JdbcTemplate jdbc;

    public StatementService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @WebMethod(operationName = "getStatement")
    public List<String> getStatement(@WebParam(name = "accountNumber") String accountNumber,
                                     @WebParam(name = "fromDate") LocalDate from,
                                     @WebParam(name = "toDate") LocalDate to) {
        // TODO enforce bank.statement.max-days
        String sql = "SELECT to_char(booked_at,'YYYY-MM-DD') || ' ' || amount FROM transactions WHERE from_account = '"
                + accountNumber + "' AND booked_at BETWEEN ? AND ?";
        return jdbc.queryForList(sql, String.class, from, to);
    }
}
