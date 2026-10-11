package com.acme.bank.repo;

import com.acme.bank.domain.Customer;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface CustomerRepository extends JpaRepository<Customer, Long> {
    List<Customer> findBySegment(String segment);
    List<Customer> findByEmailContaining(String fragment);
}
