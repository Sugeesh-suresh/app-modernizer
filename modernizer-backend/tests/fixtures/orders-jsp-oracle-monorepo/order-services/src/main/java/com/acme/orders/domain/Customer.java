package com.acme.orders.domain;

public class Customer {
    private Long id;
    private String name;
    private String email;
    private String segment;
    private java.math.BigDecimal creditLimit;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }
    public String getSegment() { return segment; }
    public void setSegment(String segment) { this.segment = segment; }
    public java.math.BigDecimal getCreditLimit() { return creditLimit; }
    public void setCreditLimit(java.math.BigDecimal creditLimit) { this.creditLimit = creditLimit; }
}
