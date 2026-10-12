package com.acme.orders.web;

import java.util.Map;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RequestParam;

/** Renders the JSP pages; the pages then talk to order-services directly with AJAX. */
@Controller
public class OrderPageController {

    @Autowired
    private OrderServicesClient services;

    @Value("${order.services.public.url}")
    private String apiBase;

    @RequestMapping(value = "/", method = RequestMethod.GET)
    public String home() {
        return "redirect:/orders";
    }

    @RequestMapping(value = "/orders", method = RequestMethod.GET)
    public String list(@RequestParam(value = "status", required = false) String status, Model model) {
        model.addAttribute("apiBase", apiBase);
        model.addAttribute("status", status);
        model.addAttribute("recent", services.recentOrders(status));
        return "orders/list";
    }

    @RequestMapping(value = "/orders/{id}", method = RequestMethod.GET)
    public String detail(@PathVariable("id") long id, Model model) {
        Map<String, Object> order = services.order(id);
        if (order == null) {
            model.addAttribute("message", "Order " + id + " could not be loaded.");
            return "common/error";
        }
        model.addAttribute("apiBase", apiBase);
        model.addAttribute("order", order);
        return "orders/detail";
    }

    @RequestMapping(value = "/orders/new", method = RequestMethod.GET)
    public String newOrder(Model model) {
        model.addAttribute("apiBase", apiBase);
        return "orders/new";
    }

    @RequestMapping(value = "/customers", method = RequestMethod.GET)
    public String customers(Model model) {
        model.addAttribute("apiBase", apiBase);
        return "customers/search";
    }
}
