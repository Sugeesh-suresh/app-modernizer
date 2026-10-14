package com.acme.orders.api;

import static org.junit.Assert.assertTrue;

import javax.servlet.ServletContextEvent;

import org.apache.camel.CamelContext;
import org.apache.camel.impl.DefaultCamelContext;
import org.junit.Test;
import org.springframework.mock.web.MockServletContext;
import org.springframework.web.context.WebApplicationContext;
import org.springframework.web.context.support.StaticWebApplicationContext;

import com.acme.orders.api.listener.CamelContextListener;

public class CamelContextListenerTest {

    @Test
    public void startsAndStopsTheCamelContextWithTheServletContext() throws Exception {
        MockServletContext servletContext = new MockServletContext();
        StaticWebApplicationContext spring = new StaticWebApplicationContext();
        spring.setServletContext(servletContext);
        CamelContext camel = new DefaultCamelContext();
        spring.getBeanFactory().registerSingleton("camelContext", camel);
        spring.refresh();
        servletContext.setAttribute(WebApplicationContext.ROOT_WEB_APPLICATION_CONTEXT_ATTRIBUTE, spring);

        CamelContextListener listener = new CamelContextListener();
        ServletContextEvent event = new ServletContextEvent(servletContext);

        listener.contextInitialized(event);
        assertTrue(camel.getStatus().isStarted());

        listener.contextDestroyed(event);
        assertTrue(camel.getStatus().isStopped());
    }
}
