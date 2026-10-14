package com.acme.orders.model;

/** Lifecycle of an order as it moves through the Camel routes. */
public enum OrderStatus {
    RECEIVED,
    ACCEPTED,
    REJECTED,
    SHIPPED,
    CANCELLED
}
