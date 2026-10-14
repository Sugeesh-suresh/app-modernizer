package com.acme.orders.api;

import static org.hamcrest.CoreMatchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import com.acme.orders.api.error.ApiExceptionHandler;
import com.acme.orders.api.repository.CustomerRepository;
import com.acme.orders.api.web.CustomerController;

public class CustomerControllerTest {

    private final MockMvc mvc = MockMvcBuilders
            .standaloneSetup(new CustomerController(new CustomerRepository()))
            .setControllerAdvice(new ApiExceptionHandler())
            .build();

    @Test
    public void listCustomers() throws Exception {
        mvc.perform(get("/api/customers"))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("Northwind Traders")))
                .andExpect(content().string(containsString("Fabrikam Industrial")));
    }

    @Test
    public void getCustomer() throws Exception {
        mvc.perform(get("/api/customers/C-200"))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("buying@contoso.test")));
    }

    @Test
    public void unknownCustomerIs404() throws Exception {
        mvc.perform(get("/api/customers/C-999"))
                .andExpect(status().isNotFound())
                .andExpect(content().string(containsString("Customer C-999 not found")));
    }
}
