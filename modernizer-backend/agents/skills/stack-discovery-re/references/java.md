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
