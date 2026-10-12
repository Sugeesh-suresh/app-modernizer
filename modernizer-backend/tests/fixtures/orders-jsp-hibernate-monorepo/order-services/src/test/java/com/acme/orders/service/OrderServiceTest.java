package com.acme.orders.service;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.mockito.Matchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.acme.orders.dao.CustomerDao;
import com.acme.orders.dao.OrderDao;
import com.acme.orders.domain.Customer;
import com.acme.orders.domain.Order;
import com.acme.orders.domain.OrderLine;
import com.acme.orders.domain.OrderRequest;
import java.math.BigDecimal;
import java.util.Arrays;
import org.junit.Before;
import org.junit.Test;

public class OrderServiceTest {
    private OrderDao orders;
    private CustomerDao customers;
    private OrderService service;

    @Before
    public void setUp() {
        orders = mock(OrderDao.class);
        customers = mock(CustomerDao.class);
        service = new OrderService(orders, customers);
    }

    private static OrderLine line(String sku, int qty, String price) {
        OrderLine l = new OrderLine();
        l.setSku(sku);
        l.setQuantity(qty);
        l.setUnitPrice(new BigDecimal(price));
        return l;
    }

    @Test
    public void placeTotalsTheLines() {
        Customer c = new Customer();
        c.setId(7L);
        c.setCreditLimit(new BigDecimal("500"));
        when(customers.findById(7L)).thenReturn(c);
        when(orders.insert(any(Order.class))).thenReturn(1001L);
        Order stored = new Order();
        stored.setId(1001L);
        stored.setTotal(new BigDecimal("30.00"));
        when(orders.findById(1001L)).thenReturn(stored);

        OrderRequest r = new OrderRequest();
        r.setCustomerId(7L);
        r.setLines(Arrays.asList(line("A-1", 2, "10.00"), line("B-2", 1, "10.00")));
        assertEquals(new BigDecimal("30.00"), service.place(r).getTotal());
    }

    @Test(expected = IllegalArgumentException.class)
    public void creditLimitIsEnforced() {
        Customer c = new Customer();
        c.setId(7L);
        c.setCreditLimit(new BigDecimal("5"));
        when(customers.findById(7L)).thenReturn(c);
        OrderRequest r = new OrderRequest();
        r.setCustomerId(7L);
        r.setLines(Arrays.asList(line("A-1", 1, "10.00")));
        try {
            service.place(r);
        } finally {
            verify(orders, never()).insert(any(Order.class));
        }
    }

    @Test
    public void largeOrdersNeedApproval() {
        Order o = new Order();
        o.setTotal(new BigDecimal("10000.01"));
        assertTrue(service.needsApproval(o));
        o.setTotal(new BigDecimal("10000.00"));
        assertFalse(service.needsApproval(o));
    }

    @Test(expected = IllegalStateException.class)
    public void shippedOrdersCannotBeCancelled() {
        Order o = new Order();
        o.setId(5L);
        o.setStatus(Order.STATUS_SHIPPED);
        when(orders.findById(5L)).thenReturn(o);
        service.cancel(5L, "tester");
    }
}
