# Spring XML contexts and `web.xml` → Spring Boot

Companion to `java-8-to-25` › `webxml-to-javaconfig.md` (which has the servlet/filter/listener/error-page/session/security-constraint translations with code): this file maps the **XML bean contexts** and the remaining `web.xml` elements the base file does not cover, and defines how `@ImportResource` may be used. End state: no Spring XML bean file, no `web.xml`, no `@ImportResource`.

## Process, one context at a time

1. List every bean, `<import>`, placeholder and namespace element in the file (`read_file` the whole of it).
2. Convert each to its target below; keep bean names that anything looks up.
3. Delete the XML file **only after** each of its beans exists as an annotated class, a `@Configuration` `@Bean`, or a property — and remove the `@ImportResource`/`<import>` that loaded it.
4. A bean can only live in one place: never an XML and a Java definition of it.

## `@ImportResource` — a bridge, not a destination

```java
@SpringBootApplication
@ImportResource("classpath:legacy-context.xml")   // allowed only while the stage's guardrail says XML survives
public class Application { … }
```
Move the XML under `src/main/resources` so `classpath:` finds it (not `WEB-INF/`). Every `@ImportResource` is gone by the end of the stage that deletes the last XML file; the pipeline reports leftover XML as B005.

## Bean-definition elements

| XML | Spring Boot form |
|---|---|
| `<bean class="com.acme.OrderService"><property name="repo" ref="orderRepo"/></bean>` for your own class | `@Service` on the class, constructor injection: `OrderService(OrderRepo repo)` |
| the same, with an id that other code uses | `@Service("orderService")` |
| `<bean>` for a library type with real wiring | `@Bean` in a `@Configuration` class |
| `<bean … init-method destroy-method>` | `@PostConstruct`/`@PreDestroy` (`jakarta.annotation`), or `@Bean(initMethod=…)` |
| `scope="prototype"` / `lazy-init` / `depends-on` / `primary` | `@Scope("prototype")` / `@Lazy` / `@DependsOn` / `@Primary` |
| `<constructor-arg>`, `<property value="${x}">` | constructor injection; `@Value("${x}")` for one key, `@ConfigurationProperties` for a group |
| `<import resource="other.xml"/>` | convert `other.xml` first, or in the same task |
| `<beans profile="dev">` | `@Profile("dev")` on the class/`@Bean`; `application-dev.yml` |
| `<context:component-scan base-package=…/>`, `<context:annotation-config/>` | delete — `@SpringBootApplication` scans from its package (`scanBasePackages` only if code lives elsewhere) |
| `<context:property-placeholder location=…/>` | delete; keys → `application.yml` |
| `<util:properties id="p" location=…/>`, `<util:list>` | `@ConfigurationProperties` class |
| `<bean id="dataSource" …>`, `<tx:annotation-driven/>`, `<bean transactionManager>` | delete — `spring.datasource.*` (`data-access-to-boot.md`) |
| `<mvc:annotation-driven>` / `<mvc:resources>` / `<mvc:interceptors>` / `<mvc:view-controller>` | delete or `WebMvcConfigurer` (`web-layer-to-boot.md`) |
| `<aop:aspectj-autoproxy/>`, `<aop:config>` | AOP starter; `@Aspect @Component`; `<aop:advisor>` for `<tx:advice>` → `@Transactional` on the matched methods |
| `<task:annotation-driven>`, `<task:scheduled-tasks>` | `@EnableScheduling`/`@EnableAsync`; `@Scheduled(cron=…)`; `spring.task.*` |
| `<jee:jndi-lookup>` | `spring.datasource.*` env-bound (JNDI is gone with the container) |
| `<jdbc:embedded-database>` / `<jdbc:initialize-database>` | embedded DB on the classpath, `spring.sql.init.*` |
| `<jms:*>`, `<rabbit:*>`, `<int:*>`, `<batch:*>` | `messaging-integration-batch-to-boot.md` |
| `<security:*>` | `security-to-boot.md` |
| a custom namespace handler | no automatic target — an Open Question in the plan |

## `web.xml` elements beyond the base file

| `web.xml` | Spring Boot |
|---|---|
| `ContextLoaderListener` + `contextConfigLocation` | delete; one Boot context, XML converted per the above |
| `DispatcherServlet` + `<servlet-mapping>` `/` | delete; a non-root mapping → `spring.mvc.servlet.path` |
| `<load-on-startup>` | `spring.mvc.servlet.load-on-startup` |
| `DelegatingFilterProxy` `springSecurityFilterChain` | delete; the `SecurityFilterChain` bean is registered by Boot |
| `CharacterEncodingFilter` | `server.servlet.encoding.charset: UTF-8`, `.force: true` |
| `HiddenHttpMethodFilter` | `spring.mvc.hiddenmethod.filter.enabled: true` |
| `OpenEntityManagerInViewFilter` / interceptor | `spring.jpa.open-in-view` — state it explicitly: `true` if the legacy app relied on lazy loading in views, otherwise `false` |
| `<resource-ref>` / `<resource-env-ref>` / `<env-entry>` | `spring.datasource.*` / properties; flag to ops |
| `<jsp-config>`, `<jsp-property-group>`, taglib mappings | gone with JSP → Thymeleaf |
| `<mime-mapping>` | usually unnecessary; an unusual type → `WebServerFactoryCustomizer` |
| `<display-name>`, `<distributable>` | drop; say so in the summary |
| `<servlet>`/`<filter>`/`<listener>`/`<error-page>`/`<session-config>`/`<welcome-file-list>`/`<security-constraint>` | the base `webxml-to-javaconfig.md` |

## Example: a context converted

```xml
<!-- applicationContext.xml (deleted after) -->
<context:component-scan base-package="com.acme"/>
<tx:annotation-driven/>
<bean id="dataSource" class="org.apache.commons.dbcp2.BasicDataSource">
  <property name="url" value="${db.url}"/><property name="maxTotal" value="20"/>
</bean>
<bean id="auditClock" class="com.acme.AuditClock"/>
```
```yaml
# application.yml
spring:
  datasource:
    url: ${DB_URL}
    hikari:
      maximum-pool-size: 20
```
```java
@Component("auditClock")          // keeps the id other code looks up
public class AuditClock { … }
```
The scan, `<tx:annotation-driven/>` and `dataSource` bean are deleted, not re-declared.
