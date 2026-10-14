package com.acme.orders.camel;

import java.math.BigDecimal;

import org.apache.camel.CamelContext;
import org.apache.camel.component.properties.PropertiesComponent;
import org.apache.camel.impl.JndiRegistry;
import org.apache.camel.test.junit4.CamelTestSupport;

import com.acme.orders.camel.bean.DeadLetterStore;
import com.acme.orders.camel.bean.LineEnricher;
import com.acme.orders.camel.bean.OrderRegistry;
import com.acme.orders.camel.bean.ShipmentService;
import com.acme.orders.camel.bean.StatusReportBuilder;
import com.acme.orders.model.Order;
import com.acme.orders.model.OrderLine;

/** Plain (non-Spring) Camel tests: beans are bound into a JNDI registry. */
public abstract class AbstractRouteTest extends CamelTestSupport {

    protected final DeadLetterStore deadLetterStore = new DeadLetterStore();
    protected final OrderRegistry orderRegistry = new OrderRegistry();
    protected final ShipmentService shipmentService = new ShipmentService();

    @Override
    public boolean isUseAdviceWith() {
        return true;
    }

    @Override
    protected JndiRegistry createRegistry() throws Exception {
        JndiRegistry jndi = super.createRegistry();
        jndi.bind("deadLetterStore", deadLetterStore);
        jndi.bind("orderRegistry", orderRegistry);
        jndi.bind("shipmentService", shipmentService);
        jndi.bind("lineEnricher", new LineEnricher());
        jndi.bind("statusReportBuilder", new StatusReportBuilder());
        return jndi;
    }

    @Override
    protected CamelContext createCamelContext() throws Exception {
        CamelContext ctx = super.createCamelContext();
        ctx.addComponent("properties", new PropertiesComponent("classpath:camel.properties"));
        return ctx;
    }

    protected static Order order(String id, boolean priority, int... quantities) {
        Order o = new Order();
        o.setId(id);
        o.setCustomerId("C-100");
        o.setPriority(priority);
        int i = 1;
        for (int q : quantities) {
            o.getLines().add(new OrderLine("SKU-" + i++, q, new BigDecimal("10.00")));
        }
        return o;
    }
}
