package com.acme.policy.service;

import com.acme.policy.dao.PolicyDao;
import com.acme.policy.domain.Policy;
import com.acme.policy.search.PolicySearchService;
import java.util.List;
import org.apache.log4j.Logger;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional
public class PolicyService {
    private static final Logger LOG = Logger.getLogger(PolicyService.class);

    @Autowired
    private PolicyDao dao;

    @Autowired
    private PolicySearchService search;

    @Transactional(readOnly = true)
    public List<Policy> list(String status) {
        return dao.findByStatus(status == null ? "ACTIVE" : status);
    }

    @Cacheable("policies")
    @Transactional(readOnly = true)
    public Policy get(Long id) {
        Policy p = dao.findById(id);
        if (p == null) {
            throw new PolicyNotFoundException(id);
        }
        return p;
    }

    @CacheEvict(value = "policies", allEntries = true)
    public Policy create(Policy policy) {
        policy.setStatus("ACTIVE");
        dao.save(policy);
        try {
            search.index(policy);
        } catch (Exception e) {
            LOG.warn("Indexing failed for policy " + policy.getPolicyNumber(), e);
        }
        return policy;
    }

    @CacheEvict(value = "policies", key = "#id")
    public void cancel(Long id) {
        Policy p = get(id);
        p.setStatus("CANCELLED");
    }
}
