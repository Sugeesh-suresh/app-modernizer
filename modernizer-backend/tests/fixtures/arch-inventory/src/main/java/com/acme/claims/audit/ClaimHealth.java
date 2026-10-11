package com.acme.claims.audit;

public class ClaimHealth implements HealthIndicator {
    public Health health() { return Health.up().build(); }
}
