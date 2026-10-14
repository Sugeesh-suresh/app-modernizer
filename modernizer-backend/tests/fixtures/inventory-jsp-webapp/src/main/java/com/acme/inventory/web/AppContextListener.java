package com.acme.inventory.web;

import com.acme.inventory.dao.JdbcProductDao;
import com.acme.inventory.service.InventoryService;
import com.acme.inventory.service.PricingService;
import javax.naming.InitialContext;
import javax.naming.NamingException;
import javax.servlet.ServletContext;
import javax.servlet.ServletContextEvent;
import javax.servlet.ServletContextListener;
import javax.sql.DataSource;

public class AppContextListener implements ServletContextListener {
    @Override
    public void contextInitialized(ServletContextEvent sce) {
        ServletContext ctx = sce.getServletContext();
        try {
            DataSource ds = (DataSource) new InitialContext().lookup("java:comp/env/jdbc/inventory");
            JdbcProductDao dao = new JdbcProductDao(ds);
            ctx.setAttribute("productDao", dao);
            ctx.setAttribute("inventoryService", new InventoryService(dao));
        } catch (NamingException e) {
            ctx.log("DataSource jdbc/inventory not available", e);
        }
        ctx.setAttribute("pricingService", new PricingService());
    }

    @Override
    public void contextDestroyed(ServletContextEvent sce) {
        sce.getServletContext().removeAttribute("productDao");
        sce.getServletContext().removeAttribute("inventoryService");
        sce.getServletContext().removeAttribute("pricingService");
    }
}
