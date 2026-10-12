package com.acme.store.search;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import org.apache.solr.client.solrj.SolrQuery;
import org.junit.Test;

public class ProductSearchServiceTest {

    @Test
    public void blankTextSearchesEverythingActive() {
        SolrQuery q = ProductSearchService.buildQuery("  ", null, null, null, null, null, 0, 24);
        assertEquals("*:*", q.getQuery());
        assertArrayEquals(new String[] {"active:true"}, q.getFilterQueries());
    }

    @Test
    public void filtersAreTaggedSoFacetsStayMultiSelect() {
        SolrQuery q = ProductSearchService.buildQuery("tv", "Electronics", "Acme", 10d, null, "price_asc", 2, 10);
        assertTrue(Arrays.asList(q.getFilterQueries()).contains("{!tag=cat}category:\"Electronics\""));
        assertTrue(Arrays.asList(q.getFilterQueries()).contains("price:[10.0 TO *]"));
        assertEquals(Integer.valueOf(20), q.getStart());
        assertEquals("price asc", q.getSortField());
    }

    @Test
    public void rowsAreCapped() {
        assertEquals(Integer.valueOf(ProductSearchService.MAX_ROWS),
                ProductSearchService.buildQuery("x", null, null, null, null, null, 0, 500).getRows());
    }
}
