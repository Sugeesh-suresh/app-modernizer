package com.acme.store.domain;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** What the search API and the search page get back from Solr. */
public class SearchResult {
    private long total;
    private int page;
    private int size;
    private List<Hit> hits = new ArrayList<Hit>();
    private Map<String, Map<String, Long>> facets = new LinkedHashMap<String, Map<String, Long>>();
    private String spellcheck;

    public long getTotal() { return total; }
    public void setTotal(long total) { this.total = total; }
    public int getPage() { return page; }
    public void setPage(int page) { this.page = page; }
    public int getSize() { return size; }
    public void setSize(int size) { this.size = size; }
    public List<Hit> getHits() { return hits; }
    public Map<String, Map<String, Long>> getFacets() { return facets; }
    public String getSpellcheck() { return spellcheck; }
    public void setSpellcheck(String spellcheck) { this.spellcheck = spellcheck; }

    public static class Hit {
        private String id;
        private String sku;
        private String name;
        private String brand;
        private double price;
        private String highlight;

        public String getId() { return id; }
        public void setId(String id) { this.id = id; }
        public String getSku() { return sku; }
        public void setSku(String sku) { this.sku = sku; }
        public String getName() { return name; }
        public void setName(String name) { this.name = name; }
        public String getBrand() { return brand; }
        public void setBrand(String brand) { this.brand = brand; }
        public double getPrice() { return price; }
        public void setPrice(double price) { this.price = price; }
        public String getHighlight() { return highlight; }
        public void setHighlight(String highlight) { this.highlight = highlight; }
    }
}
