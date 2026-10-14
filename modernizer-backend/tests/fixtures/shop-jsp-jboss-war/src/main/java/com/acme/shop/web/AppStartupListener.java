package com.acme.shop.web;

import javax.servlet.ServletContextEvent;
import javax.servlet.ServletContextListener;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class AppStartupListener implements ServletContextListener {

    private static final Logger LOG = LoggerFactory.getLogger(AppStartupListener.class);

    @Override
    public void contextInitialized(ServletContextEvent sce) {
        LOG.info("Shop starting, context path {}", sce.getServletContext().getContextPath());
    }

    @Override
    public void contextDestroyed(ServletContextEvent sce) {
        LOG.info("Shop stopping");
    }
}
