package com.acme.catalog.domain;

import java.math.BigDecimal;
import javax.persistence.*;

@Entity
@Table(name = "PRODUCTS")
public class Product {
    @Id
    private String sku;
    private String name;
    private String description;
    private String category;
    private BigDecimal price;
    @Column(name = "IN_STOCK")
    private boolean inStock;

    public String getSku() { return sku; }
    public String getName() { return name; }
    public String getDescription() { return description; }
    public String getCategory() { return category; }
    public BigDecimal getPrice() { return price; }
    public boolean isInStock() { return inStock; }
}
