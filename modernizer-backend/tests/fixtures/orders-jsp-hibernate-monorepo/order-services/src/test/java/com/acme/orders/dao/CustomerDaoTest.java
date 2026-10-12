package com.acme.orders.dao;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import com.acme.orders.domain.Customer;
import java.math.BigDecimal;
import java.util.List;
import java.util.Properties;
import javax.sql.DataSource;
import org.hibernate.SessionFactory;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.orm.hibernate4.HibernateTransactionManager;
import org.springframework.orm.hibernate4.LocalSessionFactoryBuilder;
import org.springframework.transaction.support.TransactionTemplate;

/** Runs the real HQL / Criteria against an in-memory H2 database. */
public class CustomerDaoTest {
    private SessionFactory sessionFactory;
    private CustomerDao dao;
    private TransactionTemplate tx;

    @Before
    public void setUp() {
        DriverManagerDataSource ds = new DriverManagerDataSource("jdbc:h2:mem:orders;DB_CLOSE_DELAY=-1", "sa", "");
        Properties props = new Properties();
        props.setProperty("hibernate.dialect", "org.hibernate.dialect.H2Dialect");
        props.setProperty("hibernate.hbm2ddl.auto", "create-drop");
        sessionFactory = new LocalSessionFactoryBuilder((DataSource) ds).addAnnotatedClasses(Customer.class)
                .addProperties(props).buildSessionFactory();
        dao = new CustomerDao(sessionFactory);
        tx = new TransactionTemplate(new HibernateTransactionManager(sessionFactory));
        tx.execute(s -> {
            dao.save(customer(1L, "Acme Corp", "CORPORATE", true));
            dao.save(customer(2L, "acme retail", null, true));
            dao.save(customer(3L, "Acorn Ltd", "CORPORATE", false));
            dao.save(customer(4L, "Beta Inc", "CORPORATE", true));
            return null;
        });
    }

    @After
    public void tearDown() {
        sessionFactory.close();
    }

    private static Customer customer(long id, String name, String segment, boolean active) {
        Customer c = new Customer();
        c.setId(id);
        c.setName(name);
        c.setSegment(segment);
        c.setActive(active);
        c.setCreditLimit(new BigDecimal("1000.00"));
        return c;
    }

    @Test
    public void searchIsCaseInsensitivePrefixOverActiveCustomers() {
        List<Customer> found = tx.execute(s -> dao.search("ac"));
        assertEquals(2, found.size());
        assertEquals("Acme Corp", found.get(0).getName());
        assertEquals("acme retail", found.get(1).getName());
    }

    @Test
    public void segmentQueryAndCountUseTheActiveFlag() {
        assertEquals(2, tx.execute(s -> dao.bySegment("CORPORATE")).size());
        assertEquals(3L, (long) tx.execute(s -> dao.countActive()));
    }

    @Test
    public void unknownCustomerIsNull() {
        assertNull(tx.execute(s -> dao.findById(99L)));
        assertEquals("RETAIL", tx.execute(s -> dao.findById(2L)).getSegment());
    }
}
