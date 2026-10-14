package com.acme.orders.camel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;

import org.apache.camel.CamelContext;
import org.apache.camel.ProducerTemplate;
import org.junit.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;

public class CamelRoutesConfigTest {

    @Test
    public void configExposesContextAndTemplate() {
        AnnotationConfigApplicationContext ctx = new AnnotationConfigApplicationContext(CamelRoutesConfig.class);
        try {
            CamelContext camel = ctx.getBean(CamelContext.class);
            assertNotNull(ctx.getBean(ProducerTemplate.class));
            assertEquals("orderCamelContext", camel.getName());
            assertNotNull(camel.getRoute("order-intake"));
            assertNotNull(camel.getRoute("customer-lookup"));
        } finally {
            ctx.close();
        }
    }
}
