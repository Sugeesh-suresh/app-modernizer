package com.acme.claims.web;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;

@RestController
public class ClaimController {
    private static final Logger log = LoggerFactory.getLogger(ClaimController.class);

    @PreAuthorize("hasRole('ADJUSTER')")
    @Transactional(readOnly = true)
    public Claim get(Long id) {
        MDC.put("correlationId", "x");
        log.info("get claim {}", id);
        return null;
    }
}
