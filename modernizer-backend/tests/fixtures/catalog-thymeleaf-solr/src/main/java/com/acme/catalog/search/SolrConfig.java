package com.acme.catalog.search;

import org.apache.solr.client.solrj.SolrServer;
import org.apache.solr.client.solrj.impl.HttpSolrServer;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class SolrConfig {
    @Bean
    public SolrServer solrServer(@Value("${solr.url}") String url) {
        HttpSolrServer server = new HttpSolrServer(url);
        server.setConnectionTimeout(2000);
        server.setSoTimeout(5000);
        return server;
    }
}
