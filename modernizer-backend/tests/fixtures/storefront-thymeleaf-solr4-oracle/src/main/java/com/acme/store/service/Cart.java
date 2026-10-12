package com.acme.store.service;

import com.acme.store.domain.CartItem;
import com.acme.store.domain.Product;
import java.io.Serializable;
import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.context.annotation.Scope;
import org.springframework.context.annotation.ScopedProxyMode;
import org.springframework.stereotype.Component;

/** Session-scoped shopping cart. */
@Component
@Scope(value = "session", proxyMode = ScopedProxyMode.TARGET_CLASS)
public class Cart implements Serializable {
    private static final long serialVersionUID = 1L;
    static final int MAX_QUANTITY = 10;

    private final Map<Long, CartItem> items = new LinkedHashMap<Long, CartItem>();

    public void add(Product product, int quantity) {
        if (!product.inStock()) {
            throw new IllegalStateException(product.getName() + " is out of stock");
        }
        CartItem item = items.get(product.getId());
        int wanted = (item == null ? 0 : item.getQuantity()) + quantity;
        int capped = Math.min(Math.min(wanted, MAX_QUANTITY), product.getStock());
        if (item == null) {
            items.put(product.getId(), new CartItem(product.getId(), product.getName(), product.getPrice(), capped));
        } else {
            item.setQuantity(capped);
        }
    }

    public void remove(Long productId) {
        items.remove(productId);
    }

    public Iterable<CartItem> getItems() {
        return items.values();
    }

    public int getCount() {
        int n = 0;
        for (CartItem i : items.values()) {
            n += i.getQuantity();
        }
        return n;
    }

    public BigDecimal getTotal() {
        BigDecimal total = BigDecimal.ZERO;
        for (CartItem i : items.values()) {
            total = total.add(i.getLineTotal());
        }
        return total;
    }
}
