package com.acme.orders.camel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import java.util.concurrent.TimeUnit;

import org.apache.camel.ProducerTemplate;
import org.apache.camel.builder.NotifyBuilder;
import org.apache.camel.test.spring.CamelSpringTestSupport;
import org.junit.Test;
import org.springframework.context.support.AbstractApplicationContext;
import org.springframework.context.support.ClassPathXmlApplicationContext;

import com.acme.orders.camel.bean.DeadLetterStore;
import com.acme.orders.camel.bean.OrderRegistry;
import com.acme.orders.camel.bean.ShipmentService;
import com.acme.orders.model.Order;
import com.acme.orders.model.OrderLine;
import com.acme.orders.model.OrderStatus;
import com.acme.orders.model.StatusReport;

/** Exercises the real META-INF/spring/camel-context.xml (XML route + Java DSL builders). */
public class CamelContextXmlRoutesTest extends CamelSpringTestSupport {

    @Override
    protected AbstractApplicationContext createApplicationContext() {
        return new ClassPathXmlApplicationContext("META-INF/spring/camel-context.xml");
    }

    private Order order(String id, boolean priority) {
        Order o = new Order();
        o.setId(id);
        o.setCustomerId("C-200");
        o.setPriority(priority);
        o.getLines().add(new OrderLine("SKU-1", 3, new java.math.BigDecimal("4.50")));
        return o;
    }

    @Test
    public void xmlRouteLooksUpCustomerAndMarshalsJson() {
        String json = template.requestBody("direct:customerLookup", "C-100", String.class);
        assertNotNull(json);
        assertTrue(json, json.contains("\"name\":\"Northwind Traders\""));
    }

    @Test
    public void xmlRouteSendsUnknownCustomerToDeadLetter() {
        DeadLetterStore store = applicationContext.getBean(DeadLetterStore.class);
        template.sendBody("direct:customerLookup", "C-999");
        assertEquals(1, store.getEntries().size());
        assertTrue(store.getEntries().get(0).getReason().contains("C-999"));
    }

    @Test
    public void orderFlowsFromIntakeToShipment() throws Exception {
        NotifyBuilder done = new NotifyBuilder(context).whenDone(1).wereSentTo("direct:notify").create();
        Order o = order("ORD-XML-1", true);
        template.sendBody("direct:orderIn", o);

        assertTrue("fulfilment did not complete", done.matches(10, TimeUnit.SECONDS));
        ShipmentService shipments = applicationContext.getBean(ShipmentService.class);
        assertEquals("EXPRESS-AIR", shipments.findByOrderId("ORD-XML-1").getCarrier());
        assertEquals(OrderStatus.SHIPPED, o.getStatus());
        assertTrue(new java.io.File("target/outbox/shipment-SHP-ORD-XML-1.json").exists());
    }

    @Test
    public void reportRouteSummarisesOrders() {
        Order a = order("R-1", false);
        Order b = order("R-2", false);
        b.setStatus(OrderStatus.SHIPPED);
        ProducerTemplate t = template;
        StatusReport report = t.requestBody("direct:report", Arrays.asList(a, b), StatusReport.class);
        assertEquals(2, report.getTotalOrders());
        assertEquals(1, (int) report.getCountsByStatus().get("SHIPPED"));
        assertEquals(new java.math.BigDecimal("27.00"), report.getTotalValue());
    }

    @Test
    public void timerReportRouteRunsAgainstTheRegistry() throws Exception {
        OrderRegistry registry = applicationContext.getBean(OrderRegistry.class);
        registry.accept(order("T-1", false));
        // the timer itself fires once a minute; start the route body on demand instead
        StatusReport report = template.requestBody("direct:report", registry.all(), StatusReport.class);
        assertEquals(1, report.getTotalOrders());
        assertEquals(1, (int) report.getCountsByStatus().get("ACCEPTED"));
    }
}
