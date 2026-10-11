package com.acme.claims.domain;

import javax.persistence.*;

@Entity
@Table(name = "claim")
@EntityListeners(AuditingEntityListener.class)
public class Claim {
    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE)
    private Long id;

    @Column(name = "policy_no", nullable = false, length = 20)
    private String policyNo;

    private java.math.BigDecimal amount;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "adjuster_id")
    private Adjuster adjuster;

    @CreatedBy
    private String createdBy;

    @Transient
    private String scratch;
}
