package com.acme.orders.camel.routes;

import com.acme.orders.camel.aggregate.ShipmentAggregationStrategy;

/** Batches shipment notifications per carrier (aggregator EIP). */
public class NotificationRoute extends AbstractOrderRoute {

    @Override
    public void configure() {
        configureErrorHandling();

        from("direct:notify").routeId("notify")
            .aggregate(header("carrier"), new ShipmentAggregationStrategy())
                .completionSize(3)
                .completionTimeout(1500)
            .log("notify: carrier ${header.carrier} dispatch batch of ${body.size()} shipment(s)")
            .to("log:com.acme.orders.notifications?level=INFO");
    }
}
