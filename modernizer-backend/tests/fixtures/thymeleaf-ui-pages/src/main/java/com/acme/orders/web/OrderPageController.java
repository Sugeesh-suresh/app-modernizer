package com.acme.orders.web;

import com.acme.orders.dto.*;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.annotation.*;
import javax.validation.Valid;
import java.util.List;

@Controller
@RequestMapping("/orders")
public class OrderPageController {
    private final OrderService service;

    @GetMapping
    public String list(@RequestParam(required = false) String q,
                       @RequestParam(defaultValue = "0") int page,
                       @RequestParam(required = false) OrderStatus status, Model model) {
        List<OrderSummary> orders = service.search(q, page);
        model.addAttribute("orders", orders);
        model.addAttribute("q", q);
        return "orders/list";
    }

    @GetMapping("/{id}")
    public String detail(@PathVariable Long id, Model model) {
        OrderSummary order = service.find(id);
        model.addAttribute("order", order);
        return "orders/detail";
    }

    @GetMapping("/new")
    public String newOrder(Model model) {
        model.addAttribute("orderForm", new OrderForm());
        return "orders/form";
    }

    @PostMapping
    public String create(@Valid @ModelAttribute("orderForm") OrderForm form, BindingResult result) {
        if (result.hasErrors()) {
            return "orders/form";
        }
        service.create(form);
        return "redirect:/orders";
    }
}
