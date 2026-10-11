package com.acme.claims.service;

import com.acme.claims.domain.Claim;
import com.acme.claims.domain.ClaimNote;
import com.acme.claims.repo.ClaimNoteRepository;
import com.acme.claims.repo.ClaimRepository;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ClaimService {
    private final ClaimRepository claims;
    private final ClaimNoteRepository notes;

    public ClaimService(ClaimRepository claims, ClaimNoteRepository notes) {
        this.claims = claims;
        this.notes = notes;
    }

    public List<Claim> list(String status) {
        return status == null || status.isEmpty() ? claims.findAll() : claims.findByStatus(status);
    }

    public List<Claim> search(String policy) {
        return claims.findByPolicyNumberStartingWith(policy);
    }

    public Claim get(Long id) {
        return claims.findById(id).orElseThrow();
    }

    @Transactional
    public Claim decide(Long id, String decision) {
        Claim c = get(id);
        if (!"OPEN".equals(c.getStatus())) {
            throw new ClaimDecisionException("Claim " + id + " is already " + c.getStatus());
        }
        c.setStatus(decision);
        return claims.save(c);
    }

    @Transactional
    public void addNote(Long id, String text) {
        get(id);
        notes.save(new ClaimNote(id, text));
    }
}
