# Data-access code (DAOs, repositories)
<!-- applies-to: jdbc, datasource, jdbctemplate, hibernate, entitymanager, repository, dao -->

Unit tests never touch a real database. Replace the connection layer with Mockito mocks. Use an in-memory database (H2, HSQLDB, Derby) ONLY if it is already a test dependency; never Testcontainers unless the query lists it and the run has Docker (assume it does not).

## Plain JDBC

```java
@Mock DataSource ds; @Mock Connection con; @Mock PreparedStatement ps; @Mock ResultSet rs;
@InjectMocks CustomerDao dao;

@Before public void wire() throws Exception {
    when(ds.getConnection()).thenReturn(con);
    when(con.prepareStatement(anyString())).thenReturn(ps);
    when(ps.executeQuery()).thenReturn(rs);
}

@Test public void mapsRowToCustomer() throws Exception {
    when(rs.next()).thenReturn(true, false);       // one row, then end
    when(rs.getLong("id")).thenReturn(7L);
    when(rs.getString("name")).thenReturn("Ada");

    Customer c = dao.findById(7L);

    assertEquals("Ada", c.getName());
    verify(ps).setLong(1, 7L);
}

@Test public void returnsNullWhenNoRow() throws Exception {
    when(rs.next()).thenReturn(false);
    assertNull(dao.findById(9L));
}

@Test public void wrapsSqlException() throws Exception {
    when(ps.executeQuery()).thenThrow(new SQLException("boom"));
    assertThrows(DataAccessException.class, () -> dao.findById(1L));
}
```

Assert: the SQL text when it is behaviour (`ArgumentCaptor<String>` on `prepareStatement`; check key fragments, not whitespace), the parameters bound (`verify(ps).setString(2, "x")`), the mapping of each column, the update count handling (`when(ps.executeUpdate()).thenReturn(0)` → "not found" branch), and cleanup (`verify(rs).close()`, `verify(con).close()`, `verify(con).rollback()` on failure). Test empty result, one row, many rows, SQL error, null column values (`rs.wasNull()`).

If the DAO obtains its connection statically (`DriverManager`, `DBUtil.getConnection()`, JNDI lookup), it is `UNTESTABLE` unless a constructor/setter accepts the connection or DataSource.

## Spring JdbcTemplate

```java
@Mock JdbcTemplate jdbc;
@Test public void usesQueryForObject() {
    when(jdbc.queryForObject(anyString(), eq(Integer.class), eq("A1"))).thenReturn(4);
    assertEquals(4, repo.stockOf("A1"));
}
```

For `query(sql, RowMapper, args)` capture the `RowMapper` with an `ArgumentCaptor` and call `mapRow(rsMock, 0)` to cover the mapping. `EmptyResultDataAccessException` is a branch worth a test: `thenThrow(new EmptyResultDataAccessException(1))`. With H2 on the classpath, `new JdbcTemplate(new EmbeddedDatabaseBuilder().setType(H2).addScript("schema.sql").build())` is acceptable (script under `src/test/resources`).

## Hibernate (SessionFactory / Session)

```java
@Mock SessionFactory sf; @Mock Session session; @Mock Query<Order> query;
when(sf.getCurrentSession()).thenReturn(session);
when(session.createQuery(anyString(), eq(Order.class))).thenReturn(query);
when(query.setParameter("status", "NEW")).thenReturn(query);   // fluent API: return the same mock
when(query.list()).thenReturn(List.of(order));
```

Fluent mocks: the simplest way is `mock(Query.class, RETURNS_SELF)` (Mockito 2.x+). `session.get(Order.class, 1L)` returning null is the "not found" branch; `session.save/persist/merge/delete` are verified.

## JPA (EntityManager)

```java
@Mock EntityManager em; @Mock TypedQuery<Order> q;
when(em.createQuery(anyString(), eq(Order.class))).thenReturn(q);
when(q.setParameter(anyString(), any())).thenReturn(q);
when(q.getResultList()).thenReturn(List.of());
```

`em.find` null, `NoResultException` from `getSingleResult`, `em.persist` verified with a captor, `em.getTransaction()` begin/commit/rollback.

## Spring Data repositories

Interfaces have no code to cover: test the services that use them with a mocked repository (`when(repo.findById(1L)).thenReturn(Optional.empty())`). Custom `@Query` methods cannot be unit-tested without a database — skip them unless an embedded DB is already present.

## Transactions

You cannot prove `@Transactional` behaviour with mocks. Test the logic (rollback on exception paths, what is saved) and leave the proxy to integration tests.
