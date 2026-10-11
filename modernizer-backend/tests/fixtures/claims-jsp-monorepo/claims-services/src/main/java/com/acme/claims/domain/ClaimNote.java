package com.acme.claims.domain;

import javax.persistence.*;

@Entity
@Table(name = "CLAIM_NOTES")
public class ClaimNote {
    @Id
    @GeneratedValue
    private Long id;
    @Column(name = "CLAIM_ID")
    private Long claimId;
    @Column(name = "NOTE_TEXT")
    private String text;

    public ClaimNote() {}
    public ClaimNote(Long claimId, String text) { this.claimId = claimId; this.text = text; }
}
