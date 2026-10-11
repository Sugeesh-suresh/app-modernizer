package com.acme.bank.repo;

import com.acme.bank.domain.Account;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface AccountRepository extends JpaRepository<Account, String> {
    @Query("select a from Account a where a.accountNumber = ?1 and a.status = 'OPEN'")
    Optional<Account> findOpen(String accountNumber);
}
