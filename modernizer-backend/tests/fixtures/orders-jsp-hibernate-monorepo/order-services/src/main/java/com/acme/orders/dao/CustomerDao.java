package com.acme.orders.dao;

import com.acme.orders.domain.Customer;
import java.util.List;
import org.hibernate.Criteria;
import org.hibernate.SessionFactory;
import org.hibernate.criterion.Projections;
import org.hibernate.criterion.Restrictions;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.orm.hibernate4.HibernateTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

/** Customers through Hibernate 4: HQL with JDBC-style parameters, Criteria, and HibernateTemplate. */
@Repository
@Transactional
public class CustomerDao {
    private final SessionFactory sessionFactory;
    private final HibernateTemplate template;

    @Autowired
    public CustomerDao(SessionFactory sessionFactory) {
        this.sessionFactory = sessionFactory;
        this.template = new HibernateTemplate(sessionFactory);
    }

    /** Type-ahead search: active customers whose name starts with the term, case-insensitive. */
    @SuppressWarnings("unchecked")
    @Transactional(readOnly = true)
    public List<Customer> search(String term) {
        return sessionFactory.getCurrentSession()
                .createQuery("from Customer c where c.active = true and upper(c.name) like upper(?) order by c.name")
                .setString(0, term + "%")
                .setMaxResults(20)
                .list();
    }

    @Transactional(readOnly = true)
    public Customer findById(long id) {
        return template.get(Customer.class, id);
    }

    @SuppressWarnings("unchecked")
    @Transactional(readOnly = true)
    public List<Customer> bySegment(String segment) {
        return (List<Customer>) template.find("from Customer c where c.segment = ? and c.active = true order by c.name", segment);
    }

    @Transactional(readOnly = true)
    public long countActive() {
        Criteria criteria = sessionFactory.getCurrentSession().createCriteria(Customer.class)
                .add(Restrictions.eq("active", true))
                .setProjection(Projections.rowCount());
        return ((Number) criteria.uniqueResult()).longValue();
    }

    public void save(Customer customer) {
        sessionFactory.getCurrentSession().saveOrUpdate(customer);
    }
}
