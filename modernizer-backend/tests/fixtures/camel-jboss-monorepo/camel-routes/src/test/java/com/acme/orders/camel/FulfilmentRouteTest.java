package com.acme.orders.camel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.io.File;

import org.apache.camel.RoutesBuilder;
import org.apache.camel.builder.AdviceWithRouteBuilder;
import org.apache.camel.component.mock.MockEndpoint;
import org.junit.Test;

import com.acme.orders.camel.routes.FulfilmentRoute;
import com.acme.orders.model.Order;
import com.acme.orders.model.OrderStatus;
import com.acme.orders.model.Shipment;

public class FulfilmentRouteTest extends AbstractRouteTest {

    @Override
    protected RoutesBuilder createRouteBuilder() {
        return new FulfilmentRoute();
    }

    @Test
    public void writesShipmentFileAndNotifies() throws Exception {
        context.getRouteDefinition("fulfilment").adviceWith(context, new AdviceWithRouteBuilder() {
            @Override
            public void configure() {
                weaveByToUri("direct:notify").replace().to("mock:notify");
            }
        });
        context.start();

        File out = new File("target/outbox/shipment-SHP-ORD-77.json");
        out.delete();
        MockEndpoint notify = getMockEndpoint("mock:notify");
        notify.expectedMessageCount(1);
        notify.expectedHeaderReceived("carrier", "EXPRESS-AIR");

        Order o = order("ORD-77", true, 2);
        template.sendBody("seda:fulfilment", o);

        assertMockEndpointsSatisfied();
        assertEquals(OrderStatus.SHIPPED, o.getStatus());
        Shipment s = shipmentService.findByOrderId("ORD-77");
        assertNotNull(s);
        assertTrue(out.exists());
    }
}
