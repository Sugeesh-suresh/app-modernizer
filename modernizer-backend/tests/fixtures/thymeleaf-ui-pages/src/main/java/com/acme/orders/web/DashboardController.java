package com.acme.orders.web;

import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;

@Controller
public class DashboardController {
    @GetMapping("/attribute_search")
    public String attributeSearch(Model model) {
        model.addAttribute("userInfo", userService.current());
        return "dashboard/attribute_search";
    }
}
