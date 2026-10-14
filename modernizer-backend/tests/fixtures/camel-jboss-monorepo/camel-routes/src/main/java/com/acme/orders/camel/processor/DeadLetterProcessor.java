package com.acme.orders.camel.processor;

import org.apache.camel.Exchange;
import org.apache.camel.Processor;

import com.acme.orders.camel.bean.DeadLetterStore;
import com.acme.orders.model.Order;
import com.acme.orders.model.OrderStatus;

/** Records the failed message, marks the order REJECTED and leaves the reason in a header. */
public class DeadLetterProcessor implements Processor {

    private final DeadLetterStore store;

    public DeadLetterProcessor(DeadLetterStore store) {
        this.store = store;
    }

    @Override
    public void process(Exchange exchange) {
        Throwable cause = exchange.getProperty(Exchange.EXCEPTION_CAUGHT, Throwable.class);
        String reason = cause != null ? cause.getMessage() : "unknown";
        Object body = exchange.getIn().getBody();
        if (body instanceof Order) {
            ((Order) body).setStatus(OrderStatus.REJECTED);
        }
        exchange.getIn().setHeader("deadLetterReason", reason);
        store.add(body, reason);
    }
}
