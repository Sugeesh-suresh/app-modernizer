package com.acme.store.api;

import com.acme.store.domain.SearchResult;
import com.acme.store.search.ProductSearchService;
import com.acme.store.search.SearchUnavailableException;
import com.acme.store.service.ReindexService;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/** Search APIs backed by Solr 4 — used by the Thymeleaf pages' scripts and by the mobile app. */
@RestController
@RequestMapping("/api/search")
public class SearchApiController {

    @Autowired
    private ProductSearchService search;

    @Autowired
    private ReindexService reindex;

    @GetMapping
    public SearchResult search(@RequestParam(value = "q", required = false) String q,
                               @RequestParam(value = "category", required = false) String category,
                               @RequestParam(value = "brand", required = false) String brand,
                               @RequestParam(value = "minPrice", required = false) Double minPrice,
                               @RequestParam(value = "maxPrice", required = false) Double maxPrice,
                               @RequestParam(value = "sort", required = false) String sort,
                               @RequestParam(value = "page", defaultValue = "0") int page,
                               @RequestParam(value = "size", defaultValue = "24") int size) {
        return search.search(q, category, brand, minPrice, maxPrice, sort, page, size);
    }

    @GetMapping("/suggest")
    public List<String> suggest(@RequestParam("q") String q) {
        return q.length() < 2 ? Collections.<String>emptyList() : search.suggest(q);
    }

    @PostMapping("/reindex")
    public Map<String, Object> reindexAll() {
        return Collections.<String, Object>singletonMap("indexed", reindex.full());
    }

    @ExceptionHandler(SearchUnavailableException.class)
    @ResponseStatus(HttpStatus.SERVICE_UNAVAILABLE)
    public Map<String, String> unavailable(SearchUnavailableException e) {
        return Collections.singletonMap("error", e.getMessage());
    }
}
