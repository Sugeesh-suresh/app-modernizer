# Web layer → Spring Boot (controllers, views, assets, `server.*`)
<!-- applies-to: controller, jsp, dispatcherservlet, webmvc -->

Target: `spring-boot-starter-web` (Spring MVC on embedded Tomcat 11, Servlet 6.1). Controllers stay; everything around them that Boot configures goes away. Per-element `web.xml` translations are in `java-8-to-25` › `webxml-to-javaconfig.md`; the JSP translation tables are in `java-8-to-25` › `jsp-to-thymeleaf.md` (not repeated here).

## MVC configuration

```java
// Before
@Configuration @EnableWebMvc @ComponentScan("com.acme.web")
public class WebConfig extends WebMvcConfigurerAdapter {
    @Override public void addInterceptors(InterceptorRegistry r) { r.addInterceptor(new AuditInterceptor()); }
    @Bean public InternalResourceViewResolver viewResolver() { … "/WEB-INF/views/", ".jsp" }
    @Bean public CommonsMultipartResolver multipartResolver() { … }
}
// After
@Configuration
public class WebConfig implements WebMvcConfigurer {          // no @EnableWebMvc, no @ComponentScan, no resolvers
    @Override public void addInterceptors(InterceptorRegistry r) { r.addInterceptor(new AuditInterceptor()); }
}
```
```yaml
spring.servlet.multipart: { max-file-size: 10MB, max-request-size: 20MB }
```
`@EnableWebMvc` switches off Boot's MVC auto-configuration (resource handling, message converters, error handling) and is conformance B009 — delete it. Keep `addInterceptors`, `addCorsMappings`, `addFormatters`, `addViewControllers`, `configureContentNegotiation`, `addResourceHandlers` (extra locations only) in the `WebMvcConfigurer`. Spring 7 removed suffix-pattern and trailing-slash matching: a client that called `/orders/` now needs an explicit mapping or a stated behaviour change. Prefer `@GetMapping` etc. when you touch a mapping; do not change paths.

## Controllers and exception handling

- `@Controller`/`@RestController` need no change beyond `jakarta.*` imports and `javax.servlet` types. Keep return types, status codes and model attribute names.
- `@ExceptionHandler` and `@ControllerAdvice` stay. XML `SimpleMappingExceptionResolver` → a `@ControllerAdvice` with `@ExceptionHandler` methods returning the same view names. Move to `ProblemDetail` only if the plan accepts a changed error body.
- `RestTemplate` calls from controllers/services → `RestClient` (inject the auto-configured `RestClient.Builder`: `builder.baseUrl(url).build()`); timeouts via `spring.http.client.*` or a `ClientHttpRequestFactory` customiser. Keep `RestTemplate` only where code depends on its API, built from `RestTemplateBuilder`.
- `@Value`-injected URLs and flags → `@ConfigurationProperties` records or classes with the same key names under an app prefix.

## Views: JSP → Thymeleaf (B004)

An executable JAR cannot serve JSP, so every `.jsp` and everything under `src/main/webapp/WEB-INF` goes. Mechanics: `jsp-to-thymeleaf.md` (same view names, so controllers do not change; `src/main/resources/templates/<name>.html`). This profile adds:

| Concern | Convert to |
|---|---|
| `InternalResourceViewResolver`, `spring.mvc.view.prefix/suffix` | delete; `spring.thymeleaf.prefix`/`suffix` only if templates live elsewhere |
| JSP include / Tiles layouts / SiteMesh | Thymeleaf fragments (`th:replace`, `th:fragment`); a layout dialect only if the plan names one |
| Spring form tags `<form:form>`, `<form:input path=>`, `<form:errors>` | `<form th:object="${cmd}" th:action="@{/x}">`, `th:field="*{name}"`, `th:errors="*{name}"` |
| `<spring:message code=>` | `th:text="#{code}"` (the `MessageSource`, `spring.messages.basename`) |
| `<spring:url>`, `<c:url>` | `@{/path}` |
| `<sec:authorize>` (security taglib) | `thymeleaf-extras-springsecurity`: `sec:authorize="hasRole('ADMIN')"` |
| Custom tag libraries / tag files | a fragment or a Thymeleaf dialect; no equivalent → an Open Question in the plan |
| `.jspf`, `web.xml` `<jsp-config>` | gone |

Every model attribute the JSP read is still set under the same name; every link resolves to the same URL including context path.

## Static assets and error pages

- `src/main/webapp/{css,js,img,*.html,favicon.ico}` → `src/main/resources/static/` (same URLs). `index.html` there is the welcome page. Delete `src/main/webapp` when empty.
- `<error-page>` → `templates/error/404.html`, `error/5xx.html` (or `static/error/…`); `server.error.whitelabel.enabled: false` only when a custom page exists; `server.error.include-message`/`include-stacktrace` set deliberately (the Boot default hides them).

## `server.*` — what the container used to provide

```yaml
server:
  port: 8080
  servlet:
    context-path: /orders-service        # the WAR's name, so existing URLs keep working
    encoding: { charset: UTF-8, force: true }
    session: { timeout: 30m, cookie: { http-only: true, secure: true } }
  compression: { enabled: true, mime-types: text/html,text/css,application/json }
  ssl: { enabled: false }                # key-store, key-store-password (${SSL_PASSWORD}) when TLS moved from server.xml
  shutdown: graceful
  tomcat:
    threads: { max: 200, min-spare: 10 }
    max-http-form-post-size: 2MB
    accesslog: { enabled: true, directory: logs, pattern: "%h %l %u %t \"%r\" %s %b" }
    connection-timeout: 20s
```
Tomcat tuning lives only in `server.tomcat.*` (or a `WebServerFactoryCustomizer<TomcatServletWebServerFactory>` for what properties cannot express). Never add Jetty or Undertow, never exclude Tomcat (B010). `server.xml`/`context.xml` settings that the plan lists map one-to-one onto these keys; a setting with no key is an Open Question.

## Check list

No `@EnableWebMvc`/adapter/resolver beans; URLs and context path unchanged; every view has a template; static files under `static/`; error pages reachable; `server.*` keys cover the former container settings.
