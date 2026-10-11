package com.acme.claims.repo;

import com.acme.claims.domain.Claim;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ClaimRepository extends JpaRepository<Claim, Long> {
    List<Claim> findByStatus(String status);
    List<Claim> findByPolicyNumberStartingWith(String prefix);
}
