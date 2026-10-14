package com.acme.shop.service;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertSame;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.acme.shop.dao.ProductDao;
import com.acme.shop.model.Product;
import java.math.BigDecimal;
import org.junit.Before;
import org.junit.Test;

public class ProductServiceTest {

    private ProductDao dao;
    private ProductService service;

    @Before
    public void setUp() {
        dao = mock(ProductDao.class);
        service = new ProductService(dao);
        service.setPageSize(5);
        service.setCurrencySymbol("EUR ");
    }

    private Product product(long id, int stock) {
        return new Product(id, "SKU-" + id, "Item " + id, new BigDecimal("10.00"), stock);
    }

    @Test(expected = ProductNotFoundException.class)
    public void getThrowsWhenMissing() {
        when(dao.findById(1L)).thenReturn(null);
        service.get(1L);
    }

    @Test
    public void createInsertsWhenSkuIsFree() {
        Product p = product(0, 1);
        when(dao.findBySku(p.getSku())).thenReturn(null);
        when(dao.insert(p)).thenReturn(p);
        assertSame(p, service.create(p));
    }

    @Test(expected = DuplicateSkuException.class)
    public void createRejectsDuplicateSku() {
        Product p = product(2, 1);
        when(dao.findBySku(p.getSku())).thenReturn(p);
        try {
            service.create(p);
        } finally {
            verify(dao, never()).insert(any(Product.class));
        }
    }

    @Test
    public void adjustStockUpdatesDao() {
        when(dao.findById(3L)).thenReturn(product(3, 10));
        assertEquals(7, service.adjustStock(3L, -3).getStock());
        verify(dao).updateStock(3L, 7);
    }

    @Test(expected = InsufficientStockException.class)
    public void adjustStockRejectsNegativeResult() {
        when(dao.findById(4L)).thenReturn(product(4, 2));
        service.adjustStock(4L, -5);
    }

    @Test
    public void formatsPriceWithCurrencySymbol() {
        assertEquals("EUR 1,234.50", service.formatPrice(new BigDecimal("1234.5")));
    }

    @Test
    public void pageCountRoundsUp() {
        when(dao.count("x")).thenReturn(11);
        assertEquals(3, service.pageCount("x"));
    }
}
