package com.acme.shop.service;

public class ProductNotFoundException extends RuntimeException {
    public ProductNotFoundException(long id) {
        super("Product not found: " + id);
    }
}
