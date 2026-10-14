# Spring Framework → Spring Boot component map

The master table. For every Spring component the repository uses, find its row, and convert to the Boot target — a starter, an auto-configuration (nothing to write), or a property. The target is Spring Boot 4.x (the newest), Spring Framework 7, Spring Security 7, Jakarta EE 11. Starter names below are the ones the `java-8-to-25` references use; where the chosen 4.x release names a starter differently (for example `spring-boot-starter-webmvc` for the web starter, see `java-8-to-25` › `boot4-dependency-cleanup.md`), the conformance report's B006 finding names the one to use — take it from there.

Legend: **auto** = Boot configures it, delete the manual definition; **prop** = a property replaces the code; **code** = a small Java class remains.

## Web

| Spring today | Spring Boot |
|---|---|
| `spring-webmvc`, `spring-web`, `<mvc:annotation-driven/>`, `@EnableWebMvc`, `DispatcherServlet` in `web.xml` | `spring-boot-starter-web` — **auto**. Customisations in a `WebMvcConfigurer` (**code**) |
| `@RestController`/`@Controller` classes | Unchanged; found by component scan from the `@SpringBootApplication` package |
| `InternalResourceViewResolver`, JSP, Tiles | `spring-boot-starter-thymeleaf` — **auto**; JSP → Thymeleaf (`web-layer-to-boot.md`) |
| FreeMarker/Velocity view resolvers | `spring-boot-starter-freemarker` — **auto** (Velocity has no Boot support: convert to Thymeleaf) |
| `ResourceBundleMessageSource`/`ReloadableResourceBundleMessageSource` (`messageSource` bean) | **prop** `spring.messages.basename`, `.encoding`, `.fallback-to-system-locale`, `.cache-duration` |
| `<mvc:resources>`, default-servlet-handler | **auto**: `classpath:/static/`; **prop** `spring.web.resources.static-locations`, `spring.mvc.static-path-pattern` |
| `CommonsMultipartResolver` (removed in Spring 6) | **auto** `StandardServletMultipartResolver`; **prop** `spring.servlet.multipart.max-file-size`, `.max-request-size` |
| `<mvc:cors>`, `CorsFilter` | **code** `WebMvcConfigurer.addCorsMappings` (or `CorsConfigurationSource` bean when Spring Security is present) |
| `SimpleMappingExceptionResolver`, `@ExceptionHandler` | **code** `@ControllerAdvice`/`@RestControllerAdvice`; `ProblemDetail` (`spring.mvc.problemdetails.enabled=true`) for RFC 9457 bodies — only if the old error body shape may change |
| `<error-page>` | **auto** `BasicErrorController`, `templates/error/<status>.html`; **prop** `server.error.*` |
| `<mvc:interceptors>`, `HandlerInterceptor` | **code** `WebMvcConfigurer.addInterceptors` |
| `Filter`, `OncePerRequestFilter`, `CharacterEncodingFilter`, `HiddenHttpMethodFilter` | `Filter` beans / `FilterRegistrationBean` (**code**); encoding **prop** `server.servlet.encoding.*`; hidden method **prop** `spring.mvc.hiddenmethod.filter.enabled` |
| `Converter`/`Formatter`/`HttpMessageConverter` definitions | **auto**: `Converter`/`Formatter` beans are registered; Jackson via `spring.jackson.*` / `JsonMapperBuilderCustomizer` |
| `LocaleResolver`, `LocaleChangeInterceptor` | **prop** `spring.web.locale`, `spring.web.locale-resolver`; interceptor stays in `addInterceptors` |
| `<mvc:view-controller>` | **code** `WebMvcConfigurer.addViewControllers` |
| Bean Validation / `LocalValidatorFactoryBean` | `spring-boot-starter-validation` — **auto** |
| Custom health servlet / `/ping` | `spring-boot-starter-actuator`: `/actuator/health`; **code** `HealthIndicator`; **prop** `management.endpoints.web.exposure.include`, `management.endpoint.health.probes.enabled` |
| Logging (`log4j.properties`, bindings) | `spring-boot-starter-logging` (default); **prop** `logging.level.*`, `logging.file.name`, or `logback-spring.xml` |

## Data

