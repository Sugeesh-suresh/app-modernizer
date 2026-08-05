# Standard Java/Spring Boot Project Layout

```
myapp/
├── pom.xml
├── src/main/java/com/example/app/
│   ├── Application.java
│   ├── controller/
│   ├── service/
│   ├── repository/
│   ├── domain/
│   ├── dto/
│   ├── mapper/                # MapStruct mappers (replaces AutoMapper profiles)
│   ├── exception/              # Custom exceptions + @ControllerAdvice handler
│   └── config/                 # @Configuration classes (security, CORS, beans)
├── src/main/resources/
│   ├── application.yml
│   ├── application-dev.yml
│   ├── application-prod.yml
│   └── db/migration/           # Flyway SQL migrations (V1__init.sql, ...)
├── src/test/java/com/example/app/
│   ├── controller/
│   ├── service/
│   └── repository/
└── Dockerfile
```

## `pom.xml` starter dependency set

```xml
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
        <artifactId>spring-boot-starter-validation</artifactId>
    </dependency>
    <dependency>
        <groupId>org.flywaydb</groupId>
        <artifactId>flyway-core</artifactId>
    </dependency>
    <dependency>
        <groupId>org.mapstruct</groupId>
        <artifactId>mapstruct</artifactId>
        <version>1.5.5.Final</version>
    </dependency>
    <dependency>
        <groupId>org.projectlombok</groupId>
        <artifactId>lombok</artifactId>
        <optional>true</optional>
    </dependency>
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-test</artifactId>
        <scope>test</scope>
    </dependency>
</dependencies>
```

## NuGet → Maven dependency swap table

| From (NuGet) | To (Maven artifact) |
|---|---|
| `Microsoft.AspNetCore.App` | `spring-boot-starter-web` |
| `Microsoft.EntityFrameworkCore.SqlServer` | `spring-boot-starter-data-jpa` + `mssql-jdbc` (or `postgresql` driver) |
| `AutoMapper` | `org.mapstruct:mapstruct` |
| `FluentValidation.AspNetCore` | `spring-boot-starter-validation` |
| `Serilog.AspNetCore` | (bundled) SLF4J + Logback |
| `Swashbuckle.AspNetCore` | `springdoc-openapi-starter-webmvc-ui` |
| `Microsoft.AspNetCore.Authentication.JwtBearer` | `spring-boot-starter-oauth2-resource-server` |

## `application.yml` skeleton (from `appsettings.json`)

```yaml
spring:
  application:
    name: myapp
  datasource:
    url: jdbc:sqlserver://localhost:1433;databaseName=myapp
    username: ${DB_USER}
    password: ${DB_PASSWORD}
  jpa:
    hibernate:
      ddl-auto: validate
  flyway:
    enabled: true

server:
  port: 8080

logging:
  level:
    com.example.app: INFO
```
