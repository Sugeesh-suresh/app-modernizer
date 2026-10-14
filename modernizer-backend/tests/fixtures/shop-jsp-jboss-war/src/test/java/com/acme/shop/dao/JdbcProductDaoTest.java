package com.acme.shop.dao;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

import com.acme.shop.model.Product;
import java.math.BigDecimal;
import java.util.List;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.test.context.junit4.SpringJUnit4ClassRunner;

@RunWith(SpringJUnit4ClassRunner.class)
@ContextConfiguration("classpath:test-context.xml")
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_EACH_TEST_METHOD)
public class JdbcProductDaoTest {

    @Autowired
    private ProductDao dao;

    @Test
    public void findsSeededProductBySku() {
        Product p = dao.findBySku("WIDGET-1");
        assertNotNull(p);
        assertEquals("Blue Widget", p.getName());
        assertEquals(0, new BigDecimal("9.99").compareTo(p.getPrice()));
    }

    @Test
    public void findByIdReturnsNullWhenMissing() {
        assertNull(dao.findById(9999L));
    }

    @Test
    public void searchIsCaseInsensitiveAndPaged() {
        assertEquals(1, dao.search("WIDGET", 0, 10).size());
        List<Product> page = dao.search("", 1, 2);
        assertEquals(2, page.size());
        assertEquals(4, dao.count(""));
    }

    @Test
    public void insertAssignsIdAndUpdateStockPersists() {
        Product saved = dao.insert(new Product(null, "NEW-1", "New Thing", new BigDecimal("5.00"), 1));
        assertNotNull(saved.getId());
        dao.updateStock(saved.getId(), 42);
        assertEquals(42, dao.findById(saved.getId()).getStock());
    }
}
