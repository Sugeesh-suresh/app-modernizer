package com.acme.orders.model;

import java.io.Serializable;
import java.math.BigDecimal;

import javax.validation.constraints.DecimalMin;
import javax.validation.constraints.Min;
import javax.validation.constraints.NotNull;

import javax.validation.constraints.Pattern;

public class OrderLine implements Serializable {
    private static final long serialVersionUID = 1L;

    @NotNull
    @Pattern(regexp = ".*\\S.*")
    private String sku;

    /** Filled in by the LineEnricher bean in the intake route. */
    private String description;

    @Min(1)
    private int quantity;

    @NotNull
    @DecimalMin("0.00")
    private BigDecimal unitPrice;

    public OrderLine() {
    }

    public OrderLine(String sku, int quantity, BigDecimal unitPrice) {
        this.sku = sku;
        this.quantity = quantity;
        this.unitPrice = unitPrice;
    }

    public String getSku() { return sku; }
    public void setSku(String sku) { this.sku = sku; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public int getQuantity() { return quantity; }
    public void setQuantity(int quantity) { this.quantity = quantity; }
    public BigDecimal getUnitPrice() { return unitPrice; }
    public void setUnitPrice(BigDecimal unitPrice) { this.unitPrice = unitPrice; }
}
