package com.acme.inventory.service;

import com.acme.inventory.dao.ProductDao;
import com.acme.inventory.model.Order;
import com.acme.inventory.model.OrderLine;
import com.acme.inventory.model.OrderStatus;
import com.acme.inventory.model.Product;
import java.util.ArrayList;
import java.util.List;

public class InventoryService {
    private final ProductDao dao;

    public InventoryService(ProductDao dao) {
        this.dao = dao;
    }

    public void reserve(long productId, int qty) throws InsufficientStockException {
        if (qty <= 0) {
            throw new IllegalArgumentException("qty must be positive");
        }
        Product p = dao.findById(productId);
        if (p == null) {
            throw new IllegalArgumentException("Unknown product " + productId);
        }
        if (p.getStock() < qty) {
            throw new InsufficientStockException(productId, p.getStock(), qty);
        }
        dao.updateStock(productId, p.getStock() - qty);
    }

    public void release(long productId, int qty) {
        if (qty <= 0) {
            throw new IllegalArgumentException("qty must be positive");
        }
        Product p = dao.findById(productId);
        if (p == null) {
            throw new IllegalArgumentException("Unknown product " + productId);
        }
        dao.updateStock(productId, p.getStock() + qty);
    }

    /** Reserves every line; on failure releases what was already reserved. */
    public void reserveOrder(Order order) throws InsufficientStockException {
        List<OrderLine> done = new ArrayList<OrderLine>();
        try {
            for (OrderLine l : order.getLines()) {
                reserve(l.getProductId(), l.getQuantity());
                done.add(l);
            }
            order.setStatus(OrderStatus.RESERVED);
        } catch (InsufficientStockException e) {
            for (OrderLine l : done) {
                release(l.getProductId(), l.getQuantity());
            }
            throw e;
        }
    }

    public boolean isLowStock(long productId, int threshold) {
        Product p = dao.findById(productId);
        return p != null && p.getStock() <= threshold;
    }
}
