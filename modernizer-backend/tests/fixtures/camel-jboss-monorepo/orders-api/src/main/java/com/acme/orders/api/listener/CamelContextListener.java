package com.acme.orders.api.listener;

import javax.servlet.ServletContextEvent;
import javax.servlet.ServletContextListener;

import org.apache.camel.CamelContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.context.WebApplicationContext;
import org.springframework.web.context.support.WebApplicationContextUtils;

/**
 * Makes sure the Camel context is started once the Spring root context is up and stopped
 * before the web application goes away. Registered after ContextLoaderListener in web.xml.
 */
public class CamelContextListener implements ServletContextListener {

    private static final Logger LOG = LoggerFactory.getLogger(CamelContextListener.class);

    @Override
    public void contextInitialized(ServletContextEvent sce) {
        WebApplicationContext spring = WebApplicationContextUtils.getWebApplicationContext(sce.getServletContext());
        if (spring == null) {
            LOG.warn("No Spring root context found; Camel is not started");
            return;
        }
        try {
            CamelContext camel = spring.getBean(CamelContext.class);
            if (!camel.getStatus().isStarted()) {
                LOG.info("Starting Camel context {}", camel.getName());
                camel.start();
            }
        } catch (Exception e) {
            throw new IllegalStateException("Cannot start Camel context", e);
        }
    }

    @Override
    public void contextDestroyed(ServletContextEvent sce) {
        WebApplicationContext spring = WebApplicationContextUtils.getWebApplicationContext(sce.getServletContext());
        if (spring == null) {
            return;
        }
        try {
            CamelContext camel = spring.getBean(CamelContext.class);
            LOG.info("Stopping Camel context {}", camel.getName());
            camel.stop();
        } catch (Exception e) {
            LOG.warn("Error while stopping Camel context", e);
        }
    }
}
