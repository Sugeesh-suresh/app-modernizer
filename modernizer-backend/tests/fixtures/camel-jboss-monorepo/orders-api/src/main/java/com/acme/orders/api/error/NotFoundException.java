package com.acme.orders.api.error;

public class NotFoundException extends RuntimeException {
    private static final long serialVersionUID = 1L;

    public NotFoundException(String what, String id) {
        super(what + " " + id + " not found");
    }
}
