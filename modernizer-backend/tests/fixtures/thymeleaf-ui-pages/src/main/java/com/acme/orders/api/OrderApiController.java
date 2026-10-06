package com.acme.orders.api;

import com.acme.orders.dto.*;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/orders")
public class OrderApiController {
    private final OrderService service;

    @GetMapping("/{id}/status")
    public StatusResponse status(@PathVariable Long id) {
        return service.status(id);
    }

    @PostMapping("/{id}/cancel")
    @PreAuthorize("hasRole('ORDER_ADMIN')")
    public ResponseEntity<StatusResponse> cancel(@PathVariable Long id) {
        if (!service.isOpen(id)) {
            throw new OrderNotOpenException(id);
        }
        return ResponseEntity.ok(service.cancel(id));
    }
}
