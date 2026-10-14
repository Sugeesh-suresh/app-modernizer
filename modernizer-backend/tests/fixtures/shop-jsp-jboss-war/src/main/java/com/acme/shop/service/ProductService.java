package com.acme.shop.service;

import com.acme.shop.dao.ProductDao;
import com.acme.shop.model.Product;
import java.math.BigDecimal;
import java.text.DecimalFormat;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional
public class ProductService {

    private static final Logger LOG = LoggerFactory.getLogger(ProductService.class);

    private final ProductDao dao;

    @Value("${shop.page.size}")
    private int pageSize = 10;

    @Value("${shop.currency.symbol}")
    private String currencySymbol = "$";

    @Autowired
    public ProductService(ProductDao dao) {
        this.dao = dao;
    }

    @Transactional(readOnly = true)
    public List<Product> search(String query, int page) {
        int p = Math.max(page, 0);
        return dao.search(query, p * pageSize, pageSize);
    }

    @Transactional(readOnly = true)
    public int pageCount(String query) {
        int total = dao.count(query);
        return (total + pageSize - 1) / pageSize;
    }

    @Transactional(readOnly = true)
    public Product get(long id) {
        Product p = dao.findById(id);
        if (p == null) {
            throw new ProductNotFoundException(id);
        }
        return p;
    }

    public Product create(Product product) {
        if (dao.findBySku(product.getSku()) != null) {
            throw new DuplicateSkuException(product.getSku());
        }
        LOG.info("Creating product {}", product.getSku());
        return dao.insert(product);
    }

    public Product adjustStock(long id, int delta) {
        Product p = get(id);
        int updated = p.getStock() + delta;
        if (updated < 0) {
            throw new InsufficientStockException(p.getSku(), p.getStock(), -delta);
        }
        dao.updateStock(id, updated);
        p.setStock(updated);
        return p;
    }

    public String formatPrice(BigDecimal price) {
        return currencySymbol + new DecimalFormat("#,##0.00").format(price);
    }

    public void setPageSize(int pageSize) { this.pageSize = pageSize; }
    public void setCurrencySymbol(String currencySymbol) { this.currencySymbol = currencySymbol; }
}
