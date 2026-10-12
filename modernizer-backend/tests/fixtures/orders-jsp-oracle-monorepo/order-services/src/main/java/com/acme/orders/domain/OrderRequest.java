package com.acme.orders.domain;

import java.util.List;
import javax.validation.constraints.NotNull;
import javax.validation.constraints.Size;

/** Body of POST /api/orders. */
public class OrderRequest {
    @NotNull
    private Long customerId;
    @Size(min = 1)
    private List<OrderLine> lines;
    @Size(max = 4000)
    private String notes;

    public Long getCustomerId() { return customerId; }
    public void setCustomerId(Long customerId) { this.customerId = customerId; }
    public List<OrderLine> getLines() { return lines; }
    public void setLines(List<OrderLine> lines) { this.lines = lines; }
    public String getNotes() { return notes; }
    public void setNotes(String notes) { this.notes = notes; }
}
