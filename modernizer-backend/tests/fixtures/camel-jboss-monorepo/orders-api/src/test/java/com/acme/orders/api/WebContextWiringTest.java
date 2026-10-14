package com.acme.orders.api;

import static org.hamcrest.CoreMatchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.springframework.mock.web.MockServletContext;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.support.XmlWebApplicationContext;

/** Loads the real WEB-INF XML contexts (root + DispatcherServlet) and calls one endpoint. */
public class WebContextWiringTest {

    private XmlWebApplicationContext root;
    private XmlWebApplicationContext servlet;

    @Before
    public void setUp() {
        MockServletContext sc = new MockServletContext("src/main/webapp", new org.springframework.core.io.FileSystemResourceLoader());
        root = new XmlWebApplicationContext();
        root.setServletContext(sc);
        root.setConfigLocation("/WEB-INF/applicationContext.xml");
        root.refresh();

        servlet = new XmlWebApplicationContext();
        servlet.setParent(root);
        servlet.setServletContext(sc);
        servlet.setConfigLocation("/WEB-INF/api-servlet.xml");
        servlet.refresh();
    }

    @After
    public void tearDown() {
        servlet.close();
        root.close();
    }

    @Test
    public void healthEndpointIsWiredToTheRealCamelContext() throws Exception {
        MockMvc mvc = MockMvcBuilders.webAppContextSetup(servlet).build();
        mvc.perform(get("/api/health"))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("\"camelContext\":\"orderCamelContext\"")))
                .andExpect(content().string(containsString("\"id\":\"order-intake\"")));
        mvc.perform(get("/api/customers/C-100")).andExpect(status().isOk());
    }
}
