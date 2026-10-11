package com.acme.bank.domain;

import java.math.BigDecimal;
import javax.persistence.*;

@Entity
@Table(name = "ACCOUNTS")
public class Account {
    @Id
    @Column(name = "ACCOUNT_NUMBER")
    private String accountNumber;

    @ManyToOne
    @JoinColumn(name = "CUSTOMER_ID")
    private Customer customer;

    private BigDecimal balance;
    private String status;

    public String getAccountNumber() { return accountNumber; }
    public Customer getCustomer() { return customer; }
    public BigDecimal getBalance() { return balance; }
    public String getStatus() { return status; }
}
