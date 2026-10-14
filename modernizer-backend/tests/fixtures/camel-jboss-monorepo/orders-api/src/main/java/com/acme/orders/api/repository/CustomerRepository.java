package com.acme.orders.api.repository;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Repository;

import com.acme.orders.model.Customer;

@Repository
public class CustomerRepository {

    private final Map<String, Customer> customers = new ConcurrentHashMap<String, Customer>();

    public CustomerRepository() {
        save(new Customer("C-100", "Northwind Traders", "orders@northwind.test", "Leeds"));
        save(new Customer("C-200", "Contoso Retail", "buying@contoso.test", "Austin"));
        save(new Customer("C-300", "Fabrikam Industrial", "po@fabrikam.test", "Rotterdam"));
    }

    public List<Customer> findAll() {
        List<Customer> list = new ArrayList<Customer>(customers.values());
        java.util.Collections.sort(list, new java.util.Comparator<Customer>() {
            @Override
            public int compare(Customer a, Customer b) {
                return a.getId().compareTo(b.getId());
            }
        });
        return list;
    }

    public Customer findById(String id) {
        return customers.get(id);
    }

    public final Customer save(Customer c) {
        customers.put(c.getId(), c);
        return c;
    }
}
