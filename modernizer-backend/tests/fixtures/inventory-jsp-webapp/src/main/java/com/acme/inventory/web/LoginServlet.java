package com.acme.inventory.web;

import com.acme.inventory.util.InputValidator;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import javax.servlet.http.HttpSession;

public class LoginServlet extends HttpServlet {
    private static final long serialVersionUID = 1L;
    private final Map<String, String> users = new HashMap<String, String>();

    public LoginServlet() {
        users.put("admin", "admin123");
        users.put("clerk", "clerk123");
    }

    @Override
    protected void doPost(HttpServletRequest req, HttpServletResponse resp) throws ServletException, IOException {
        String user = req.getParameter("username");
        String pass = req.getParameter("password");
        if (InputValidator.isBlank(user) || InputValidator.isBlank(pass)) {
            req.setAttribute("error", "Username and password are required");
            req.getRequestDispatcher("/login.jsp").forward(req, resp);
            return;
        }
        if (!pass.equals(users.get(user.trim()))) {
            req.setAttribute("error", "Invalid credentials");
            resp.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            req.getRequestDispatcher("/login.jsp").forward(req, resp);
            return;
        }
        HttpSession old = req.getSession(false);
        if (old != null) {
            old.invalidate();
        }
        HttpSession session = req.getSession(true);
        session.setAttribute("user", user.trim());
        session.setMaxInactiveInterval(30 * 60);
        resp.sendRedirect(req.getContextPath() + "/products");
    }

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse resp) throws ServletException, IOException {
        HttpSession session = req.getSession(false);
        if (session != null && "logout".equals(req.getParameter("action"))) {
            session.invalidate();
        }
        resp.sendRedirect(req.getContextPath() + "/login.jsp");
    }
}
