package com.acme.shop.web;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.model;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.redirectedUrl;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.view;

import com.acme.shop.model.Product;
import com.acme.shop.service.ProductNotFoundException;
import com.acme.shop.service.ProductService;
import java.math.BigDecimal;
import java.util.Collections;
import org.junit.Before;
import org.junit.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.servlet.view.InternalResourceViewResolver;

public class ProductControllerTest {

    private ProductService service;
    private MockMvc mvc;

    @Before
    public void setUp() {
        service = mock(ProductService.class);
        InternalResourceViewResolver resolver = new InternalResourceViewResolver("/WEB-INF/views/", ".jsp");
        mvc = MockMvcBuilders.standaloneSetup(new ProductController(service))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setViewResolvers(resolver)
                .build();
    }

    @Test
    public void listPutsProductsInModel() throws Exception {
        when(service.search("w", 0)).thenReturn(Collections.singletonList(
                new Product(1L, "W-1", "Widget", new BigDecimal("1.00"), 3)));
        when(service.pageCount("w")).thenReturn(1);
        mvc.perform(get("/products").param("q", "w"))
                .andExpect(status().isOk())
                .andExpect(view().name("products/list"))
                .andExpect(model().attributeExists("products", "pages"));
    }

    @Test
    public void missingProductRendersErrorView() throws Exception {
        when(service.get(99L)).thenThrow(new ProductNotFoundException(99L));
        mvc.perform(get("/products/99"))
                .andExpect(status().isNotFound())
                .andExpect(view().name("error"));
    }

    @Test
    public void createRedirectsOnValidInput() throws Exception {
        when(service.create(org.mockito.ArgumentMatchers.any(Product.class))).thenAnswer(inv -> {
            Product p = inv.getArgument(0);
            p.setId(7L);
            return p;
        });
        mvc.perform(post("/products").param("sku", "ABC-1").param("name", "Thing")
                        .param("price", "3.50").param("stock", "4"))
                .andExpect(status().is3xxRedirection())
                .andExpect(redirectedUrl("/products/7"));
    }

    @Test
    public void createReturnsFormWhenInvalid() throws Exception {
        mvc.perform(post("/products").param("sku", "bad sku").param("name", "T")
                        .param("price", "0").param("stock", "-1"))
                .andExpect(status().isOk())
                .andExpect(view().name("products/form"))
                .andExpect(model().attributeHasFieldErrors("product", "sku", "name", "price", "stock"));
    }

    @Test
    public void jsonEndpointReturnsProduct() throws Exception {
        when(service.get(1L)).thenReturn(new Product(1L, "W-1", "Widget", new BigDecimal("1.00"), 3));
        mvc.perform(get("/api/products/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.sku").value("W-1"))
                .andExpect(jsonPath("$.stock").value(3));
    }
}
