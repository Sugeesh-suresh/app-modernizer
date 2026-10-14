package com.acme.orders.camel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.apache.camel.RoutesBuilder;
import org.apache.camel.builder.AdviceWithRouteBuilder;
import org.apache.camel.component.mock.MockEndpoint;
import org.junit.Before;
import org.junit.Test;

import com.acme.orders.camel.routes.DeadLetterRoute;
import com.acme.orders.camel.routes.OrderIntakeRoute;
import com.acme.orders.model.Order;
import com.acme.orders.model.OrderStatus;

public class OrderIntakeRouteTest extends AbstractRouteTest {

    @Override
    protected RoutesBuilder[] createRouteBuilders() throws Exception {
        DeadLetterRoute dead = new DeadLetterRoute();
        dead.setDeadLetterStore(deadLetterStore);
        return new RoutesBuilder[] {new OrderIntakeRoute(), dead};
    }

    @Before
    public void adviceRoutes() throws Exception {
        context.getRouteDefinition("order-intake").adviceWith(context, new AdviceWithRouteBuilder() {
            @Override
            public void configure() {
                weaveByToUri("seda:fulfilment").replace().to("mock:fulfilment");
            }
        });
        context.getRouteDefinition("dead-letter").adviceWith(context, new AdviceWithRouteBuilder() {
            @Override
            public void configure() {
                weaveAddLast().to("mock:deadLetter");
            }
        });
        context.start();
    }

    @Test
    public void standardOrderTakesStandardLane() throws Exception {
        MockEndpoint fulfilment = getMockEndpoint("mock:fulfilment");
        fulfilment.expectedMessageCount(1);
        fulfilment.expectedHeaderReceived("lane", "standard");
        getMockEndpoint("mock:deadLetter").expectedMessageCount(0);

        template.sendBody("direct:orderIn", order("ORD-1", false, 1, 2));

        assertMockEndpointsSatisfied();
        Order routed = fulfilment.getExchanges().get(0).getIn().getBody(Order.class);
        assertEquals(OrderStatus.ACCEPTED, routed.getStatus());
    }

    @Test
    public void priorityOrderTakesExpressLane() throws Exception {
        MockEndpoint fulfilment = getMockEndpoint("mock:fulfilment");
        fulfilment.expectedMessageCount(1);
        fulfilment.expectedHeaderReceived("lane", "express");

        template.sendBody("direct:orderIn", order("ORD-2", true, 5));

        assertMockEndpointsSatisfied();
    }

    @Test
    public void everyLineIsSplitAndEnriched() throws Exception {
        MockEndpoint fulfilment = getMockEndpoint("mock:fulfilment");
        fulfilment.expectedMessageCount(1);

        Order o = order("ORD-3", false, 1, 1, 1);
        template.sendBody("direct:orderIn", o);

        assertMockEndpointsSatisfied();
        assertEquals(3, o.getLines().size());
        assertEquals("Widget, standard", o.getLines().get(0).getDescription());
        assertEquals("Widget, large", o.getLines().get(1).getDescription());
        assertEquals("Gadget", o.getLines().get(2).getDescription());
        assertEquals(1, orderRegistry.all().size());
    }

    @Test
    public void invalidOrderGoesToDeadLetter() throws Exception {
        getMockEndpoint("mock:fulfilment").expectedMessageCount(0);
        MockEndpoint dead = getMockEndpoint("mock:deadLetter");
        dead.expectedMessageCount(1);

        Order bad = order("ORD-4", false, 1);
        bad.setCustomerId(null);
        template.sendBody("direct:orderIn", bad);

        assertMockEndpointsSatisfied();
        assertEquals(OrderStatus.REJECTED, bad.getStatus());
        assertEquals(1, deadLetterStore.getEntries().size());
        assertTrue(deadLetterStore.getEntries().get(0).getReason().contains("ORD-4"));
    }
}
