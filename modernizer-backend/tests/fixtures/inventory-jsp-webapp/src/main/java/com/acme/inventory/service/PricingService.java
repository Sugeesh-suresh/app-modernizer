package com.acme.inventory.service;

import java.math.BigDecimal;
import java.math.RoundingMode;

public class PricingService {

    public BigDecimal discountRate(BigDecimal subtotal) {
        if (subtotal == null || subtotal.signum() < 0) {
            throw new IllegalArgumentException("subtotal must be non-negative");
        }
        if (subtotal.compareTo(new BigDecimal("1000")) >= 0) {
            return new BigDecimal("0.10");
        }
        if (subtotal.compareTo(new BigDecimal("500")) >= 0) {
            return new BigDecimal("0.05");
        }
        if (subtotal.compareTo(new BigDecimal("100")) >= 0) {
            return new BigDecimal("0.02");
        }
        return BigDecimal.ZERO;
    }

    public BigDecimal taxRate(String region) {
        if (region == null || region.trim().isEmpty()) {
            throw new IllegalArgumentException("region is required");
        }
        switch (region.trim().toUpperCase()) {
            case "US":
                return new BigDecimal("0.07");
            case "EU":
                return new BigDecimal("0.20");
            case "UK":
                return new BigDecimal("0.20");
            case "JP":
                return new BigDecimal("0.10");
            default:
                return BigDecimal.ZERO;
        }
    }

    public BigDecimal total(BigDecimal subtotal, String region) {
        BigDecimal discounted = subtotal.subtract(subtotal.multiply(discountRate(subtotal)));
        BigDecimal withTax = discounted.add(discounted.multiply(taxRate(region)));
        return withTax.setScale(2, RoundingMode.HALF_UP);
    }
}
