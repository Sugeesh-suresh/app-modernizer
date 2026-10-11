package com.acme.catalog.repo;

import com.acme.catalog.domain.Product;
import java.time.LocalDateTime;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface ProductRepository extends JpaRepository<Product, String> {
    @Query(value = "SELECT * FROM products WHERE updated_at > :since", nativeQuery = true)
    List<Product> changedSince(LocalDateTime since);
}
