package com.acme.inventory.dao;

import com.acme.inventory.model.Product;
import java.util.List;

public interface ProductDao {
    Product findById(long id);

    List<Product> search(String term, int offset, int limit);

    int count(String term);

    boolean updateStock(long id, int newStock);
}
