package com.acme.shop.dao;

import com.acme.shop.model.Product;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcProductDao implements ProductDao {

    private static final RowMapper<Product> MAPPER = new RowMapper<Product>() {
        @Override
        public Product mapRow(ResultSet rs, int rowNum) throws SQLException {
            return new Product(rs.getLong("id"), rs.getString("sku"), rs.getString("name"),
                    rs.getBigDecimal("price"), rs.getInt("stock"));
        }
    };

    private final JdbcTemplate jdbc;

    @Autowired
    public JdbcProductDao(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Product findById(long id) {
        try {
            return jdbc.queryForObject("SELECT id, sku, name, price, stock FROM product WHERE id = ?", MAPPER, id);
        } catch (EmptyResultDataAccessException e) {
            return null;
        }
    }

    @Override
    public Product findBySku(String sku) {
        try {
            return jdbc.queryForObject("SELECT id, sku, name, price, stock FROM product WHERE sku = ?", MAPPER, sku);
        } catch (EmptyResultDataAccessException e) {
            return null;
        }
    }

    @Override
    public List<Product> search(String query, int offset, int limit) {
        return jdbc.query(
                "SELECT id, sku, name, price, stock FROM product WHERE LOWER(name) LIKE ? ORDER BY id LIMIT ? OFFSET ?",
                MAPPER, like(query), limit, offset);
    }

    @Override
    public int count(String query) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM product WHERE LOWER(name) LIKE ?", Integer.class, like(query));
    }

    @Override
    public Product insert(final Product p) {
        KeyHolder keys = new GeneratedKeyHolder();
        jdbc.update(new org.springframework.jdbc.core.PreparedStatementCreator() {
            @Override
            public PreparedStatement createPreparedStatement(java.sql.Connection con) throws SQLException {
                PreparedStatement ps = con.prepareStatement(
                        "INSERT INTO product (sku, name, price, stock) VALUES (?, ?, ?, ?)",
                        Statement.RETURN_GENERATED_KEYS);
                ps.setString(1, p.getSku());
                ps.setString(2, p.getName());
                ps.setBigDecimal(3, p.getPrice());
                ps.setInt(4, p.getStock());
                return ps;
            }
        }, keys);
        p.setId(keys.getKey().longValue());
        return p;
    }

    @Override
    public void updateStock(long id, int stock) {
        jdbc.update("UPDATE product SET stock = ? WHERE id = ?", stock, id);
    }

    private static String like(String q) {
        return "%" + (q == null ? "" : q.trim().toLowerCase()) + "%";
    }
}
