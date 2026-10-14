package com.acme.orders.api.repository;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Repository;

import com.acme.orders.model.Order;

@Repository
public class OrderRepository {

    private final Map<String, Order> orders = new ConcurrentHashMap<String, Order>();

    public List<Order> findAll() {
        return new ArrayList<Order>(orders.values());
    }

    public Order findById(String id) {
        return orders.get(id);
    }

    public Order save(Order order) {
        orders.put(order.getId(), order);
        return order;
    }

    public Order delete(String id) {
        return orders.remove(id);
    }
}
