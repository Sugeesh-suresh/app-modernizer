package com.acme.orders.api.web;

import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

import com.acme.orders.api.error.NotFoundException;
import com.acme.orders.api.repository.CustomerRepository;
import com.acme.orders.model.Customer;

@RestController
@RequestMapping("/api/customers")
public class CustomerController {

    private final CustomerRepository customers;

    @Autowired
    public CustomerController(CustomerRepository customers) {
        this.customers = customers;
    }

    /** 7. list customers */
    @RequestMapping(method = RequestMethod.GET)
    public List<Customer> list() {
        return customers.findAll();
    }

    /** 8. one customer */
    @RequestMapping(value = "/{id}", method = RequestMethod.GET)
    public Customer get(@PathVariable("id") String id) {
        Customer c = customers.findById(id);
        if (c == null) {
            throw new NotFoundException("Customer", id);
        }
        return c;
    }
}
