package com.acme.catalog.domain;

import java.util.List;
import java.util.Map;

public class SearchPage {
    public long total;
    public int page;
    public List<SearchHit> hits;
    public Map<String, Long> categoryFacets;
}
