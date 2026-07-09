# Spring Boot Starters Reference

## Core Starters by TIBCO Resource Type

| TIBCO Shared Resource | Spring Boot Starter | Maven Artifact |
|---|---|---|
| HTTP Receive / HTTP Send | Web | `spring-boot-starter-web` |
| JDBC Connection | Data JPA | `spring-boot-starter-data-jpa` |
| JDBC (native SQL) | JDBC | `spring-boot-starter-jdbc` |
| ActiveMQ / JMS | ActiveMQ | `spring-boot-starter-activemq` |
| Artemis JMS | Artemis | `spring-boot-starter-artemis` |
| Kafka | Kafka | `spring-kafka` |
| SOAP Web Service (client) | WS | `spring-boot-starter-ws` (CXF or JAX-WS) |
| FTP / File System | Integration | `spring-integration-ftp` |
| Scheduler / Timer | Scheduling | `spring-boot-starter-scheduling` (included in `web`) |
| Security / OAuth2 | Security | `spring-boot-starter-security` |
| Caching | Cache | `spring-boot-starter-cache` |
| Health / Metrics | Actuator | `spring-boot-starter-actuator` |
| Email | Mail | `spring-boot-starter-mail` |

## pom.xml Template (Spring Boot 3.x)
```xml
<parent>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter-parent</artifactId>
  <version>3.3.5</version>
</parent>

<dependencies>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-data-jpa</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-activemq</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-actuator</artifactId>
  </dependency>

  <!-- Test -->
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-test</artifactId>
    <scope>test</scope>
  </dependency>
</dependencies>
```

## Database Driver Dependencies

| Database | Driver Artifact |
|---|---|
| PostgreSQL | `org.postgresql:postgresql` |
| MySQL | `com.mysql:mysql-connector-j` |
| Oracle | `com.oracle.database.jdbc:ojdbc11` |
| SQL Server | `com.microsoft.sqlserver:mssql-jdbc` |
| H2 (test) | `com.h2database:h2` |

## application.properties Templates

### HTTP Server
```properties
server.port=8080
server.servlet.context-path=/api
```

### JDBC / JPA
```properties
spring.datasource.url=jdbc:postgresql://localhost:5432/mydb
spring.datasource.username=${DB_USER}
spring.datasource.password=${DB_PASSWORD}
spring.datasource.driver-class-name=org.postgresql.Driver
spring.jpa.hibernate.ddl-auto=validate
spring.jpa.show-sql=false
spring.jpa.properties.hibernate.dialect=org.hibernate.dialect.PostgreSQLDialect
```

### ActiveMQ JMS
```properties
spring.activemq.broker-url=tcp://localhost:61616
spring.activemq.user=${JMS_USER}
spring.activemq.password=${JMS_PASSWORD}
spring.jms.listener.concurrency=3-10
```

### Actuator
```properties
management.endpoints.web.exposure.include=health,info,metrics
management.endpoint.health.show-details=when-authorized
```

## MapStruct Dependency (for XSLT → Java mapper)
```xml
<dependency>
  <groupId>org.mapstruct</groupId>
  <artifactId>mapstruct</artifactId>
  <version>1.5.5.Final</version>
</dependency>
<plugin>
  <groupId>org.apache.maven.plugins</groupId>
  <artifactId>maven-compiler-plugin</artifactId>
  <configuration>
    <annotationProcessorPaths>
      <path>
        <groupId>org.mapstruct</groupId>
        <artifactId>mapstruct-processor</artifactId>
        <version>1.5.5.Final</version>
      </path>
    </annotationProcessorPaths>
  </configuration>
</plugin>
```
