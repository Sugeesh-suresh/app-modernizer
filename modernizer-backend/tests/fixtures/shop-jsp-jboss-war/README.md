# shop-jsp-jboss-war (migration test fixture)

A small, realistic legacy application used to test the migration pipeline
(Java 8 -> 25, Spring 4 -> Spring Boot 4). It is a single-module Maven project, `<packaging>war</packaging>`,
Java 8 (`maven.compiler.source/target` 1.8), deployed to JBoss EAP / WildFly as `shop.war`.

## Legacy shape a migration must convert

- Spring 4.3.30 MVC configured entirely in XML: `WEB-INF/web.xml` (ContextLoaderListener, `shop`
  DispatcherServlet, CharacterEncodingFilter, custom `RequestLoggingFilter`, `AppStartupListener`, error pages),
  `applicationContext.xml` (component-scan, `jee:jndi-lookup` DataSource `java:jboss/datasources/ShopDS`,
  `JdbcTemplate`, `DataSourceTransactionManager` + `tx:annotation-driven`, `PropertyPlaceholderConfigurer`),
  `shop-servlet.xml` (`mvc:annotation-driven`, JSP `InternalResourceViewResolver`, `mvc:resources`,
  `ResourceBundleMessageSource`, `SessionLocaleResolver` + `LocaleChangeInterceptor`).
- `javax.*` namespaces (servlet, validation), JSP + JSTL + Spring form taglib views under `WEB-INF/views`.
- JBoss deployment descriptors: `jboss-web.xml`, `jboss-deployment-structure.xml`, `WEB-INF/shop-ds.xml`
  (placeholder password `${ds.password}`), `deploy/jboss-datasource.cli`, `docs/DEPLOY.md`.
- Jackson 2.9, Hibernate Validator 5.3, slf4j + log4j 1.x (`log4j.properties`).
- Tests: JUnit 4 + Mockito (service), MockMvc standalone (controller), and a `SpringJUnit4ClassRunner`
  integration test using the XML `test-context.xml` with an embedded H2 database.

## Build and test

    JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64 mvn -B -nsu test
    JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64 mvn -B -nsu -DskipTests package   # target/shop.war

All 16 tests pass on JDK 8 with Maven 3.9.
