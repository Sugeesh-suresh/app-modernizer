package com.acme.orders.camel.predicate;

import org.apache.camel.Exchange;
import org.apache.camel.Predicate;

import com.acme.orders.model.Order;

public class PriorityPredicate implements Predicate {

    @Override
    public boolean matches(Exchange exchange) {
        Order order = exchange.getIn().getBody(Order.class);
        return order != null && order.isPriority();
    }
}
