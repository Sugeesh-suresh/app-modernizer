package com.acme.policy.search;

import com.acme.policy.domain.Policy;
import java.util.ArrayList;
import java.util.List;
import org.apache.solr.client.solrj.SolrQuery;
import org.apache.solr.client.solrj.SolrServerException;
import org.apache.solr.client.solrj.impl.HttpSolrServer;
import org.apache.solr.common.SolrDocument;
import org.apache.solr.common.SolrInputDocument;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class PolicySearchService {

    @Autowired
    private HttpSolrServer solrServer;

    public List<String> searchByHolder(String name, int rows) throws SolrServerException {
        SolrQuery query = new SolrQuery("holder_name:" + name);
        query.setRows(rows);
        query.addSort("premium", SolrQuery.ORDER.desc);
        List<String> numbers = new ArrayList<String>();
        for (SolrDocument d : solrServer.query(query).getResults()) {
            numbers.add((String) d.getFieldValue("policy_number"));
        }
        return numbers;
    }

    public void index(Policy policy) throws Exception {
        SolrInputDocument doc = new SolrInputDocument();
        doc.addField("id", String.valueOf(policy.getId()));
        doc.addField("policy_number", policy.getPolicyNumber());
        doc.addField("holder_name", policy.getHolderName());
        doc.addField("premium", policy.getPremium().doubleValue());
        doc.addField("status", policy.getStatus());
        solrServer.add(doc);
        solrServer.commit();
    }
}
