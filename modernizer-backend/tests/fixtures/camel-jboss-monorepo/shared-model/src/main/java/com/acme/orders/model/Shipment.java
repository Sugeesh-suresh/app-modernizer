package com.acme.orders.model;

import java.io.Serializable;
import java.util.Date;

import javax.validation.constraints.NotNull;

import javax.validation.constraints.Pattern;

public class Shipment implements Serializable {
    private static final long serialVersionUID = 1L;

    @NotNull
    @Pattern(regexp = ".*\\S.*")
    private String id;
    @NotNull
    @Pattern(regexp = ".*\\S.*")
    private String orderId;
    @NotNull
    @Pattern(regexp = ".*\\S.*")
    private String carrier;
    private String trackingNumber;
    @NotNull
    private Date shippedAt = new Date();

    public Shipment() {
    }

    public Shipment(String id, String orderId, String carrier, String trackingNumber) {
        this.id = id;
        this.orderId = orderId;
        this.carrier = carrier;
        this.trackingNumber = trackingNumber;
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getOrderId() { return orderId; }
    public void setOrderId(String orderId) { this.orderId = orderId; }
    public String getCarrier() { return carrier; }
    public void setCarrier(String carrier) { this.carrier = carrier; }
    public String getTrackingNumber() { return trackingNumber; }
    public void setTrackingNumber(String trackingNumber) { this.trackingNumber = trackingNumber; }
    public Date getShippedAt() { return shippedAt; }
    public void setShippedAt(Date shippedAt) { this.shippedAt = shippedAt; }
}
