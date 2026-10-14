package com.acme.inventory.web;

import com.acme.inventory.dao.DaoException;
import com.acme.inventory.dao.ProductDao;
import com.acme.inventory.model.Order;
import com.acme.inventory.model.OrderLine;
import com.acme.inventory.model.Product;
import com.acme.inventory.service.InsufficientStockException;
import com.acme.inventory.service.InventoryService;
import com.acme.inventory.service.PricingService;
import com.acme.inventory.util.InputValidator;
import java.io.IOException;
import java.math.BigDecimal;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

public class OrderServlet extends HttpServlet {
    private static final long serialVersionUID = 1L;

    private transient InventoryService inventory;
    private transient PricingService pricing = new PricingService();
    private transient ProductDao dao;

    public OrderServlet() {
    }

    public OrderServlet(InventoryService inventory, PricingService pricing, ProductDao dao) {
        this.inventory = inventory;
        this.pricing = pricing;
        this.dao = dao;
    }

    @Override
    protected void doPost(HttpServletRequest req, HttpServletResponse resp) throws ServletException, IOException {
        resolveCollaborators();
        String customer = req.getParameter("customer");
        String region = req.getParameter("region");
        String productIdParam = req.getParameter("productId");
        int qty = InputValidator.parsePositiveInt(req.getParameter("quantity"), -1);

        if (InputValidator.isBlank(customer) || InputValidator.isBlank(region)) {
            reject(req, resp, "Customer and region are required");
            return;
        }
        if (qty < 0) {
            reject(req, resp, "Quantity must be a positive number");
            return;
        }
        long productId;
        try {
            productId = Long.parseLong(productIdParam);
        } catch (NumberFormatException e) {
            reject(req, resp, "Invalid product");
            return;
        }
        try {
            Product p = dao.findById(productId);
            if (p == null) {
                reject(req, resp, "Product not found");
                return;
            }
            Order order = new Order();
            order.setCustomer(customer.trim());
            order.setRegion(region.trim());
            order.addLine(new OrderLine(productId, qty, p.getPrice()));
            inventory.reserveOrder(order);
            BigDecimal total = pricing.total(order.getSubtotal(), order.getRegion());
            req.getSession().setAttribute("lastOrderTotal", total);
            resp.sendRedirect(req.getContextPath() + "/order.jsp?ok=1");
        } catch (InsufficientStockException e) {
            reject(req, resp, "Only " + e.getAvailable() + " left in stock");
        } catch (DaoException e) {
            req.setAttribute("error", "Order could not be saved");
            resp.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            req.getRequestDispatcher("/error.jsp").forward(req, resp);
        }
    }

    private void resolveCollaborators() {
        if (dao == null) {
            dao = (ProductDao) getServletContext().getAttribute("productDao");
        }
        if (inventory == null) {
            inventory = (InventoryService) getServletContext().getAttribute("inventoryService");
        }
    }

    private void reject(HttpServletRequest req, HttpServletResponse resp, String msg)
            throws ServletException, IOException {
        req.setAttribute("error", msg);
        resp.setStatus(HttpServletResponse.SC_BAD_REQUEST);
        req.getRequestDispatcher("/order.jsp").forward(req, resp);
    }
}
