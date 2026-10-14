package com.acme.shop.dao;

import com.acme.shop.model.Product;
import java.util.List;

public interface ProductDao {

    Product findById(long id);

    Product findBySku(String sku);

    List<Product> search(String query, int offset, int limit);

    int count(String query);

    Product insert(Product product);

    void updateStock(long id, int stock);
}
