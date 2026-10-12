package com.acme.orders.domain;

import java.math.BigDecimal;
import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.Id;
import javax.persistence.Table;
import org.hibernate.annotations.Type;

/** CUSTOMERS, mapped with Hibernate (the orders themselves stay on JdbcTemplate + ORDER_PKG). */
@Entity
@Table(name = "CUSTOMERS")
public class Customer {
    @Id
    @Column(name = "CUSTOMER_ID")
    private Long id;

    @Column(name = "NAME", nullable = false, length = 200)
    private String name;

    @Column(name = "EMAIL", length = 320)
    private String email;

    @Column(name = "SEGMENT", length = 30)
    private String segment;

    @Column(name = "CREDIT_LIMIT", precision = 12, scale = 2)
    private BigDecimal creditLimit;

    /** NUMBER(1) 0/1 in Oracle. */
    @Type(type = "org.hibernate.type.NumericBooleanType")
    @Column(name = "IS_ACTIVE", nullable = false)
    private boolean active = true;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }
    public String getSegment() { return segment == null ? "RETAIL" : segment; }
    public void setSegment(String segment) { this.segment = segment; }
    public BigDecimal getCreditLimit() { return creditLimit; }
    public void setCreditLimit(BigDecimal creditLimit) { this.creditLimit = creditLimit; }
    public boolean isActive() { return active; }
    public void setActive(boolean active) { this.active = active; }
}
