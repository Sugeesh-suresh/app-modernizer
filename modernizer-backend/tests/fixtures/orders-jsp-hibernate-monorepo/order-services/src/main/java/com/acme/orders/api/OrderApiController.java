package com.acme.orders.api;

import com.acme.orders.domain.Customer;
import com.acme.orders.domain.Order;
import com.acme.orders.domain.OrderRequest;
import com.acme.orders.service.OrderNotFoundException;
import com.acme.orders.service.OrderService;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import javax.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/** JSON API used by the order-web JSP pages (jQuery AJAX) and by order-web's server-side client. */
@RestController
@RequestMapping("/api")
public class OrderApiController {

    @Autowired
    private OrderService service;

    @RequestMapping(value = "/orders", method = RequestMethod.GET)
    public List<Order> list(@RequestParam(value = "status", required = false) String status,
                            @RequestParam(value = "page", defaultValue = "0") int page,
                            @RequestParam(value = "size", defaultValue = "20") int size) {
        return service.list(status, page, size);
    }

    @RequestMapping(value = "/orders/{id}", method = RequestMethod.GET)
    public Order get(@PathVariable("id") long id) {
        return service.get(id);
    }

    @RequestMapping(value = "/orders", method = RequestMethod.POST)
    @ResponseStatus(HttpStatus.CREATED)
    public Order place(@RequestBody OrderRequest request) {
        return service.place(request);
    }

    @RequestMapping(value = "/orders/{id}/approve", method = RequestMethod.POST)
    public Map<String, Object> approve(@PathVariable("id") long id, HttpServletRequest http) {
        service.approve(id, user(http));
        return status(id, "APPROVED");
    }

    @RequestMapping(value = "/orders/{id}/cancel", method = RequestMethod.POST)
    public Map<String, Object> cancel(@PathVariable("id") long id, HttpServletRequest http) {
        service.cancel(id, user(http));
        return status(id, "CANCELLED");
    }

    @RequestMapping(value = "/customers", method = RequestMethod.GET)
    public List<Customer> customers(@RequestParam(value = "q", required = false) String q) {
        return service.findCustomers(q);
    }

    @ExceptionHandler(OrderNotFoundException.class)
    public ResponseEntity<Map<String, Object>> notFound(OrderNotFoundException e) {
        return new ResponseEntity<Map<String, Object>>(error(e.getMessage()), HttpStatus.NOT_FOUND);
    }

    @ExceptionHandler({IllegalArgumentException.class, IllegalStateException.class})
    public ResponseEntity<Map<String, Object>> rejected(RuntimeException e) {
        return new ResponseEntity<Map<String, Object>>(error(e.getMessage()), HttpStatus.UNPROCESSABLE_ENTITY);
    }

    private static String user(HttpServletRequest http) {
        String user = http.getHeader("X-Order-User");
        return user == null ? "web" : user;
    }

    private static Map<String, Object> status(long id, String status) {
        Map<String, Object> body = new HashMap<String, Object>();
        body.put("id", id);
        body.put("status", status);
        return body;
    }

    private static Map<String, Object> error(String message) {
        Map<String, Object> body = new HashMap<String, Object>();
        body.put("error", message);
        return body;
    }
}
