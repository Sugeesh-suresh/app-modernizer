package com.acme.orders.camel.exception;

import java.util.List;

public class OrderValidationException extends Exception {
    private static final long serialVersionUID = 1L;

    private final List<String> violations;

    public OrderValidationException(String message, List<String> violations) {
        super(message);
        this.violations = violations;
    }

    public List<String> getViolations() {
        return violations;
    }
}
