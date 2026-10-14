package com.acme.orders.model;

import java.io.Serializable;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;

import javax.validation.Valid;
import javax.validation.constraints.NotNull;
import javax.validation.constraints.Size;

import javax.validation.constraints.Pattern;

public class Order implements Serializable {
    private static final long serialVersionUID = 1L;

    private String id;

    @NotNull
    @Pattern(regexp = ".*\\S.*")
    private String customerId;

    @NotNull
    @Size(min = 1)
    @Valid
    private List<OrderLine> lines = new ArrayList<OrderLine>();

    /** Priority orders take the express lane in the intake route. */
    private boolean priority;

    @NotNull
    private OrderStatus status = OrderStatus.RECEIVED;

    @Size(max = 200)
    private String notes;

    private Date createdAt = new Date();

    public Order() {
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getCustomerId() { return customerId; }
    public void setCustomerId(String customerId) { this.customerId = customerId; }
    public List<OrderLine> getLines() { return lines; }
    public void setLines(List<OrderLine> lines) { this.lines = lines; }
    public boolean isPriority() { return priority; }
    public void setPriority(boolean priority) { this.priority = priority; }
    public OrderStatus getStatus() { return status; }
    public void setStatus(OrderStatus status) { this.status = status; }
    public String getNotes() { return notes; }
    public void setNotes(String notes) { this.notes = notes; }
    public Date getCreatedAt() { return createdAt; }
    public void setCreatedAt(Date createdAt) { this.createdAt = createdAt; }
}
