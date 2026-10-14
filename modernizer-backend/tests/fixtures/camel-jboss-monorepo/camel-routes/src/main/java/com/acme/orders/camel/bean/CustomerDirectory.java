package com.acme.orders.camel.bean;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.NoSuchElementException;

import org.apache.camel.Body;

import com.acme.orders.model.Customer;

/** Reference data used by the Spring XML route direct:customerLookup. */
public class CustomerDirectory {

    private final Map<String, Customer> customers = new LinkedHashMap<String, Customer>();

    public CustomerDirectory() {
        add(new Customer("C-100", "Northwind Traders", "orders@northwind.test", "Leeds"));
        add(new Customer("C-200", "Contoso Retail", "buying@contoso.test", "Austin"));
        add(new Customer("C-300", "Fabrikam Industrial", "po@fabrikam.test", "Rotterdam"));
    }

    private void add(Customer c) {
        customers.put(c.getId(), c);
    }

    public Customer lookup(@Body String id) {
        Customer c = customers.get(id);
        if (c == null) {
            throw new NoSuchElementException("Unknown customer " + id);
        }
        return c;
    }

    public Map<String, Customer> all() {
        return customers;
    }
}
