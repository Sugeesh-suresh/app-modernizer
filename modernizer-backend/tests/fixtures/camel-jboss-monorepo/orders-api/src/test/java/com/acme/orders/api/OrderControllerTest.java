package com.acme.orders.api;

import static org.hamcrest.CoreMatchers.containsString;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;

import org.apache.camel.CamelContext;
import org.apache.camel.ProducerTemplate;
import org.apache.camel.builder.RouteBuilder;
import org.apache.camel.component.mock.MockEndpoint;
import org.apache.camel.impl.DefaultCamelContext;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import com.acme.orders.api.error.ApiExceptionHandler;
import com.acme.orders.api.repository.OrderRepository;
import com.acme.orders.api.web.OrderController;
import com.acme.orders.camel.bean.ShipmentService;
import com.acme.orders.model.Order;
import com.acme.orders.model.OrderLine;

/** Orders endpoints 1-6, with a real CamelContext whose direct:orderIn ends in a mock endpoint. */
public class OrderControllerTest {

    private static final String VALID_ORDER =
            "{\"customerId\":\"C-100\",\"priority\":true,"
            + "\"lines\":[{\"sku\":\"SKU-1\",\"quantity\":2,\"unitPrice\":9.99}]}";

    private CamelContext camel;
    private ProducerTemplate producer;
    private MockEndpoint orderIn;
    private OrderRepository repository;
    private ShipmentService shipments;
    private MockMvc mvc;

    @Before
    public void setUp() throws Exception {
        camel = new DefaultCamelContext();
        camel.addRoutes(new RouteBuilder() {
            @Override
            public void configure() {
                from("direct:orderIn").to("mock:orderIn");
            }
        });
        camel.start();
        producer = camel.createProducerTemplate();
        orderIn = camel.getEndpoint("mock:orderIn", MockEndpoint.class);

        repository = new OrderRepository();
        shipments = new ShipmentService();
        mvc = MockMvcBuilders
                .standaloneSetup(new OrderController(repository, producer, shipments))
                .setControllerAdvice(new ApiExceptionHandler())
                .build();
    }

    @After
    public void tearDown() throws Exception {
        producer.stop();
        camel.stop();
    }

    private Order stored(String id) {
        Order o = new Order();
        o.setId(id);
        o.setCustomerId("C-200");
        o.getLines().add(new OrderLine("SKU-2", 1, new BigDecimal("5.00")));
        return repository.save(o);
    }

    @Test
    public void listOrders() throws Exception {
        stored("ORD-1");
        mvc.perform(get("/api/orders"))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("\"id\":\"ORD-1\"")));
    }

    @Test
    public void getOrder() throws Exception {
        stored("ORD-2");
        mvc.perform(get("/api/orders/ORD-2"))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("\"customerId\":\"C-200\"")));
    }

    @Test
    public void getUnknownOrderReturnsJson404() throws Exception {
        mvc.perform(get("/api/orders/NOPE"))
                .andExpect(status().isNotFound())
                .andExpect(content().string(containsString("Order NOPE not found")));
    }

    @Test
    public void createOrderReturns202AndSendsItIntoTheCamelRoute() throws Exception {
        mvc.perform(post("/api/orders").contentType(MediaType.APPLICATION_JSON).content(VALID_ORDER))
                .andExpect(status().isAccepted())
                .andExpect(content().string(containsString("\"status\":\"RECEIVED\"")));

        assertEquals(1, orderIn.getReceivedCounter());
        Order sent = orderIn.getExchanges().get(0).getIn().getBody(Order.class);
        assertNotNull(sent.getId());
        assertEquals(1, repository.findAll().size());
    }

    @Test
    public void createInvalidOrderReturns400WithFieldErrorsAndDoesNotCallCamel() throws Exception {
        mvc.perform(post("/api/orders").contentType(MediaType.APPLICATION_JSON)
                .content("{\"customerId\":\"\",\"lines\":[]}"))
                .andExpect(status().isBadRequest())
                .andExpect(content().string(containsString("customerId")))
                .andExpect(content().string(containsString("lines")));
        assertEquals(0, orderIn.getReceivedCounter());
    }

    @Test
    public void malformedJsonReturns400() throws Exception {
        mvc.perform(post("/api/orders").contentType(MediaType.APPLICATION_JSON).content("{oops"))
                .andExpect(status().isBadRequest())
                .andExpect(content().string(containsString("Malformed JSON")));
    }

    @Test
    public void updateOrder() throws Exception {
        stored("ORD-3");
        mvc.perform(put("/api/orders/ORD-3").contentType(MediaType.APPLICATION_JSON).content(VALID_ORDER))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("\"customerId\":\"C-100\"")));
        assertEquals("C-100", repository.findById("ORD-3").getCustomerId());
    }

    @Test
    public void deleteOrder() throws Exception {
        stored("ORD-4");
        mvc.perform(delete("/api/orders/ORD-4")).andExpect(status().isNoContent());
        mvc.perform(delete("/api/orders/ORD-4")).andExpect(status().isNotFound());
    }

    @Test
    public void getShipmentOfOrder() throws Exception {
        Order o = stored("ORD-5");
        mvc.perform(get("/api/orders/ORD-5/shipment")).andExpect(status().isNotFound());

        shipments.ship(o);
        mvc.perform(get("/api/orders/ORD-5/shipment"))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("\"carrier\":\"GROUND\"")))
                .andExpect(content().string(containsString("\"orderId\":\"ORD-5\"")));
    }
}
