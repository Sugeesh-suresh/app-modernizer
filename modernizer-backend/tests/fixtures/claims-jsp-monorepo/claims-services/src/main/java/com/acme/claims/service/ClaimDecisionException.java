package com.acme.claims.service;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ResponseStatus;

@ResponseStatus(HttpStatus.CONFLICT)
public class ClaimDecisionException extends RuntimeException {
    public ClaimDecisionException(String message) { super(message); }
}