| Spring today | Spring Boot |
|---|---|
| `DataSource` bean (DBCP, C3P0, Tomcat JDBC, JNDI) | `spring-boot-starter-jdbc` — **prop** `spring.datasource.*`, `spring.datasource.hikari.*` |
| `JdbcTemplate`, `NamedParameterJdbcTemplate` bean | **auto** (inject it) |
| `LocalContainerEntityManagerFactoryBean`, `LocalSessionFactoryBean`, `persistence.xml`, `HibernateTemplate` | `spring-boot-starter-data-jpa` — **auto**; **prop** `spring.jpa.*` |
| `DataSourceTransactionManager`, `JpaTransactionManager`, `<tx:annotation-driven/>`, `<tx:advice>` | **auto**; `@Transactional` stays where the pointcut matched |
| `<jdbc:initialize-database>`, `<jdbc:embedded-database>` | **prop** `spring.sql.init.*`; an embedded database on the classpath |
| DAO classes (JDBC/Hibernate) | Spring Data repositories behind the existing DAO interface (`java-8-to-25` › `spring-data-jpa-migration.md`) |
| Spring Data (`@EnableJpaRepositories`, `<jpa:repositories>`) | `spring-boot-starter-data-jpa` — **auto**; annotation only when repositories live outside the application package |
| Redis / MongoDB templates | `spring-boot-starter-data-redis` / `-data-mongodb` — **auto**; `spring.data.redis.*`, `spring.data.mongodb.*` |
| Flyway / Liquibase | the matching Boot starter; `spring.flyway.*` / `spring.liquibase.*` |
| `@EnableCaching`, `CacheManager`, `<cache:annotation-driven>` | `spring-boot-starter-cache` — **auto**; **prop** `spring.cache.type`, `spring.cache.jcache.config` (Ehcache 3 via JCache) |

## Integration, jobs, messaging

| Spring today | Spring Boot |
|---|---|
| `<task:scheduler>`, `<task:annotation-driven>`, `<task:scheduled-tasks>` | `@EnableScheduling`/`@EnableAsync` stay; executors **auto**; **prop** `spring.task.scheduling.*`, `spring.task.execution.*`; XML `<task:scheduled-tasks>` → `@Scheduled` with the same cron/delay |
| `JavaMailSenderImpl` | `spring-boot-starter-mail` — **auto**; **prop** `spring.mail.*` |
| JMS (`JmsTemplate`, `DefaultMessageListenerContainer`, `<jms:listener-container>`) | `spring-boot-starter-artemis` / `-activemq`; `@JmsListener`; **prop** `spring.jms.*` |
| AMQP / RabbitMQ | `spring-boot-starter-amqp`; **prop** `spring.rabbitmq.*`, `@RabbitListener` |
| Kafka | the Kafka starter; **prop** `spring.kafka.*` |
| Spring Batch | `spring-boot-starter-batch`; **prop** `spring.batch.*` |
| Spring Integration | `spring-boot-starter-integration` |
| `<aop:aspectj-autoproxy/>`, `<aop:config>` | the AOP starter — **auto**; aspects become `@Aspect @Component` |
| Remoting: HttpInvoker, RMI, Hessian, `JmsInvokerProxyFactoryBean` (all removed from Spring 6) | **remove**; replace with a REST controller and a `@HttpExchange` client or `RestClient`; flag outside clients |
| `RestTemplate` | `RestClient` (built from the auto-configured `RestClient.Builder`); where a `RestTemplate` must stay, build it from `RestTemplateBuilder`, never `new RestTemplate()` with hand-set factories |
| JMX exporter (`<context:mbean-export>`) | **prop** `spring.jmx.enabled` |

## Security, config, tests

| Spring today | Spring Boot |
|---|---|
| Spring Security XML `<http>`, `WebSecurityConfigurerAdapter`, `DelegatingFilterProxy` | `spring-boot-starter-security`; **code** a `SecurityFilterChain` bean (`security-to-boot.md`) |
| `<context:component-scan>`, `<context:annotation-config/>` | **auto** — the `@SpringBootApplication` scan |
| `<context:property-placeholder>`, `PropertyPlaceholderConfigurer`, `@PropertySource` | `application.yml`; `@ConfigurationProperties`; `spring.config.import` for extra files |
| `<beans profile="x">`, `@Profile` | `@Profile` stays; `application-x.yml`; **prop** `spring.profiles.active` |
| `<util:properties>`, `<util:list>`, `<util:map>` | **code** a `@ConfigurationProperties` class |
| `SpringJUnit4ClassRunner`, `@ContextConfiguration`, `@MockBean` | `spring-boot-starter-test`; `@SpringBootTest`, slices, `@MockitoBean` (`testing-to-boot.md`) |

## Hand-written Java config that Boot makes unnecessary

`@EnableWebMvc`, `@EnableTransactionManagement`, `@EnableJpaRepositories` (in the application package), `@EnableAspectJAutoProxy`, `@ComponentScan` duplicating the application's, `@Import`/`@ImportResource` of XML, `PropertySourcesPlaceholderConfigurer`, `ObjectMapper`/`MessageSource`/`DataSource`/`EntityManagerFactory`/`JdbcTemplate`/transaction-manager `@Bean` methods. Delete each, carry its settings into properties, and keep what is a genuine customisation as a `Customizer`.
