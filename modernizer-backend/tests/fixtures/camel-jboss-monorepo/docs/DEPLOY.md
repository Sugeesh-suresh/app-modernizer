# Deploying orders-api.war to JBoss EAP 7

Target: JBoss EAP 7.x (WildFly 10/11 based), Java 8, standalone profile.

## 1. Build

```
mvn -B clean package          # runs the tests, produces orders-api/target/orders-api.war
```

The WAR bundles Spring 4.3, Jackson 2.9, Apache Camel 2.25, log4j 1.2 and slf4j.
`javax.servlet-api` and `validation-api` are `provided`; the container supplies them.

## 2. Container configuration used by the WAR

| File | Purpose |
|------|---------|
| `WEB-INF/jboss-web.xml` | context root `/orders-api`, security domain `orders-security-domain` |
| `WEB-INF/jboss-deployment-structure.xml` | excludes the `jaxrs` subsystem and the container's log4j, slf4j, commons-logging, Jackson and RESTEasy-Jackson modules so the bundled copies are used; adds a dependency on `org.hibernate.validator` |
| `META-INF/MANIFEST.MF` | `Dependencies: javax.api` (added by the maven-war-plugin) |
| `WEB-INF/web.xml` | `ContextLoaderListener`, `CamelContextListener`, `CorrelationIdFilter`, `DispatcherServlet` on `/api/*` |

## 3. Deploy

CLI script (creates the security domain and outbox property, then deploys):

```
$JBOSS_HOME/bin/jboss-cli.sh --connect --file=deploy/jboss-cli/orders-api.cli
```

Or copy `orders-api/target/orders-api.war` into `$JBOSS_HOME/standalone/deployments/`; the
deployment scanner creates `orders-api.war.deployed`.

## 4. Verify

```
curl http://localhost:8080/orders-api/api/health
curl -X POST -H 'Content-Type: application/json' \
     -d '{"customerId":"C-100","priority":true,"lines":[{"sku":"SKU-1","quantity":2,"unitPrice":9.99}]}' \
     http://localhost:8080/orders-api/api/orders
```

Shipments are written as JSON to `target/outbox` relative to the server working directory
(`outbox.dir` in `camel.properties`).

## 5. Undeploy

```
$JBOSS_HOME/bin/jboss-cli.sh --connect "undeploy orders-api.war"
```

## Troubleshooting

* `NoClassDefFoundError: javax/validation/...` - the `org.hibernate.validator` module dependency is missing.
* Duplicate Jackson or log4j classes in the log - check the exclusions in `jboss-deployment-structure.xml`.
* Camel routes not started - look for the `Starting Camel context orderCamelContext` message from `CamelContextListener`.
