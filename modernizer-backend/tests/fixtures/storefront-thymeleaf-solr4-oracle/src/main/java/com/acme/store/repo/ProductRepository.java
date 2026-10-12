package com.acme.store.repo;

import com.acme.store.domain.Product;
import java.util.Date;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ProductRepository extends JpaRepository<Product, Long> {

    Product findBySku(String sku);

    List<Product> findByCategoryAndActiveTrueOrderByNameAsc(String category);

    /** Products changed since the last index run (for the incremental Solr reindex). */
    @Query("select p from Product p where p.updatedAt > :since")
    List<Product> findChangedSince(@Param("since") Date since);

    /** Oracle-specific: top sellers from the ORDER_LINES history, ROWNUM-limited. */
    @Query(value = "SELECT * FROM (SELECT p.* FROM PRODUCTS p JOIN (SELECT PRODUCT_ID, SUM(QTY) SOLD FROM ORDER_LINES"
            + " WHERE ORDERED_AT > SYSDATE - 30 GROUP BY PRODUCT_ID) s ON s.PRODUCT_ID = p.PRODUCT_ID"
            + " WHERE p.ACTIVE = 1 ORDER BY s.SOLD DESC) WHERE ROWNUM <= :limit", nativeQuery = true)
    List<Product> topSellers(@Param("limit") int limit);
}
