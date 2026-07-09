# Quarkus Extensions Reference

## Core Extension Groups

### Web / REST
| Need | Extension | Maven Artifact |
|---|---|---|
| REST (recommended) | RESTEasy Reactive | `quarkus-resteasy-reactive` |
| REST + Jackson | RESTEasy Reactive Jackson | `quarkus-resteasy-reactive-jackson` |
| OpenAPI / Swagger UI | SmallRye OpenAPI | `quarkus-smallrye-openapi` |
| WebSockets | WebSockets Next | `quarkus-websockets-next` |

### Data
| Need | Extension | Maven Artifact |
|---|---|---|
| ORM (recommended) | Hibernate ORM with Panache | `quarkus-hibernate-orm-panache` |
| Reactive ORM | Hibernate Reactive with Panache | `quarkus-hibernate-reactive-panache` |
| PostgreSQL | JDBC PostgreSQL | `quarkus-jdbc-postgresql` |
| MySQL | JDBC MySQL | `quarkus-jdbc-mysql` |
| H2 (tests) | JDBC H2 | `quarkus-jdbc-h2` |
| MongoDB | MongoDB with Panache | `quarkus-mongodb-panache` |
| Redis | Redis | `quarkus-redis` |
| Flyway | Flyway | `quarkus-flyway` |
| Liquibase | Liquibase | `quarkus-liquibase` |

### Security
| Need | Extension | Maven Artifact |
|---|---|---|
| OIDC / OAuth2 | OIDC | `quarkus-oidc` |
| JWT Bearer | SmallRye JWT | `quarkus-smallrye-jwt` |
| Basic Auth | Elytron Security Properties | `quarkus-elytron-security-properties-file` |
| Password hashing | Security | `quarkus-security` |

### Messaging
| Need | Extension | Maven Artifact |
|---|---|---|
| Kafka | SmallRye Reactive Messaging Kafka | `quarkus-messaging-kafka` |
| AMQP | SmallRye Reactive Messaging AMQP | `quarkus-messaging-amqp` |
| JMS | Artemis JMS | `quarkus-artemis-jms` |

### Observability
| Need | Extension | Maven Artifact |
|---|---|---|
| Health checks | SmallRye Health | `quarkus-smallrye-health` |
| Metrics | Micrometer | `quarkus-micrometer` |
| Tracing | OpenTelemetry | `quarkus-opentelemetry` |

### Developer Experience
| Need | Extension | Maven Artifact |
|---|---|---|
| Config | SmallRye Config | `quarkus-smallrye-config` (included by default) |
| Caching | Cache | `quarkus-cache` |
| Scheduling | Scheduler | `quarkus-scheduler` |
| Email | Mailer | `quarkus-mailer` |
| REST Client | REST Client Reactive | `quarkus-rest-client-reactive` |

## Quarkus BOM (pom.xml template)
```xml
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>io.quarkus.platform</groupId>
      <artifactId>quarkus-bom</artifactId>
      <version>3.15.1</version>
      <type>pom</type>
      <scope>import</scope>
    </dependency>
  </dependencies>
</dependencyManagement>
```

## quarkus-maven-plugin (build)
```xml
<plugin>
  <groupId>io.quarkus.platform</groupId>
  <artifactId>quarkus-maven-plugin</artifactId>
  <version>3.15.1</version>
  <executions>
    <execution>
      <goals><goal>build</goal><goal>generate-code</goal></goals>
    </execution>
  </executions>
</plugin>
```

## Native Build Command
```bash
./mvnw package -Pnative -Dquarkus.native.container-build=true
```
