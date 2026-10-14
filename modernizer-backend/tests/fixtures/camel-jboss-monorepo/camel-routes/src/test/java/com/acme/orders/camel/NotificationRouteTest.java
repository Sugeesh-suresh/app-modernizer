package com.acme.orders.camel;

import java.util.List;

import org.apache.camel.RoutesBuilder;
import org.apache.camel.builder.AdviceWithRouteBuilder;
import org.apache.camel.component.mock.MockEndpoint;
import org.junit.Test;

import com.acme.orders.camel.routes.NotificationRoute;

public class NotificationRouteTest extends AbstractRouteTest {

    @Override
    protected RoutesBuilder createRouteBuilder() {
        return new NotificationRoute();
    }

    @Test
    public void aggregatesThreeShipmentsPerCarrier() throws Exception {
        context.getRouteDefinition("notify").adviceWith(context, new AdviceWithRouteBuilder() {
            @Override
            public void configure() {
                weaveByToUri("log:com.acme.orders.notifications*").replace().to("mock:batches");
            }
        });
        context.start();

        MockEndpoint batches = getMockEndpoint("mock:batches");
        batches.expectedMessageCount(1);

        for (int i = 0; i < 3; i++) {
            template.sendBodyAndHeader("direct:notify", "{\"id\":" + i + "}", "carrier", "GROUND");
        }
        // a different carrier never reaches the batch size inside the test window
        template.sendBodyAndHeader("direct:notify", "{\"id\":9}", "carrier", "EXPRESS-AIR");

        batches.await();
        assertMockEndpointsSatisfied();
        List<?> body = batches.getExchanges().get(0).getIn().getBody(List.class);
        org.junit.Assert.assertEquals(3, body.size());
    }
}
