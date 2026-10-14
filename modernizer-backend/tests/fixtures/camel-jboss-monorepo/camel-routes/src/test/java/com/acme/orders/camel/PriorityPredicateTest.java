package com.acme.orders.camel;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.apache.camel.Exchange;
import org.apache.camel.impl.DefaultCamelContext;
import org.apache.camel.impl.DefaultExchange;
import org.junit.Test;

import com.acme.orders.camel.predicate.PriorityPredicate;
import com.acme.orders.model.Order;

public class PriorityPredicateTest {

    private final PriorityPredicate predicate = new PriorityPredicate();

    private Exchange exchangeWith(Object body) {
        Exchange e = new DefaultExchange(new DefaultCamelContext());
        e.getIn().setBody(body);
        return e;
    }

    @Test
    public void matchesOnlyPriorityOrders() {
        Order o = new Order();
        assertFalse(predicate.matches(exchangeWith(o)));
        o.setPriority(true);
        assertTrue(predicate.matches(exchangeWith(o)));
        assertFalse(predicate.matches(exchangeWith("not an order")));
    }
}
