package com.acme.orders.camel.routes;

import org.apache.camel.model.dataformat.JsonLibrary;

/** seda:fulfilment -> ShipmentService -> JSON file in the outbox -> direct:notify. */
public class FulfilmentRoute extends AbstractOrderRoute {

    @Override
    public void configure() {
        configureErrorHandling();

        from("seda:fulfilment").routeId("fulfilment")
            .beanRef("shipmentService", "ship")
            .setHeader("shipmentId", simple("${body.id}"))
            .setHeader("orderId", simple("${body.orderId}"))
            .setHeader("carrier", simple("${body.carrier}"))
            .marshal().json(JsonLibrary.Jackson)
            .to("file:{{outbox.dir}}?fileName=shipment-${header.shipmentId}.json")
            .to("direct:notify");
    }
}
