package com.acme.store.search;

import com.acme.store.domain.Product;
import com.acme.store.domain.SearchResult;
import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.apache.solr.client.solrj.SolrQuery;
import org.apache.solr.client.solrj.SolrServer;
import org.apache.solr.client.solrj.SolrServerException;
import org.apache.solr.client.solrj.response.FacetField;
import org.apache.solr.client.solrj.response.QueryResponse;
import org.apache.solr.client.solrj.response.SpellCheckResponse;
import org.apache.solr.common.SolrDocument;
import org.apache.solr.common.SolrInputDocument;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

/** Product search on the Solr 4 "products" core: keyword search, facets, suggest and indexing. */
@Service
public class ProductSearchService {
    private static final Logger LOG = LoggerFactory.getLogger(ProductSearchService.class);
    static final int MAX_ROWS = 50;
    static final String[] FACET_FIELDS = {"category", "brand"};

    private final SolrServer solr;

    @Autowired
    public ProductSearchService(SolrServer solr) {
        this.solr = solr;
    }

    /** Builds the query the search API and the search page share — kept separate so it can be unit tested. */
    static SolrQuery buildQuery(String text, String category, String brand, Double minPrice, Double maxPrice,
                                String sort, int page, int size) {
        SolrQuery q = new SolrQuery(text == null || text.trim().isEmpty() ? "*:*" : text.trim());
        q.set("defType", "edismax");
        q.set("qf", "name^4 brand^2 description sku^10");
        q.addFilterQuery("active:true");
        if (category != null && !category.isEmpty()) {
            q.addFilterQuery("{!tag=cat}category:\"" + category.replace("\"", "") + "\"");
        }
        if (brand != null && !brand.isEmpty()) {
            q.addFilterQuery("{!tag=brand}brand:\"" + brand.replace("\"", "") + "\"");
        }
        if (minPrice != null || maxPrice != null) {
            q.addFilterQuery("price:[" + (minPrice == null ? "*" : minPrice) + " TO " + (maxPrice == null ? "*" : maxPrice) + "]");
        }
        int rows = Math.min(Math.max(size, 1), MAX_ROWS);
        q.setStart(Math.max(page, 0) * rows);
        q.setRows(rows);
        if ("price_asc".equals(sort)) {
            q.addSort("price", SolrQuery.ORDER.asc);
        } else if ("price_desc".equals(sort)) {
            q.addSort("price", SolrQuery.ORDER.desc);
        } else if ("newest".equals(sort)) {
            q.addSort("updated_at", SolrQuery.ORDER.desc);
        }
        q.setFacet(true);
        q.setFacetMinCount(1);
        q.addFacetField("{!ex=cat}category", "{!ex=brand}brand");
        q.setHighlight(true);
        q.addHighlightField("description");
        q.setHighlightSnippets(1);
        q.setHighlightFragsize(160);
        q.set("spellcheck", true);
        q.set("spellcheck.collate", true);
        return q;
    }

    public SearchResult search(String text, String category, String brand, Double minPrice, Double maxPrice,
                               String sort, int page, int size) {
        SolrQuery q = buildQuery(text, category, brand, minPrice, maxPrice, sort, page, size);
        try {
            QueryResponse rsp = solr.query(q);
            SearchResult result = new SearchResult();
            result.setTotal(rsp.getResults().getNumFound());
            result.setPage(page);
            result.setSize(q.getRows());
            Map<String, Map<String, List<String>>> highlights = rsp.getHighlighting();
            for (SolrDocument doc : rsp.getResults()) {
                SearchResult.Hit hit = new SearchResult.Hit();
                hit.setId((String) doc.getFieldValue("id"));
                hit.setSku((String) doc.getFieldValue("sku"));
                hit.setName((String) doc.getFieldValue("name"));
                hit.setBrand((String) doc.getFieldValue("brand"));
                Object price = doc.getFieldValue("price");
                hit.setPrice(price == null ? 0d : ((Number) price).doubleValue());
                if (highlights != null && highlights.get(hit.getId()) != null) {
                    List<String> snippets = highlights.get(hit.getId()).get("description");
                    hit.setHighlight(snippets == null || snippets.isEmpty() ? null : snippets.get(0));
                }
                result.getHits().add(hit);
            }
            if (rsp.getFacetFields() != null) {
                for (FacetField field : rsp.getFacetFields()) {
                    Map<String, Long> counts = new LinkedHashMap<String, Long>();
                    for (FacetField.Count c : field.getValues()) {
                        counts.put(c.getName(), c.getCount());
                    }
                    result.getFacets().put(field.getName(), counts);
                }
            }
            SpellCheckResponse spell = rsp.getSpellCheckResponse();
            if (spell != null && !spell.isCorrectlySpelled() && spell.getCollatedResult() != null) {
                result.setSpellcheck(spell.getCollatedResult());
            }
            return result;
        } catch (SolrServerException e) {
            LOG.error("Solr search failed for '{}'", text, e);
            throw new SearchUnavailableException(e);
        }
    }

    /** Type-ahead from the /suggest handler (Solr 4 SuggestComponent). */
    public List<String> suggest(String prefix) {
        SolrQuery q = new SolrQuery();
        q.setRequestHandler("/suggest");
        q.set("suggest", true);
        q.set("suggest.q", prefix);
        q.set("suggest.count", 8);
        try {
            QueryResponse rsp = solr.query(q);
            List<String> out = new ArrayList<String>();
            Object suggest = rsp.getResponse().findRecursive("suggest", "productSuggester", prefix, "suggestions");
            if (suggest instanceof List) {
                for (Object s : (List<?>) suggest) {
                    Object term = ((org.apache.solr.common.util.NamedList<?>) s).get("term");
                    if (term != null) {
                        out.add(term.toString());
                    }
                }
            }
            return out;
        } catch (SolrServerException e) {
            LOG.warn("Suggest failed for '{}': {}", prefix, e.getMessage());
            return new ArrayList<String>();
        }
    }

    public void index(List<Product> products) {
        List<SolrInputDocument> docs = new ArrayList<SolrInputDocument>();
        for (Product p : products) {
            SolrInputDocument d = new SolrInputDocument();
            d.addField("id", "product-" + p.getId());
            d.addField("sku", p.getSku());
            d.addField("name", p.getName());
            d.addField("description", p.getDescription());
            d.addField("category", p.getCategory());
            d.addField("brand", p.getBrand());
            d.addField("price", p.getPrice() == null ? null : p.getPrice().doubleValue());
            d.addField("stock", p.getStock());
            d.addField("active", Boolean.TRUE.equals(p.getActive()));
            d.addField("updated_at", p.getUpdatedAt());
            docs.add(d);
        }
        try {
            solr.add(docs);
            solr.commit(false, true, true);
        } catch (SolrServerException | IOException e) {
            throw new SearchUnavailableException(e);
        }
    }

    public void deleteAll() {
        try {
            solr.deleteByQuery("*:*");
            solr.commit();
        } catch (SolrServerException | IOException e) {
            throw new SearchUnavailableException(e);
        }
    }
}
