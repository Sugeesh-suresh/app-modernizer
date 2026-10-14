package com.acme.inventory.dao;

import com.acme.inventory.model.Product;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import javax.sql.DataSource;

public class JdbcProductDao implements ProductDao {
    private static final String COLS = "id, sku, name, price, stock";
    private final DataSource dataSource;

    public JdbcProductDao(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @Override
    public Product findById(long id) {
        String sql = "SELECT " + COLS + " FROM product WHERE id = ?";
        try (Connection c = dataSource.getConnection();
             PreparedStatement ps = c.prepareStatement(sql)) {
            ps.setLong(1, id);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? map(rs) : null;
            }
        } catch (SQLException e) {
            throw new DaoException("findById failed for " + id, e);
        }
    }

    @Override
    public List<Product> search(String term, int offset, int limit) {
        String sql = "SELECT " + COLS + " FROM product WHERE LOWER(name) LIKE ? ORDER BY name LIMIT ? OFFSET ?";
        List<Product> out = new ArrayList<Product>();
        try (Connection c = dataSource.getConnection();
             PreparedStatement ps = c.prepareStatement(sql)) {
            ps.setString(1, like(term));
            ps.setInt(2, limit);
            ps.setInt(3, offset);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    out.add(map(rs));
                }
            }
        } catch (SQLException e) {
            throw new DaoException("search failed", e);
        }
        return out;
    }

    @Override
    public int count(String term) {
        String sql = "SELECT COUNT(*) FROM product WHERE LOWER(name) LIKE ?";
        try (Connection c = dataSource.getConnection();
             PreparedStatement ps = c.prepareStatement(sql)) {
            ps.setString(1, like(term));
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rs.getInt(1) : 0;
            }
        } catch (SQLException e) {
            throw new DaoException("count failed", e);
        }
    }

    @Override
    public boolean updateStock(long id, int newStock) {
        String sql = "UPDATE product SET stock = ? WHERE id = ?";
        try (Connection c = dataSource.getConnection();
             PreparedStatement ps = c.prepareStatement(sql)) {
            ps.setInt(1, newStock);
            ps.setLong(2, id);
            return ps.executeUpdate() == 1;
        } catch (SQLException e) {
            throw new DaoException("updateStock failed for " + id, e);
        }
    }

    private static String like(String term) {
        return "%" + (term == null ? "" : term.toLowerCase()) + "%";
    }

    private static Product map(ResultSet rs) throws SQLException {
        return new Product(rs.getLong("id"), rs.getString("sku"), rs.getString("name"),
                rs.getBigDecimal("price"), rs.getInt("stock"));
    }
}
