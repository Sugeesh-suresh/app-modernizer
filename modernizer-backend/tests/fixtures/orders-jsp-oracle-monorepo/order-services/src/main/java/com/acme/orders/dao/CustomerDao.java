package com.acme.orders.dao;

import com.acme.orders.domain.Customer;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import javax.sql.DataSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

@Repository
public class CustomerDao {
    private final JdbcTemplate jdbc;

    @Autowired
    public CustomerDao(DataSource dataSource) {
        this.jdbc = new JdbcTemplate(dataSource);
    }

    private static final RowMapper<Customer> CUSTOMER = new RowMapper<Customer>() {
        public Customer mapRow(ResultSet rs, int i) throws SQLException {
            Customer c = new Customer();
            c.setId(rs.getLong("CUSTOMER_ID"));
            c.setName(rs.getString("NAME"));
            c.setEmail(rs.getString("EMAIL"));
            c.setSegment(rs.getString("SEGMENT"));
            c.setCreditLimit(rs.getBigDecimal("CREDIT_LIMIT"));
            return c;
        }
    };

    /** Type-ahead search; NVL and UPPER keep it case-insensitive on the Oracle side. */
    public List<Customer> search(String term) {
        return jdbc.query("SELECT CUSTOMER_ID, NAME, EMAIL, NVL(SEGMENT, 'RETAIL') SEGMENT, CREDIT_LIMIT"
                + " FROM CUSTOMERS WHERE UPPER(NAME) LIKE UPPER(?) || '%' AND ROWNUM <= 20 ORDER BY NAME",
                CUSTOMER, term);
    }

    public Customer findById(long id) {
        List<Customer> found = jdbc.query("SELECT CUSTOMER_ID, NAME, EMAIL, SEGMENT, CREDIT_LIMIT FROM CUSTOMERS"
                + " WHERE CUSTOMER_ID = ?", CUSTOMER, id);
        return found.isEmpty() ? null : found.get(0);
    }
}
