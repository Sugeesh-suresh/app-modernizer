package com.acme.inventory.web;

import com.acme.inventory.dao.DaoException;
import com.acme.inventory.dao.ProductDao;
import com.acme.inventory.model.Product;
import com.acme.inventory.util.InputValidator;
import java.io.IOException;
import java.util.List;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

public class ProductListServlet extends HttpServlet {
    private static final long serialVersionUID = 1L;
    static final int DEFAULT_PAGE_SIZE = 10;
    static final int MAX_PAGE_SIZE = 50;

    private transient ProductDao dao;

    public ProductListServlet() {
    }

    public ProductListServlet(ProductDao dao) {
        this.dao = dao;
    }

    public void setDao(ProductDao dao) {
        this.dao = dao;
    }

    private ProductDao dao() {
        if (dao == null) {
            dao = (ProductDao) getServletContext().getAttribute("productDao");
        }
        return dao;
    }

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse resp) throws ServletException, IOException {
        String term = req.getParameter("q");
        if (term != null && term.length() > 100) {
            resp.sendError(HttpServletResponse.SC_BAD_REQUEST, "Search term too long");
            return;
        }
        int page = InputValidator.parsePositiveInt(req.getParameter("page"), 1);
        int size = Math.min(InputValidator.parsePositiveInt(req.getParameter("size"), DEFAULT_PAGE_SIZE),
                MAX_PAGE_SIZE);
        try {
            int total = dao().count(term);
            int pages = Math.max(1, (total + size - 1) / size);
            if (page > pages) {
                page = pages;
            }
            List<Product> products = dao().search(term, (page - 1) * size, size);
            req.setAttribute("products", products);
            req.setAttribute("page", page);
            req.setAttribute("pages", pages);
            req.setAttribute("q", InputValidator.sanitize(term));
            req.getRequestDispatcher("/products.jsp").forward(req, resp);
        } catch (DaoException e) {
            req.setAttribute("error", "Could not load products");
            req.getRequestDispatcher("/error.jsp").forward(req, resp);
        }
    }
}
