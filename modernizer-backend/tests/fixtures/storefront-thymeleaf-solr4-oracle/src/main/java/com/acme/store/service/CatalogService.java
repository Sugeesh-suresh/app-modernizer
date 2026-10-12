package com.acme.store.service;

import com.acme.store.domain.Product;
import com.acme.store.repo.ProductRepository;
import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

@Service
public class CatalogService {
    private final ProductRepository products;

    @Autowired
    public CatalogService(ProductRepository products) {
        this.products = products;
    }

    @Cacheable("products")
    public Product bySku(String sku) {
        return products.findBySku(sku);
    }

    public List<Product> byCategory(String category) {
        return products.findByCategoryAndActiveTrueOrderByNameAsc(category);
    }

    @Cacheable("topSellers")
    public List<Product> topSellers() {
        return products.topSellers(8);
    }
}
