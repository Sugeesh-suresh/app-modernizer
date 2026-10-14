# Data access → Spring Boot
<!-- applies-to: jdbc, jpa, hibernate, datasource, repository -->

Target: `spring-boot-starter-jdbc` / `spring-boot-starter-data-jpa` (Hibernate ORM 7, Jakarta Persistence 3.2, HikariCP). No hand-built `DataSource`, `EntityManagerFactory`, `SessionFactory`, `JdbcTemplate` or transaction manager remains (conformance B009). Entities, repositories and vendor SQL are handled in `java-8-to-25` › `spring-data-jpa-migration.md`; this file is the configuration and transaction side.

## DataSource → `spring.datasource.*`

```xml
<bean id="dataSource" class="org.apache.commons.dbcp2.BasicDataSource" destroy-method="close">
  <property name="driverClassName" value="${jdbc.driver}"/><property name="url" value="${jdbc.url}"/>
  <property name="username" value="${jdbc.user}"/><property name="password" value="${jdbc.pass}"/>
  <property name="maxTotal" value="30"/><property name="maxWaitMillis" value="10000"/><property name="validationQuery" value="select 1 from dual"/>
</bean>
```
```yaml
spring:
  datasource:
    url: ${DB_URL}
    username: ${DB_USERNAME}
    password: ${DB_PASSWORD}          # no real default
    hikari:
      maximum-pool-size: 30           # maxTotal / maxActive
      connection-timeout: 10000       # maxWaitMillis / maxWait (ms)
      minimum-idle: 5                 # minIdle
      # validationQuery is unnecessary: Hikari uses JDBC isValid(); set connection-test-query only for a driver that needs it
```
- `driver-class-name` is detected from the URL; set it only for a driver Boot cannot infer.
- **JNDI:** `<jee:jndi-lookup>`, `spring.datasource.jndi-name`, a `jndi` profile, `context.xml` `<Resource>` → the properties above, bound to environment variables; delete the JNDI profile and tell ops which variables to supply. An executable JAR has no JNDI tree.
- Several `DataSource`s are a genuine exception the scanner cannot tell apart from a leftover: the plan must name it as an Open Question (primary + secondary, each `DataSourceBuilder` bound with `@ConfigurationProperties("app.datasource.x")`, entity-manager and transaction manager per source); everything else uses the single auto-configured pool.
- Pool libraries (`commons-dbcp*`, `c3p0`, `tomcat-jdbc`) leave the pom.

## JPA and Hibernate → `spring.jpa.*`

```yaml
spring:
  jpa:
    hibernate:
      ddl-auto: none                  # never create/alter an existing schema
      naming:
        physical-strategy: org.hibernate.boot.model.naming.PhysicalNamingStrategyStandardImpl   # legacy names are explicit; Boot's default would snake_case them
    open-in-view: false               # true only if views/serialisation relied on lazy loading — decide, don't inherit the default
    show-sql: false
    properties:
      hibernate.jdbc.batch_size: 50   # every legacy hibernate.* property moves here; drop dialect (auto-detected) and removed ones
```
- Delete `LocalContainerEntityManagerFactoryBean`/`LocalSessionFactoryBean`, `persistence.xml`, `hibernate.cfg.xml`, `*.hbm.xml` (mappings become annotations). Entities outside the application's package → `@EntityScan("…")`; repositories outside it → `@EnableJpaRepositories("…")`. Neither is needed otherwise.
- `HibernateTemplate`, `HibernateDaoSupport`, `SessionFactory.getCurrentSession()`: no equivalent in Spring 7 — inject `EntityManager` (`@PersistenceContext`) or a repository.

## JdbcTemplate

`JdbcTemplate` and `NamedParameterJdbcTemplate` are auto-configured with `spring-boot-starter-jdbc`: delete the `@Bean`/XML definition and inject it. Query timeouts and fetch size → `spring.jdbc.template.query-timeout`, `.fetch-size`, `.max-rows`. Schema or data scripts (`<jdbc:initialize-database>`) → `spring.sql.init.mode`, `.schema-locations`, `.data-locations`; Flyway/Liquibase → their Boot starter and `spring.flyway.*` / `spring.liquibase.change-log`.

## Transactions

```xml
<tx:annotation-driven transaction-manager="txManager"/>
<bean id="txManager" class="org.springframework.orm.jpa.JpaTransactionManager"><property name="entityManagerFactory" ref="emf"/></bean>
```
→ both deleted; Boot creates `JpaTransactionManager` (or `DataSourceTransactionManager`) and enables annotation-driven transactions. `@EnableTransactionManagement` is unnecessary.
- `<tx:advice>` + `<aop:config>` with a pointcut (`execution(* com.acme.service.*.*(..))`, `get*` read-only, `*` required) → `@Transactional` / `@Transactional(readOnly = true)` on the **same** service methods, keeping propagation, isolation, `rollbackFor` and timeout. List the matched methods before deleting the XML.
- `@Transactional` must be on public methods called through the proxy; do not move it to a different layer.
- `spring.transaction.default-timeout` and `.rollback-on-commit-failure` replace transaction-manager properties. XA/JTA across several resources is a plan decision, not a mechanical conversion.
- Two managers (two data sources) stay explicit and are referenced by `@Transactional("name")`.

## Check list

One pool; `application.yml` carries every former `jdbc.*`/`hibernate.*` key; no secrets as defaults; every XML transaction rule has an equal `@Transactional`; JNDI variables are listed for ops; the schema is untouched (`ddl-auto: none`).
