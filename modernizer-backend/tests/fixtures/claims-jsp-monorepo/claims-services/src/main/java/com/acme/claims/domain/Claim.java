package com.acme.claims.domain;

import java.math.BigDecimal;
import javax.persistence.*;

@Entity
@Table(name = "CLAIMS")
public class Claim {
    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "claim_seq")
    @SequenceGenerator(name = "claim_seq", sequenceName = "CLAIM_SEQ", allocationSize = 1)
    private Long id;
    @Column(name = "POLICY_NUMBER")
    private String policyNumber;
    private String description;
    private BigDecimal amount;
    private String status;

    public Long getId() { return id; }
    public String getPolicyNumber() { return policyNumber; }
    public BigDecimal getAmount() { return amount; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
}
