package com.acme.claims.web;

import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

@Controller
@RequestMapping("/claims")
public class ClaimPageController {
    private final RestTemplate rest = new RestTemplate();

    @GetMapping
    public String list(@RequestParam(required = false) String status, Model model) {
        model.addAttribute("status", status);
        return "claims/list";
    }

    @GetMapping("/{id}")
    public String detail(@PathVariable Long id, Model model) {
        model.addAttribute("claimId", id);
        return "claims/detail";
    }

    @GetMapping("/new")
    public String newClaim(Model model) {
        return "claims/new";
    }

    @PostMapping
    public String submit(@RequestParam String policyNumber, @RequestParam String description,
                         @RequestParam Double amount) {
        rest.postForObject("http://localhost:8090/api/claims", new Object[]{policyNumber, description, amount}, Object.class);
        return "redirect:/claims";
    }
}
