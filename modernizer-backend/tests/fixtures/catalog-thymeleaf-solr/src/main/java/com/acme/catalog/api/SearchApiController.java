package com.acme.catalog.api;

import com.acme.catalog.domain.SearchPage;
import com.acme.catalog.search.ProductSearchService;
import java.util.List;
import javax.validation.constraints.Max;
import javax.validation.constraints.Min;
import javax.validation.constraints.Size;
import org.apache.solr.client.solrj.SolrServerException;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/search")
@Validated
public class SearchApiController {
    private final ProductSearchService search;

    public SearchApiController(ProductSearchService search) {
        this.search = search;
    }

    @GetMapping("/products")
    public SearchPage products(@RequestParam(defaultValue = "") String q,
                               @RequestParam(required = false) String category,
                               @RequestParam(defaultValue = "false") boolean inStock,
                               @RequestParam(defaultValue = "0") @Min(0) @Max(500) int page) throws SolrServerException {
        return search.search(q, category, inStock, page);
    }

    @GetMapping("/suggest")
    public List<String> suggest(@RequestParam @Size(min = 2, max = 50) String prefix) throws SolrServerException {
        return search.suggest(prefix);
    }
}
