package com.acme.orders.camel.routes;

import org.apache.camel.LoggingLevel;

import com.acme.orders.camel.predicate.PriorityPredicate;
import com.acme.orders.camel.processor.OrderValidationProcessor;

/** direct:orderIn -> validate -> priority choice -> split lines -> enrich -> seda:fulfilment. */
public class OrderIntakeRoute extends AbstractOrderRoute {

    @Override
    public void configure() {
        configureErrorHandling();

        from("direct:orderIn").routeId("order-intake")
            .log(LoggingLevel.INFO, "intake: received order ${body.id} for customer ${body.customerId}")
            .process(new OrderValidationProcessor())
            .choice()
                .when(new PriorityPredicate())
                    .setHeader("lane", constant("express"))
                .otherwise()
                    .setHeader("lane", constant("standard"))
            .end()
            .split(simple("${body.lines}"))
                .stopOnException()
                .beanRef("lineEnricher", "enrich")
            .end()
            .beanRef("orderRegistry", "accept")
            .inOnly("seda:fulfilment");
    }
}
