package com.acme.claims.repo;

import com.acme.claims.domain.ClaimNote;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ClaimNoteRepository extends JpaRepository<ClaimNote, Long> {
}
