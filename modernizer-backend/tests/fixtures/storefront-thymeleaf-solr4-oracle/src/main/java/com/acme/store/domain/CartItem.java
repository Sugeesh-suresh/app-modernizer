package com.acme.store.domain;

import java.io.Serializable;
import java.math.BigDecimal;

/** A line in the session cart. */
public class CartItem implements Serializable {
    private static final long serialVersionUID = 1L;
    private final Long productId;
    private final String name;
    private final BigDecimal price;
    private int quantity;

    public CartItem(Long productId, String name, BigDecimal price, int quantity) {
        this.productId = productId;
        this.name = name;
        this.price = price;
        this.quantity = quantity;
    }

    public Long getProductId() { return productId; }
    public String getName() { return name; }
    public BigDecimal getPrice() { return price; }
    public int getQuantity() { return quantity; }
    public void setQuantity(int quantity) { this.quantity = quantity; }
    public BigDecimal getLineTotal() { return price.multiply(new BigDecimal(quantity)); }
}
