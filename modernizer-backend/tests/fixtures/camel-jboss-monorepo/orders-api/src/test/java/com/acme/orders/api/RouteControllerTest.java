package com.acme.orders.api;

import static org.hamcrest.CoreMatchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;

import org.apache.camel.CamelContext;
import org.apache.camel.ProducerTemplate;
import org.apache.camel.builder.RouteBuilder;
import org.apache.camel.impl.DefaultCamelContext;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import com.acme.orders.api.error.ApiExceptionHandler;
import com.acme.orders.api.repository.OrderRepository;
import com.acme.orders.api.web.RouteController;
import com.acme.orders.camel.bean.StatusReportBuilder;
import com.acme.orders.model.Order;
import com.acme.orders.model.OrderLine;

/** Endpoints 9 and 10 against a real CamelContext with a stand-in report route. */
public class RouteControllerTest {

    private CamelContext camel;
    private ProducerTemplate producer;
    private OrderRepository repository;
    private MockMvc mvc;

    @Before
    public void setUp() throws Exception {
        camel = new DefaultCamelContext();
        final StatusReportBuilder builder = new StatusReportBuilder();
        camel.addRoutes(new RouteBuilder() {
            @Override
            public void configure() {
                from("direct:report").routeId("report").bean(builder, "build");
                from("direct:orderIn").routeId("order-intake").to("mock:orderIn");
            }
        });
        camel.start();
        producer = camel.createProducerTemplate();
        repository = new OrderRepository();
        mvc = MockMvcBuilders.standaloneSetup(new RouteController(camel, producer, repository))
                .setControllerAdvice(new ApiExceptionHandler()).build();
    }

    @After
    public void tearDown() throws Exception {
        producer.stop();
        camel.stop();
    }

    @Test
    public void triggerReportRunsTheRouteOnceAndReturnsTheReport() throws Exception {
        Order o = new Order();
        o.setId("ORD-1");
        o.setCustomerId("C-100");
        o.getLines().add(new OrderLine("SKU-1", 2, new BigDecimal("12.50")));
        repository.save(o);

        mvc.perform(post("/api/routes/report/trigger"))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("\"totalOrders\":1")))
                .andExpect(content().string(containsString("\"RECEIVED\":1")))
                .andExpect(content().string(containsString("\"totalValue\":25.00")));
    }

    @Test
    public void healthListsRouteStatuses() throws Exception {
        mvc.perform(get("/api/health"))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("\"status\":\"UP\"")))
                .andExpect(content().string(containsString("\"id\":\"report\"")))
                .andExpect(content().string(containsString("\"id\":\"order-intake\"")))
                .andExpect(content().string(containsString("Started")));
    }
}
