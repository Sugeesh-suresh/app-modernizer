package com.acme.orders.domain;

import java.math.BigDecimal;

public class OrderLine {
    private Long id;
    private String sku;
    private int quantity;
    private BigDecimal unitPrice;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getSku() { return sku; }
    public void setSku(String sku) { this.sku = sku; }
    public int getQuantity() { return quantity; }
    public void setQuantity(int quantity) { this.quantity = quantity; }
    public BigDecimal getUnitPrice() { return unitPrice; }
    public void setUnitPrice(BigDecimal unitPrice) { this.unitPrice = unitPrice; }

    public BigDecimal lineTotal() {
        return unitPrice == null ? BigDecimal.ZERO : unitPrice.multiply(new BigDecimal(quantity));
    }
}
