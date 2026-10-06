package com.acme.orders.dto;
public class OrderSummary {
    private Long id;
    private String customer;
    private OrderStatus status;
    private java.math.BigDecimal total;
    private java.time.LocalDate placedOn;
}
