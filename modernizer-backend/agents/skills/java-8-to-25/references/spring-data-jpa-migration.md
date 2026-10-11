# Persistence → Spring Data JPA

Goal: the persistence layer runs on `spring-boot-starter-data-jpa` (Hibernate ORM 7, Jakarta Persistence 3.2, HikariCP). There are no hand-built `DataSource`, `EntityManagerFactory`, `SessionFactory` or transaction-manager beans; Spring Boot auto-configures all of them from `spring.datasource.*` / `spring.jpa.*`.

## What to migrate

| Legacy persistence code | Migrate to |
|---|---|
| Hand-written JDBC DAOs (`JdbcTemplate`, raw JDBC, `RowMapper`) doing CRUD on tables | `@Entity` + Spring Data repository, behind the existing DAO interface |
| Hibernate-native code (`SessionFactory`, `HibernateTemplate`, `HibernateDaoSupport`, `hibernate.cfg.xml`, `*.hbm.xml`) | `@Entity` + Spring Data repository; delete the Hibernate config files |
| Hand-configured JPA (`LocalContainerEntityManagerFactoryBean`, `persistence.xml`) | Boot auto-configuration + repositories; delete `persistence.xml` |
| Stored-procedure calls, bulk batch loads, dynamic reporting SQL | May stay on `JdbcTemplate` (Boot auto-configures one) — say why in the Modify Result |

## Mapping the entity

Annotate the **existing** model class — don't create a parallel class — so the REST API's JSON shape is unchanged.

```java
@Entity
@Table(name = "customer_order")
public class CustomerOrder implements Serializable {

    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "customer_order_seq")
    @SequenceGenerator(name = "customer_order_seq", sequenceName = "customer_order_seq", allocationSize = 1)
    private Long id;

    @Column(name = "total_amount")
    private Double totalAmount;      // keep wrapper types: they preserve SQL NULL

    @Column(name = "placed_at")
    private Date placedAt;           // java.util.Date maps as TIMESTAMP; switching to java.time changes the JSON — only if the plan says so

    // existing no-arg constructor, getters and setters stay as they are
}
```

- JPA entities must be non-final classes with a no-arg constructor — never records.
- Give every column an explicit `@Column(name = ...)` and the table an explicit `@Table(name = ...)`; legacy schemas rarely match the default naming strategy exactly.
- Sequence-generated ids: `allocationSize` must equal the sequence's `INCREMENT BY` (almost always 1 in a legacy schema), or ids will collide or skip.
- Methods that are computed and not stored (e.g. `getTemperatureFahrenheit()`) need `@Transient` if they have a matching field, or nothing if they are getter-only.

## Repository

```java
public interface CustomerOrderRepository extends JpaRepository<CustomerOrder, Long> {

    // Derived query: case-insensitive match, newest first, row limit
    List<CustomerOrder> findByCustomerNameIgnoreCaseOrderByPlacedAtDescIdDesc(String customerName, Limit limit);

    // Vendor-specific SQL stays native, copied verbatim from the old DAO
    @Query(value = """
            SELECT id, customer_name, total_amount, placed_at FROM (
              SELECT o.*, ROW_NUMBER() OVER (PARTITION BY UPPER(o.customer_name) ORDER BY o.placed_at DESC) AS rn
              FROM customer_order o
            ) WHERE rn = 1 ORDER BY customer_name
            """, nativeQuery = true)
    List<CustomerOrder> findLatestPerCustomer();

    // Delete that reports the affected-row count, like JdbcTemplate.update(...) did
    @Modifying
    @Query("delete from CustomerOrder o where o.id = :id")
    int deleteByIdReturningCount(@Param("id") Long id);
}
```

- Use derived queries for simple finders, and `org.springframework.data.domain.Limit` (or `Pageable`) instead of `FETCH FIRST ? ROWS ONLY` / `ROWNUM`.
- Keep complex or vendor-specific SQL (analytic functions, hints, `CONNECT BY`, `MERGE`) as native `@Query` **verbatim** — do not translate it to JPQL.
- `@Modifying` queries must run inside a transaction; the existing service-level `@Transactional` covers them.

## Keep the DAO contract

Keep the DAO interface the service layer and tests depend on, and replace only its implementation:

```java
@Repository
public class JpaCustomerOrderDao implements CustomerOrderDao {

    private final CustomerOrderRepository repository;

    public JpaCustomerOrderDao(CustomerOrderRepository repository) {
        this.repository = repository;
    }

    @Override
    public CustomerOrder findById(long id) {
        return repository.findById(id).orElse(null);   // keep the old null-if-missing contract
    }

    @Override
    public long insert(CustomerOrder order) {
        return repository.save(order).getId();
    }

    @Override
    public int deleteById(long id) {
        return repository.deleteByIdReturningCount(id);
    }
}
```

- Preserve each DAO method's observable behaviour exactly: null vs. empty results, the returned counts and ids, and side effects on the argument. `save()` on a new entity (null id) persists that same instance, so the generated id lands on the caller's object just as the old JDBC insert did. Keep any defaulting the old DAO did (e.g. setting a timestamp when null).
- Services that were wired through XML setters get constructor injection and `@Service`.
- Delete the old JDBC implementation and its `RowMapper` once nothing references them. Test doubles that implement the DAO interface (e.g. an in-memory DAO) keep working unchanged.

## Configuration

```yaml
spring:
  datasource:
    url: ${DB_URL:jdbc:oracle:thin:@//localhost:1521/ORCLPDB1}
    username: ${DB_USERNAME:app_user}
    password: ${DB_PASSWORD}
    hikari:
      minimum-idle: 2
      maximum-pool-size: 10
      connection-timeout: 10000
  jpa:
    hibernate:
      ddl-auto: none      # never let Hibernate create or alter an existing schema
    open-in-view: false
```

- Carry the old pool settings over to `spring.datasource.hikari.*` (DBCP `initialSize`/`maxActive`/`maxWait` → `minimum-idle`/`maximum-pool-size`/`connection-timeout`). Drop settings Hikari has no equivalent for, and say so.
- Old `validationQuery` settings (`SELECT 1 FROM DUAL`) are unnecessary — Hikari validates with JDBC4 `isValid()`.
- Never write a real password default into `application.yml`; use an environment-variable placeholder and list the variable under Deployment impact.
- Remove explicit `DataSourceTransactionManager` / `JpaTransactionManager` beans and `<tx:annotation-driven/>` — `@Transactional` keeps working through Boot's auto-configured JPA transaction manager.
- Don't set `hibernate.dialect`; Hibernate detects it.
