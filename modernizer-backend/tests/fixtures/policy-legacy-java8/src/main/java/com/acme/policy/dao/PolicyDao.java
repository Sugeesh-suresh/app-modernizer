package com.acme.policy.dao;

import com.acme.policy.domain.Policy;
import java.util.List;
import org.hibernate.SessionFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.orm.hibernate3.support.HibernateDaoSupport;
import org.springframework.stereotype.Repository;

@Repository
public class PolicyDao extends HibernateDaoSupport {

    @Autowired
    public PolicyDao(SessionFactory sessionFactory) {
        setSessionFactory(sessionFactory);
    }

    @SuppressWarnings("unchecked")
    public List<Policy> findByStatus(String status) {
        return getHibernateTemplate().find("from Policy p where p.status = ?", status);
    }

    public Policy findById(Long id) {
        return getHibernateTemplate().get(Policy.class, id);
    }

    public Long save(Policy policy) {
        return (Long) getHibernateTemplate().save(policy);
    }

    public void delete(Policy policy) {
        getHibernateTemplate().delete(policy);
    }
}
