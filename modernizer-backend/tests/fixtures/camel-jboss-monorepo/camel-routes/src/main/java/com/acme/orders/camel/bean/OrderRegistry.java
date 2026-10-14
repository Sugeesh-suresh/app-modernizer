package com.acme.orders.camel.bean;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.apache.camel.Body;

import com.acme.orders.model.Order;
import com.acme.orders.model.OrderStatus;
import com.acme.orders.util.OrderUtil;

/** Registry of orders accepted by the intake route; feeds the timer-driven status report. */
public class OrderRegistry {

    private final Map<String, Order> accepted = new ConcurrentHashMap<String, Order>();

    public Order accept(@Body Order order) {
        if (order.getId() == null) {
            order.setId(OrderUtil.newId("ORD"));
        }
        order.setStatus(OrderStatus.ACCEPTED);
        accepted.put(order.getId(), order);
        return order;
    }

    public List<Order> all() {
        return new ArrayList<Order>(accepted.values());
    }

    public void clear() {
        accepted.clear();
    }
}
