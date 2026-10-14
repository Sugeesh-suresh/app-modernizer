package com.acme.orders.model;

import java.io.Serializable;
import java.math.BigDecimal;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.Map;

public class StatusReport implements Serializable {
    private static final long serialVersionUID = 1L;

    private Date generatedAt = new Date();
    private int totalOrders;
    private BigDecimal totalValue = BigDecimal.ZERO;
    private Map<String, Integer> countsByStatus = new LinkedHashMap<String, Integer>();

    public StatusReport() {
    }

    public Date getGeneratedAt() { return generatedAt; }
    public void setGeneratedAt(Date generatedAt) { this.generatedAt = generatedAt; }
    public int getTotalOrders() { return totalOrders; }
    public void setTotalOrders(int totalOrders) { this.totalOrders = totalOrders; }
    public BigDecimal getTotalValue() { return totalValue; }
    public void setTotalValue(BigDecimal totalValue) { this.totalValue = totalValue; }
    public Map<String, Integer> getCountsByStatus() { return countsByStatus; }
    public void setCountsByStatus(Map<String, Integer> countsByStatus) { this.countsByStatus = countsByStatus; }
}
