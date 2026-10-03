# Java application — what to document

Where to look:
- Build: `pom.xml` (all modules, parent POMs, `<properties>`, `<dependencyManagement>`, plugins and their configuration), `build.gradle`/`settings.gradle`, Maven wrapper, `.mvn/`
- Source roots: `src/main/java`, `src/test/java`, generated-source configuration
- Configuration: `src/main/resources` (`*.properties`, `*.yml`, `*.xml`), Spring XML contexts, `META-INF/` (`persistence.xml`, `MANIFEST.MF`, `services/`), `WEB-INF/web.xml`, logging configuration
- Scripts: start scripts, `Dockerfile`, CI files that build or run the application

What to record:
- Modules and their packaging (jar/war/ear), the parent/child structure, and the declared compiler source/target/release
- Every direct dependency (groupId:artifactId:version, scope) and where its version is managed
- Frameworks in use and how they are wired (Spring XML/annotations, EJB, CDI, JAX-RS, servlets, schedulers)
- Entry points: `main` methods, servlets, controllers/resources and their routes, message listeners, scheduled jobs, startup listeners
- Layers: controllers → services → DAOs/repositories → data sources, with the classes in each
- Persistence: JDBC/JPA/Hibernate/MyBatis usage, entities and their tables, transaction boundaries
- Cross-cutting: security (authentication, authorisation, filters), logging, caching, error handling, i18n
- Concurrency: thread pools, executors, synchronisation, async processing
- External calls: HTTP clients, SOAP clients, files, mail, sockets, and where their endpoints are configured
- Tests: frameworks (JUnit, TestNG, Mockito, Arquillian, Spring Test), what each test class covers, and the surefire/failsafe configuration

## If the application uses Spring Boot

Also look at and record:
- The Spring Boot version (from the parent POM or `spring-boot.version`) and the starters in use
- Multi-module structure: what each Maven module is for, which modules depend on which, and which one is the runnable application (`@SpringBootApplication`, `spring-boot-maven-plugin` repackaging into an executable/uber JAR)
- Configuration per environment: `application.properties|yml` and every `application-<profile>` file, `@ConfigurationProperties` classes and their prefixes, `@Value` injections, `@Profile` beans — what differs between environments
- Encrypted configuration (Jasypt `ENC(...)` values): record the property and where the decryption password is supplied from (environment variable, system property), never the value
- Security: Spring Security configuration, authentication provider (e.g. LDAP), URL and method authorisation rules
- Caching (`@EnableCaching`, `@Cacheable`/`@CacheEvict`): cache names, keys, eviction/TTL configuration, what data is cached
- Scheduled and batch work (`@Scheduled` cron/fixed-rate, `@Async`, executors): what runs, when, and what it does
- Reactive pipelines (Project Reactor `Flux`/`Mono`, WebFlux): each pipeline's source, the filtering/mapping/standardisation steps and the conditions inside their lambdas, error handling and back-pressure
- File formats the application reads or writes (Apache POI Excel workbooks, CSV): sheet names, column order and meaning, validations applied per column — these are data contracts
- Logging configuration (`log4j2*.xml`, Logback): appenders, levels, what is logged
- Actuator endpoints and health checks, if present
