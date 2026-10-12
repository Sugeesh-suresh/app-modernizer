package com.acme.store.service;

import static org.junit.Assert.assertEquals;

import com.acme.store.domain.Product;
import java.math.BigDecimal;
import org.junit.Test;

public class CartTest {
    private static Product product(long id, int stock) {
        Product p = new Product();
        p.setId(id);
        p.setName("P" + id);
        p.setPrice(new BigDecimal("2.50"));
        p.setStock(stock);
        return p;
    }

    @Test
    public void quantityIsCappedByStockAndMaximum() {
        Cart cart = new Cart();
        cart.add(product(1, 3), 5);
        cart.add(product(2, 100), 25);
        assertEquals(3 + Cart.MAX_QUANTITY, cart.getCount());
        assertEquals(new BigDecimal("32.50"), cart.getTotal());
    }

    @Test(expected = IllegalStateException.class)
    public void outOfStockCannotBeAdded() {
        new Cart().add(product(3, 0), 1);
    }
}
