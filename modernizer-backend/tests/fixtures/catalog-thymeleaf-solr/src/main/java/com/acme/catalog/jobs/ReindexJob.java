package com.acme.catalog.jobs;

import com.acme.catalog.repo.ProductRepository;
import com.acme.catalog.search.ProductSearchService;
import java.time.LocalDateTime;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class ReindexJob {
    private final ProductRepository products;
    private final ProductSearchService search;
    private LocalDateTime lastRun = LocalDateTime.of(2000, 1, 1, 0, 0);

    public ReindexJob(ProductRepository products, ProductSearchService search) {
        this.products = products;
        this.search = search;
    }

    @Scheduled(cron = "${catalog.reindex.cron}")
    public void incremental() throws Exception {
        LocalDateTime started = LocalDateTime.now();
        search.index(products.changedSince(lastRun));
        lastRun = started;
    }

    public void full() throws Exception {
        search.deleteAll();
        search.index(products.findAll());
    }
}
