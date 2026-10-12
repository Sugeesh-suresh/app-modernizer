package com.acme.orders.dao;

import com.acme.orders.domain.Order;
import com.acme.orders.domain.OrderLine;
import java.sql.CallableStatement;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.util.List;
import javax.sql.DataSource;
import org.apache.log4j.Logger;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

/** Oracle access for orders: plain JDBC through JdbcTemplate plus the ORDER_PKG PL/SQL package. */
@Repository
public class OrderDao {
    private static final Logger LOG = Logger.getLogger(OrderDao.class);

    private final JdbcTemplate jdbc;
    private final DataSource dataSource;

    @Autowired
    public OrderDao(DataSource dataSource) {
        this.dataSource = dataSource;
        this.jdbc = new JdbcTemplate(dataSource);
    }

    private static final RowMapper<Order> ORDER = new RowMapper<Order>() {
        public Order mapRow(ResultSet rs, int i) throws SQLException {
            Order o = new Order();
            o.setId(rs.getLong("ORDER_ID"));
            o.setOrderNumber(rs.getString("ORDER_NO"));
            o.setCustomerId(rs.getLong("CUSTOMER_ID"));
            o.setCustomerName(rs.getString("CUSTOMER_NAME"));
            o.setStatus(rs.getString("STATUS"));
            o.setTotal(rs.getBigDecimal("TOTAL_AMT"));
            o.setCreatedAt(rs.getTimestamp("CREATED_AT"));
            o.setNotes(rs.getString("NOTES"));
            return o;
        }
    };

    /** Page of orders, newest first — Oracle ROWNUM pagination (no OFFSET/FETCH in the 11g-era SQL). */
    public List<Order> findPage(String status, int page, int size) {
        int first = page * size;
        String sql = "SELECT * FROM (SELECT q.*, ROWNUM rn FROM ("
                + " SELECT o.ORDER_ID, o.ORDER_NO, o.CUSTOMER_ID, c.NAME CUSTOMER_NAME, o.STATUS, o.TOTAL_AMT,"
                + "        o.CREATED_AT, o.NOTES"
                + "   FROM ORDERS o JOIN CUSTOMERS c ON c.CUSTOMER_ID = o.CUSTOMER_ID"
                + "  WHERE (? IS NULL OR o.STATUS = ?)"
                + "  ORDER BY o.CREATED_AT DESC) q WHERE ROWNUM <= ?) WHERE rn > ?";
        return jdbc.query(sql, ORDER, status, status, first + size, first);
    }

    public Order findById(long id) {
        List<Order> found = jdbc.query(
                "SELECT o.ORDER_ID, o.ORDER_NO, o.CUSTOMER_ID, c.NAME CUSTOMER_NAME, o.STATUS, o.TOTAL_AMT,"
                        + " o.CREATED_AT, o.NOTES FROM ORDERS o JOIN CUSTOMERS c ON c.CUSTOMER_ID = o.CUSTOMER_ID"
                        + " WHERE o.ORDER_ID = ?", ORDER, id);
        if (found.isEmpty()) {
            return null;
        }
        Order order = found.get(0);
        order.setLines(jdbc.query("SELECT LINE_ID, SKU, QTY, UNIT_PRICE FROM ORDER_LINES WHERE ORDER_ID = ? ORDER BY LINE_ID",
                new RowMapper<OrderLine>() {
                    public OrderLine mapRow(ResultSet rs, int i) throws SQLException {
                        OrderLine l = new OrderLine();
                        l.setId(rs.getLong("LINE_ID"));
                        l.setSku(rs.getString("SKU"));
                        l.setQuantity(rs.getInt("QTY"));
                        l.setUnitPrice(rs.getBigDecimal("UNIT_PRICE"));
                        return l;
                    }
                }, id));
        return order;
    }

    /** Inserts the header with the ORDERS_SEQ sequence, then each line; returns the new id. */
    public long insert(Order order) {
        Long id = jdbc.queryForObject("SELECT ORDERS_SEQ.NEXTVAL FROM DUAL", Long.class);
        jdbc.update("INSERT INTO ORDERS (ORDER_ID, ORDER_NO, CUSTOMER_ID, STATUS, TOTAL_AMT, CREATED_AT, NOTES)"
                        + " VALUES (?, 'ORD-' || LPAD(?, 8, '0'), ?, ?, ?, SYSDATE, ?)",
                id, id, order.getCustomerId(), Order.STATUS_NEW, order.getTotal(), order.getNotes());
        for (OrderLine line : order.getLines()) {
            jdbc.update("INSERT INTO ORDER_LINES (LINE_ID, ORDER_ID, SKU, QTY, UNIT_PRICE)"
                            + " VALUES (ORDER_LINES_SEQ.NEXTVAL, ?, ?, ?, ?)",
                    id, line.getSku(), line.getQuantity(), line.getUnitPrice());
        }
        return id;
    }

    /** ORDER_PKG.CHANGE_STATUS enforces the allowed transitions and writes ORDER_AUDIT. */
    public void changeStatus(long orderId, String newStatus, String user) {
        Connection con = null;
        CallableStatement cs = null;
        try {
            con = dataSource.getConnection();
            cs = con.prepareCall("{ call ORDER_PKG.CHANGE_STATUS(?, ?, ?, ?) }");
            cs.setLong(1, orderId);
            cs.setString(2, newStatus);
            cs.setString(3, user);
            cs.registerOutParameter(4, Types.VARCHAR);
            cs.execute();
            String result = cs.getString(4);
            if (!"OK".equals(result)) {
                throw new IllegalStateException("Status change rejected: " + result);
            }
        } catch (SQLException e) {
            LOG.error("ORDER_PKG.CHANGE_STATUS failed for order " + orderId, e);
            throw new IllegalStateException("Database error changing order status", e);
        } finally {
            try { if (cs != null) cs.close(); } catch (SQLException ignore) { }
            try { if (con != null) con.close(); } catch (SQLException ignore) { }
        }
    }

    public int countByStatus(String status) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM ORDERS WHERE STATUS = ?", Integer.class, status);
    }
}
