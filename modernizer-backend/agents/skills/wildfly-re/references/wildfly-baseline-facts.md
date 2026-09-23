# WildFly / JBoss EAP Deployment — Where to Look and Why It Matters

A discovery checklist, not evidence about the repository in front of you. Nothing
here asserts that a file or subsystem is present. Record what you actually read.

Describe what the configuration does and what the application depends on. Do not
record what something "should become" — this skill has no migration target.

## Why this stack is worth extracting separately

A WildFly application's behaviour is split between the application source and the
container configuration, and the container half is invisible to anyone reading
the code. Transactions, connection pooling, authentication, JNDI resolution and
class loading are all supplied by the server. An account of the application that
omits them describes something that cannot actually run.

## Server configuration

- `standalone.xml` — the usual single-server configuration. `standalone-full.xml` adds messaging and the full Jakarta EE profile; `standalone-ha.xml` adds clustering. Which file is in use is a deployment choice, so record which ones are present rather than assuming.
- `domain.xml` + `host.xml` — managed domain mode: server groups, profiles, and per-host overrides. A repository containing these is configuring a multi-server topology.
- Often **none of these are checked in**, because they belong to the environment. That absence is a finding to state, not a gap to fill with defaults.
- `<extension>` elements declare which subsystems can be configured at all.
- `${...}` expressions resolve from system properties, `-D` flags, property files or a vault. Record the expression; the effective value is unresolved unless the substituting source is in the repository.
- Schema namespaces (`urn:jboss:domain:14.0`, `urn:jboss:domain:datasources:6.0`) are the most reliable version markers in the file. Record them verbatim.

## Subsystems that change application behaviour

- **datasources** — pool name, JNDI name, driver, connection URL, pool sizing, validation, `<security>` credentials, transaction isolation. Also standalone `*-ds.xml` files, an older deployment style. Redact every password.
- **transactions** — default timeout, recovery configuration, whether JTA is in play. Container-managed transaction boundaries come from here plus the EJB/CDI annotations.
- **jpa** / `persistence.xml` — the provider, and the `jta-data-source`/`non-jta-data-source` JNDI name the persistence unit binds to. That name must reconcile with a datasource definition.
- **undertow / web** — virtual hosts, servlet container settings, session config, HTTPS listeners, keystores, request limits, access logging.
- **messaging-activemq** (or **messaging** on older EAP) — queues, topics, connection factories with their JNDI names, address settings, redelivery and expiry, bridges and remote connectors. Note that on WildFly this is where TIBCO or other external brokers are often reached through a resource adapter instead.
- **ejb3** — pools, thread pools, timer service and its data store, remote invocation, default security domain, `@Asynchronous` executor.
- **elytron** or legacy **security** — security domains, realms, login modules, role mapping, SSL contexts. Which of the two is in use tells you a great deal about the era of the configuration; record what is there.
- **logging** — handlers, categories, levels, and file locations.
- **infinispan** — caches backing the session store, JPA second-level cache or the application directly.
- **resource-adapters** — deployed RARs and their connection definitions with JNDI names; this is how external systems are commonly bound.
- **naming** — externally bound JNDI entries, including simple values the application reads as configuration.
- **batch-jberet**, **mail**, **io**, **remoting**, **request-controller** — record if configured.

## Application-contributed descriptors

- `jboss-deployment-structure.xml` — module dependencies, exclusions, resource roots, sub-deployment isolation. **The highest-value file in a WildFly repository.** It establishes which classes the container supplies and which the application brings, and nothing in the application source reveals it. An `<exclusions>` entry in particular means the application is deliberately overriding something the server would otherwise provide.
- `MANIFEST.MF` with a `Dependencies:` line — the same mechanism, expressed in the manifest instead. Easy to miss entirely.
- `jboss-web.xml` — context root (so the application's real URL is not derivable from the WAR name alone), virtual host, `security-domain` binding, JNDI resource refs.
- `jboss-app.xml` — EAR-level class loading isolation and security domain.
- `jboss-ejb3.xml` — EJB-level overrides: pools, security, timers.
- `jboss-ejb-client.xml` — outbound remote EJB connections and their target.
- `web.xml` — servlets, filters, listeners, `security-constraint`, `login-config`, error pages, session timeout, `resource-ref`/`ejb-ref`/`env-entry`. The `resource-ref` entries are JNDI lookups by another name.
- `application.xml` — EAR module list and order, and the library directory.
- `beans.xml`, `ra.xml`, `ejb-jar.xml`, `persistence.xml` — record what each contributes.

## JNDI

- Lookups appear as `@Resource(lookup=...)`, `@Resource(mappedName=...)`, `@EJB(lookup=...)`, `new InitialContext().lookup(...)`, `jndi-name` in `persistence.xml`, `<resource-ref>` in `web.xml`, `JndiObjectFactoryBean` or `jee:jndi-lookup` in Spring configuration, and `jboss-web.xml` refs.
- Names follow `java:jboss/...`, `java:global/...`, `java:app/...`, `java:module/...`, `java:comp/env/...`, or a bare legacy name.
- Reconcile both directions. A lookup with no definition in the repository is supplied by an environment you cannot see; a definition nothing looks up may be dead or may be reached from outside. Both are findings; neither is an error to resolve by guessing.

## Packaging and deployment

- `<packaging>war</packaging>` / `ear`, EAR module declarations, and `WEB-INF/lib` contents if committed.
- `wildfly-maven-plugin` / `jboss-as-maven-plugin` — their version is a strong server-version signal; record the configured goals and any `<server-config>`.
- `provided` scope dependencies — these are expected to come from the container. Which ones, and whether `jboss-deployment-structure.xml` agrees, is worth recording.
- `*.cli` scripts and `jboss-cli` batch files — configuration applied at deploy time. Everything they set is part of the running configuration and often nowhere else in the repository.
- `Dockerfile`s, entrypoint scripts and start scripts — `-D` flags, `-c` config selection, and property files they mount all feed the `${...}` expressions above.

## Tests

- Arquillian (`@RunWith(Arquillian.class)`, `@Deployment`, `arquillian.xml`) — these deploy into a real container and are the only tests that exercise container-supplied behaviour.
- Integration tests requiring a running server, and smoke or health-check scripts.
- Check the test source roots and the build configuration before concluding anything about coverage.

## What NOT to assume
- Do not assume server configuration is checked in, or describe default configuration as though you had read it.
- Do not assume the WildFly or EAP version; record the markers you found and cite them.
- Do not infer a database version from a JDBC URL, or a broker version from a connection factory.
- Do not assume `provided` dependencies match what the container actually supplies — `jboss-deployment-structure.xml` can override both directions.
- Do not assume a JNDI lookup resolves. Say when you found no definition for it.
- Never copy a credential into the output. Record the property and its path, with the value redacted.
