package com.acme.inventory.model;

public enum OrderStatus {
    NEW("New"), RESERVED("Reserved"), SHIPPED("Shipped"), CANCELLED("Cancelled");

    private final String label;

    OrderStatus(String label) {
        this.label = label;
    }

    public String getLabel() {
        return label;
    }

    public boolean isFinal() {
        return this == SHIPPED || this == CANCELLED;
    }

    public static OrderStatus fromString(String s) {
        if (s == null) {
            return NEW;
        }
        for (OrderStatus st : values()) {
            if (st.name().equalsIgnoreCase(s.trim())) {
                return st;
            }
        }
        throw new IllegalArgumentException("Unknown status: " + s);
    }
}
