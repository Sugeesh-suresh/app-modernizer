package com.acme.inventory.model;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.List;

public class Order {
    private long id;
    private String customer;
    private String region;
    private OrderStatus status = OrderStatus.NEW;
    private Date created = new Date();
    private final List<OrderLine> lines = new ArrayList<OrderLine>();

    public long getId() { return id; }
    public void setId(long id) { this.id = id; }
    public String getCustomer() { return customer; }
    public void setCustomer(String customer) { this.customer = customer; }
    public String getRegion() { return region; }
    public void setRegion(String region) { this.region = region; }
    public OrderStatus getStatus() { return status; }
    public Date getCreated() { return created; }

    public void setStatus(OrderStatus status) {
        if (this.status.isFinal()) {
            throw new IllegalStateException("Order already " + this.status.getLabel());
        }
        this.status = status;
    }

    public void addLine(OrderLine line) {
        if (status.isFinal()) {
            throw new IllegalStateException("Cannot modify a final order");
        }
        lines.add(line);
    }

    public List<OrderLine> getLines() {
        return Collections.unmodifiableList(lines);
    }

    public BigDecimal getSubtotal() {
        BigDecimal sum = BigDecimal.ZERO;
        for (OrderLine l : lines) {
            sum = sum.add(l.getLineTotal());
        }
        return sum;
    }

    public int getTotalQuantity() {
        int q = 0;
        for (OrderLine l : lines) {
            q += l.getQuantity();
        }
        return q;
    }
}
