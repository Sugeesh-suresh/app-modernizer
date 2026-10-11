package com.acme.claims.repo;

public interface ClaimRepository extends JpaRepository<Claim, Long> {
    @Query("select c from Claim c where c.policyNo = ?1")
    java.util.List<Claim> byPolicy(String policyNo);
}
