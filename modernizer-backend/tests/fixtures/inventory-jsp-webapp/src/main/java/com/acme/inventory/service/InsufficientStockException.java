package com.acme.inventory.service;

public class InsufficientStockException extends Exception {
    private static final long serialVersionUID = 1L;
    private final long productId;
    private final int available;

    public InsufficientStockException(long productId, int available, int requested) {
        super("Product " + productId + " has " + available + " in stock, requested " + requested);
        this.productId = productId;
        this.available = available;
    }

    public long getProductId() { return productId; }
    public int getAvailable() { return available; }
}
