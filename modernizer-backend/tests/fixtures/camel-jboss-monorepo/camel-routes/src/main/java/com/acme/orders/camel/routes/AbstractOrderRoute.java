package com.acme.orders.camel.routes;

import org.apache.camel.builder.RouteBuilder;

import com.acme.orders.camel.exception.OrderValidationException;

/**
 * Shared error handling: bad orders go straight to the dead letter route, any other failure is
 * redelivered a couple of times and then handed to the dead letter channel direct:deadLetter.
 */
public abstract class AbstractOrderRoute extends RouteBuilder {

    protected void configureErrorHandling() {
        errorHandler(deadLetterChannel("direct:deadLetter")
                .maximumRedeliveries(2)
                .redeliveryDelay(10)
                .useOriginalMessage());

        onException(OrderValidationException.class)
                .maximumRedeliveries(0)
                .handled(true)
                .to("direct:deadLetter");

        onException(IllegalStateException.class)
                .maximumRedeliveries(2)
                .redeliveryDelay(10)
                .handled(true)
                .to("direct:deadLetter");
    }
}
