package com.acme.store.search;

import org.apache.solr.client.solrj.SolrServer;
import org.apache.solr.client.solrj.impl.HttpSolrServer;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class SolrConfig {

    @Bean(destroyMethod = "shutdown")
    public SolrServer productsSolr(@Value("${store.solr.url}") String url,
                                   @Value("${store.solr.timeout-ms:5000}") int timeoutMs) {
        HttpSolrServer server = new HttpSolrServer(url);
        server.setConnectionTimeout(timeoutMs);
        server.setSoTimeout(timeoutMs);
        server.setMaxRetries(1);
        server.setAllowCompression(true);
        return server;
    }
}
