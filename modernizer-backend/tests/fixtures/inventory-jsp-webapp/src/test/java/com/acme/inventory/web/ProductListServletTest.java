package com.acme.inventory.web;

import static org.hamcrest.CoreMatchers.is;
import static org.junit.Assert.assertThat;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.acme.inventory.dao.DaoException;
import com.acme.inventory.dao.ProductDao;
import com.acme.inventory.model.Product;
import java.math.BigDecimal;
import java.util.Collections;
import java.util.List;
import javax.servlet.RequestDispatcher;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;

@RunWith(MockitoJUnitRunner.class)
public class ProductListServletTest {
    @Mock private HttpServletRequest request;
    @Mock private HttpServletResponse response;
    @Mock private RequestDispatcher dispatcher;
    @Mock private ProductDao dao;

    private ProductListServlet servlet;

    @Before
    public void setUp() {
        servlet = new ProductListServlet(dao);
    }

    @Test
    public void doGet_validSearch_forwardsToProductsJsp() throws Exception {
        List<Product> found = Collections.singletonList(new Product(1, "AB-100", "Widget", BigDecimal.TEN, 5));
        when(request.getParameter("q")).thenReturn("widget");
        when(dao.count("widget")).thenReturn(1);
        when(dao.search("widget", 0, 10)).thenReturn(found);
        when(request.getRequestDispatcher("/products.jsp")).thenReturn(dispatcher);

        servlet.doGet(request, response);

        verify(request).setAttribute("products", found);
        verify(dispatcher).forward(request, response);
    }

    @Test
    public void doGet_pageBeyondLastPage_clampsToLastPage() throws Exception {
        when(request.getParameter("page")).thenReturn("99");
        when(dao.count(null)).thenReturn(25);
        when(dao.search(null, 20, 10)).thenReturn(Collections.<Product>emptyList());
        when(request.getRequestDispatcher("/products.jsp")).thenReturn(dispatcher);

        servlet.doGet(request, response);

        verify(request).setAttribute("page", 3);
        verify(request).setAttribute("pages", 3);
    }

    @Test
    public void doGet_oversizedPageSize_isCappedAtMax() throws Exception {
        when(request.getParameter("size")).thenReturn("1000");
        when(dao.count(null)).thenReturn(5);
        when(request.getRequestDispatcher("/products.jsp")).thenReturn(dispatcher);

        servlet.doGet(request, response);

        verify(dao).search(null, 0, ProductListServlet.MAX_PAGE_SIZE);
    }

    @Test
    public void doGet_searchTermTooLong_sendsBadRequest() throws Exception {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 101; i++) {
            sb.append('x');
        }
        when(request.getParameter("q")).thenReturn(sb.toString());

        servlet.doGet(request, response);

        verify(response).sendError(eq(HttpServletResponse.SC_BAD_REQUEST), anyString());
        verify(dao, never()).search(anyString(), anyInt(), anyInt());
    }

    @Test
    public void doGet_daoFailure_forwardsToErrorJsp() throws Exception {
        when(dao.count(null)).thenThrow(new DaoException("boom", new java.sql.SQLException()));
        when(request.getRequestDispatcher("/error.jsp")).thenReturn(dispatcher);

        servlet.doGet(request, response);

        verify(request).setAttribute("error", "Could not load products");
        verify(dispatcher).forward(request, response);
        assertThat(servlet != null, is(true));
    }
}
