package com.acme.orders.util;

import java.math.BigDecimal;
import java.util.UUID;

import com.acme.orders.model.Order;
import com.acme.orders.model.OrderLine;

/** Small helper methods shared by the routes and the REST layer. */
public final class OrderUtil {

    private OrderUtil() {
    }

    public static BigDecimal total(Order order) {
        BigDecimal sum = BigDecimal.ZERO;
        if (order == null || order.getLines() == null) {
            return sum;
        }
        for (OrderLine line : order.getLines()) {
            if (line != null && line.getUnitPrice() != null) {
                sum = sum.add(line.getUnitPrice().multiply(BigDecimal.valueOf(line.getQuantity())));
            }
        }
        return sum;
    }

    public static String newId(String prefix) {
        return prefix + "-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase();
    }
}
