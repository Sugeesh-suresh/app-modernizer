# Spring Boot 3.x & the javax → jakarta Transition

Target: newest Spring Boot 3.x (3.5.x), Spring Framework 6, Jakarta EE 10, still a WAR on an external container (now Tomcat 10.1+). This stage runs on Java 17 and must not change the compiler release. The Java 25 stage runs right after it, so choose a 3.5.x release that also supports Java 25.

## Artifact replacements (rename imports AND swap artifacts — never just one)

| Java EE / old artifact | Jakarta / new artifact |
|---|---|
| `javax.servlet:javax.servlet-api` | `jakarta.servlet:jakarta.servlet-api` 6.0 (provided) — or rely on `spring-boot-starter-tomcat` (provided) |
| `javax.servlet:jstl` / `taglibs:standard` | `jakarta.servlet.jsp.jstl:jakarta.servlet.jsp.jstl-api` 3.0 + `org.glassfish.web:jakarta.servlet.jsp.jstl` 3.0 |
| `javax.validation:validation-api`, `org.hibernate:hibernate-validator` 6.x | `spring-boot-starter-validation` (Hibernate Validator 8, `jakarta.validation`) |
| `org.hibernate:hibernate-core` 5.x, `javax.persistence-api` | `org.hibernate.orm:hibernate-core` 6.x — **groupId changed** (managed by `spring-boot-starter-data-jpa`) |
| `javax.xml.bind:jaxb-api` + `com.sun.xml.bind:jaxb-impl` | `jakarta.xml.bind:jakarta.xml.bind-api` 4.0 + `org.glassfish.jaxb:jaxb-runtime` 4.0 |
| `javax.annotation:javax.annotation-api` | `jakarta.annotation:jakarta.annotation-api` 2.1 |
| `javax.mail` / `com.sun.mail:javax.mail` | `jakarta.mail:jakarta.mail-api` 2.1 + `org.eclipse.angus:angus-mail` (or `spring-boot-starter-mail`) |
| `javax.transaction:javax.transaction-api` | `jakarta.transaction:jakarta.transaction-api` 2.0 |
| `net.sf.ehcache:ehcache` 2.x | `org.ehcache:ehcache` 3.x with the `jakarta` classifier — **an API rewrite**, not a swap: `getKeys()`, `getQuiet()` and `Element` are all gone (the Java 17 stage should already have done this; if `net.sf.ehcache` imports survive, finish the rewrite here). Spring 6 also removed `org.springframework.cache.ehcache.EhCacheCacheManager` → `JCacheCacheManager` (`javax.cache` stays `javax`), and Hibernate 6 removed `hibernate-ehcache` → `org.hibernate.orm:hibernate-jcache` |
| `com.fasterxml.jackson.module:jackson-module-jaxb-annotations` | `jackson-module-jakarta-xmlbind-annotations` (`JakartaXmlBindAnnotationModule`) |
| `org.apache.httpcomponents:httpclient` 4.x (under `RestTemplate`) | `org.apache.httpcomponents.client5:httpclient5` — Spring 6's `HttpComponentsClientHttpRequestFactory` only supports HttpClient 5 |

## Code changes Spring Framework 6 / Spring Boot 3 force

- **Spring Security 6:** `WebSecurityConfigurerAdapter` is gone → declare a `SecurityFilterChain` `@Bean`; `authorizeRequests()` → `authorizeHttpRequests()`; `antMatchers()`/`mvcMatchers()` → `requestMatchers()`; `@EnableGlobalMethodSecurity` → `@EnableMethodSecurity`.
- **Spring MVC 6:** trailing-slash matching is off by default (`/users/` no longer matches `/users`). Either add the explicit slash mapping, or note the behavioural change for the reviewer — do not silently turn it back on globally.
- `ResponseEntityExceptionHandler` overrides take `HttpStatusCode` instead of `HttpStatus`.
- `@ConstructorBinding` on a `@ConfigurationProperties` type is no longer needed (and on the type level, removed) — delete it or move it to the constructor.
- Auto-configuration registered in `META-INF/spring.factories` → `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`.
- Spring Cloud Sleuth → Micrometer Tracing (only if Sleuth is present).
- Hibernate 6: `@Type(type = "...")` string form is gone; `@TypeDef` removed; some HQL implicit joins now need explicit `join`.

## Property renames (most common)

| Spring Boot 2.7 | Spring Boot 3.x |
|---|---|
| `spring.redis.*` | `spring.data.redis.*` |
| `spring.jpa.hibernate.use-new-id-generator-mappings` | removed |
| `server.max-http-header-size` | `server.max-http-request-header-size` |
| `management.metrics.export.<system>.*` | `management.<system>.metrics.export.*` |
| `spring.mvc.pathmatch.matching-strategy=ant_path_matcher` | still supported, but `PathPatternParser` is the default — remove it unless ant-style patterns are really needed |

## Non-Java files that also carry `javax`

- `META-INF/persistence.xml`: namespace `https://jakarta.ee/xml/ns/persistence`, `version="3.0"`, and `javax.persistence.*` property keys → `jakarta.persistence.*`.
- `web.xml` (if still present): `https://jakarta.ee/xml/ns/jakartaee`, `web-app_6_0.xsd`, `version="6.0"`.
- `META-INF/services/javax.servlet.ServletContainerInitializer` → rename the **file** to `jakarta.servlet.ServletContainerInitializer`.
- JSP taglib URIs: `http://java.sun.com/jsp/jstl/core` still works with JSTL 3.0, while the `jakarta.tags.core` URI is the new canonical form. Prefer leaving the URIs unchanged in this stage.

## Java SE packages that must stay `javax`

`javax.sql` (`DataSource`, `RowSet`), `javax.naming`, `javax.crypto`, `javax.net`/`javax.net.ssl`, `javax.management`, `javax.script`, `javax.security.auth` / `javax.security.cert`, `javax.xml.parsers`, `javax.xml.transform`, `javax.xml.xpath`, `javax.xml.stream`, `javax.xml.validation`, `javax.xml.namespace`, `javax.imageio`, `javax.swing`, `javax.annotation.processing`. There is no `jakarta.sql` — a "package jakarta.sql does not exist" error means a Java SE import was wrongly renamed; rename it back to `javax.sql`.
