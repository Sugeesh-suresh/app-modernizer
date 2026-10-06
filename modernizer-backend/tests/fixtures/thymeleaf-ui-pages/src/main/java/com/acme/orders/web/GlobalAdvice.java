package com.acme.orders.web;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@ControllerAdvice
public class GlobalAdvice {
    @ModelAttribute("currentUser")
    public String currentUser(java.security.Principal principal) {
        return principal == null ? "guest" : principal.getName();
    }

    @ExceptionHandler(OrderNotOpenException.class)
    @ResponseStatus(HttpStatus.CONFLICT)
    public String notOpen() { return "error/conflict"; }
}
