package com.acme.shop.service;

public class DuplicateSkuException extends RuntimeException {
    public DuplicateSkuException(String sku) {
        super("Duplicate SKU: " + sku);
    }
}
