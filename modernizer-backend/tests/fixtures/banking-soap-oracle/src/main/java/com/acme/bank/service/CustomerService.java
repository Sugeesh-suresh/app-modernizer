package com.acme.bank.service;

import com.acme.bank.domain.Customer;
import com.acme.bank.domain.CustomerRequest;
import com.acme.bank.repo.CustomerRepository;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CustomerService {
    private final CustomerRepository customers;

    public CustomerService(CustomerRepository customers) {
        this.customers = customers;
    }

    public List<Customer> list(String segment) {
        return segment == null ? customers.findAll() : customers.findBySegment(segment);
    }

    public Customer get(Long id) {
        return customers.findById(id).orElseThrow(() -> new CustomerNotFoundException(id));
    }

    @Transactional
    public Customer create(CustomerRequest request) {
        Customer c = new Customer();
        c.setFullName(request.fullName);
        c.setEmail(request.email);
        c.setSegment(request.segment == null ? "RETAIL" : request.segment);
        return customers.save(c);
    }

    @Transactional
    public Customer update(Long id, CustomerRequest request) {
        Customer c = get(id);
        c.setFullName(request.fullName);
        c.setEmail(request.email);
        return customers.save(c);
    }

    @Transactional
    public void delete(Long id) {
        customers.delete(get(id));
    }
}
