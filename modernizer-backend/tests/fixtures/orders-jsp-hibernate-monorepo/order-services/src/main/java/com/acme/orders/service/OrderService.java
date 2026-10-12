package com.acme.orders.service;

import com.acme.orders.dao.CustomerDao;
import com.acme.orders.dao.OrderDao;
import com.acme.orders.domain.Customer;
import com.acme.orders.domain.Order;
import com.acme.orders.domain.OrderLine;
import com.acme.orders.domain.OrderRequest;
import java.math.BigDecimal;
import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrderService {
    /** Orders above this need a manager's approval before they ship. */
    static final BigDecimal APPROVAL_THRESHOLD = new BigDecimal("10000.00");
    static final int MAX_PAGE_SIZE = 100;

    private final OrderDao orders;
    private final CustomerDao customers;

    @Autowired
    public OrderService(OrderDao orders, CustomerDao customers) {
        this.orders = orders;
        this.customers = customers;
    }

    public List<Order> list(String status, int page, int size) {
        int pageSize = Math.min(Math.max(size, 1), MAX_PAGE_SIZE);
        return orders.findPage(status == null || status.isEmpty() ? null : status, Math.max(page, 0), pageSize);
    }

    public Order get(long id) {
        Order order = orders.findById(id);
        if (order == null) {
            throw new OrderNotFoundException(id);
        }
        return order;
    }

    @Transactional
    public Order place(OrderRequest request) {
        Customer customer = customers.findById(request.getCustomerId());
        if (customer == null) {
            throw new IllegalArgumentException("Unknown customer " + request.getCustomerId());
        }
        if (request.getLines() == null || request.getLines().isEmpty()) {
            throw new IllegalArgumentException("An order needs at least one line");
        }
        BigDecimal total = BigDecimal.ZERO;
        for (OrderLine line : request.getLines()) {
            if (line.getQuantity() <= 0) {
                throw new IllegalArgumentException("Quantity must be positive for " + line.getSku());
            }
            total = total.add(line.lineTotal());
        }
        if (customer.getCreditLimit() != null && total.compareTo(customer.getCreditLimit()) > 0) {
            throw new IllegalArgumentException("Order total " + total + " exceeds the credit limit");
        }
        Order order = new Order();
        order.setCustomerId(customer.getId());
        order.setLines(request.getLines());
        order.setTotal(total);
        order.setNotes(request.getNotes());
        long id = orders.insert(order);
        return get(id);
    }

    public boolean needsApproval(Order order) {
        return order.getTotal() != null && order.getTotal().compareTo(APPROVAL_THRESHOLD) > 0;
    }

    public void approve(long id, String user) {
        Order order = get(id);
        if (!Order.STATUS_NEW.equals(order.getStatus())) {
            throw new IllegalStateException("Only NEW orders can be approved");
        }
        orders.changeStatus(id, Order.STATUS_APPROVED, user);
    }

    public void cancel(long id, String user) {
        Order order = get(id);
        if (Order.STATUS_SHIPPED.equals(order.getStatus())) {
            throw new IllegalStateException("A shipped order cannot be cancelled");
        }
        orders.changeStatus(id, Order.STATUS_CANCELLED, user);
    }

    public List<Customer> findCustomers(String term) {
        return customers.search(term == null ? "" : term.trim());
    }
}
