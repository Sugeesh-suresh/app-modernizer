package com.acme.orders.camel.routes;

import org.apache.camel.LoggingLevel;
import org.apache.camel.builder.RouteBuilder;

import com.acme.orders.camel.bean.DeadLetterStore;
import com.acme.orders.camel.processor.DeadLetterProcessor;

public class DeadLetterRoute extends RouteBuilder {

    private DeadLetterStore deadLetterStore;

    public void setDeadLetterStore(DeadLetterStore deadLetterStore) {
        this.deadLetterStore = deadLetterStore;
    }

    @Override
    public void configure() {
        from("direct:deadLetter").routeId("dead-letter")
            .process(new DeadLetterProcessor(deadLetterStore))
            .log(LoggingLevel.WARN, "dead letter: ${header.deadLetterReason}");
    }
}
