package com.acme.store.service;

import com.acme.store.domain.Product;
import com.acme.store.repo.ProductRepository;
import com.acme.store.search.ProductSearchService;
import java.util.Date;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

/** Keeps the Solr core in step with the Oracle PRODUCTS table. */
@Service
@EnableScheduling
public class ReindexService {
    private static final Logger LOG = LoggerFactory.getLogger(ReindexService.class);

    private final ProductRepository products;
    private final ProductSearchService search;
    private volatile Date lastRun = new Date(0);

    @Autowired
    public ReindexService(ProductRepository products, ProductSearchService search) {
        this.products = products;
        this.search = search;
    }

    /** Every 5 minutes: only the products changed since the last run. */
    @Scheduled(fixedDelayString = "${store.reindex.delay-ms:300000}")
    public void incremental() {
        Date started = new Date();
        List<Product> changed = products.findChangedSince(lastRun);
        if (!changed.isEmpty()) {
            search.index(changed);
            LOG.info("Reindexed {} changed product(s)", changed.size());
        }
        lastRun = started;
    }

    public int full() {
        List<Product> all = products.findAll();
        search.deleteAll();
        search.index(all);
        lastRun = new Date();
        return all.size();
    }
}
