package com.acme.catalog.search;

import com.acme.catalog.domain.Product;
import com.acme.catalog.domain.SearchHit;
import com.acme.catalog.domain.SearchPage;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import org.apache.solr.client.solrj.SolrQuery;
import org.apache.solr.client.solrj.SolrServer;
import org.apache.solr.client.solrj.SolrServerException;
import org.apache.solr.client.solrj.response.FacetField;
import org.apache.solr.client.solrj.response.QueryResponse;
import org.apache.solr.common.SolrDocument;
import org.apache.solr.common.SolrInputDocument;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class ProductSearchService {
    private final SolrServer solr;
    private final int pageSize;

    public ProductSearchService(SolrServer solr, @Value("${catalog.search.page-size}") int pageSize) {
        this.solr = solr;
        this.pageSize = pageSize;
    }

    public SearchPage search(String q, String category, boolean inStockOnly, int page) throws SolrServerException {
        SolrQuery query = new SolrQuery(q == null || q.isEmpty() ? "*:*" : q);
        query.setRequestHandler("/select");
        if (category != null && !category.isEmpty()) {
            query.addFilterQuery("category:" + category);
        }
        if (inStockOnly) {
            query.addFilterQuery("in_stock:true");
        }
        query.setFacet(true).addFacetField("category").setFacetMinCount(1);
        query.setStart(page * pageSize).setRows(pageSize);
        QueryResponse response = solr.query(query);
        SearchPage result = new SearchPage();
        result.total = response.getResults().getNumFound();
        result.page = page;
        result.hits = new ArrayList<>();
        for (SolrDocument d : response.getResults()) {
            SearchHit h = new SearchHit();
            h.sku = (String) d.getFieldValue("id");
            h.name = (String) d.getFieldValue("name");
            h.category = (String) d.getFieldValue("category");
            h.price = (Float) d.getFieldValue("price");
            h.inStock = (Boolean) d.getFieldValue("in_stock");
            result.hits.add(h);
        }
        result.categoryFacets = new LinkedHashMap<>();
        FacetField facet = response.getFacetField("category");
        if (facet != null) {
            facet.getValues().forEach(c -> result.categoryFacets.put(c.getName(), c.getCount()));
        }
        return result;
    }

    public List<String> suggest(String prefix) throws SolrServerException {
        SolrQuery query = new SolrQuery("name_suggest:" + prefix);
        query.setRequestHandler("/suggest");
        query.setFields("name");
        List<String> names = new ArrayList<>();
        for (SolrDocument d : solr.query(query).getResults()) {
            names.add((String) d.getFieldValue("name"));
        }
        return names;
    }

    public void index(List<Product> products) throws Exception {
        List<SolrInputDocument> docs = new ArrayList<>();
        for (Product p : products) {
            SolrInputDocument doc = new SolrInputDocument();
            doc.addField("id", p.getSku());
            doc.addField("name", p.getName());
            doc.addField("description", p.getDescription());
            doc.addField("category", p.getCategory());
            doc.addField("price", p.getPrice().floatValue());
            doc.addField("in_stock", p.isInStock());
            docs.add(doc);
        }
        solr.add(docs);
        solr.commit();
    }

    public void deleteAll() throws Exception {
        solr.deleteByQuery("*:*");
        solr.commit();
    }
}
