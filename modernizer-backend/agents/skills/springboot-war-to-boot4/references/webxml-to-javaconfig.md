# web.xml → Spring Boot Java Config / application.yml Translation

Translate element by element. Do not attempt a bulk "convert the whole file" pass — each element below has a distinct target, and getting the target wrong (e.g. turning a `<filter>` into a `@Component` instead of an explicit `FilterRegistrationBean`) can silently change ordering or URL-pattern matching.

## `<servlet>` / `<servlet-mapping>`

```xml
<!-- Before -->
<servlet>
  <servlet-name>reports</servlet-name>
  <servlet-class>com.acme.ReportServlet</servlet-class>
</servlet>
<servlet-mapping>
  <servlet-name>reports</servlet-name>
  <url-pattern>/reports/*</url-pattern>
</servlet-mapping>
```

```java
// After
@Bean
public ServletRegistrationBean<ReportServlet> reportServlet() {
    ServletRegistrationBean<ReportServlet> bean =
        new ServletRegistrationBean<>(new ReportServlet(), "/reports/*");
    bean.setName("reports");
    return bean;
}
```
(`ReportServlet` itself just needs its `javax.servlet.*` imports renamed to `jakarta.servlet.*` — it does not need to become a Spring bean itself unless it has injected dependencies.)

## `<filter>` / `<filter-mapping>`

```xml
<!-- Before -->
<filter>
  <filter-name>auditFilter</filter-name>
  <filter-class>com.acme.AuditFilter</filter-class>
</filter>
<filter-mapping>
  <filter-name>auditFilter</filter-name>
  <url-pattern>/*</url-pattern>
</filter-mapping>
```

```java
// After
@Bean
public FilterRegistrationBean<AuditFilter> auditFilter() {
    FilterRegistrationBean<AuditFilter> bean = new FilterRegistrationBean<>(new AuditFilter());
    bean.addUrlPatterns("/*");
    bean.setName("auditFilter");
    return bean;
}
```

## `<listener>`

```xml
<!-- Before -->
<listener>
  <listener-class>com.acme.StartupListener</listener-class>
</listener>
```

```java
// After — a ServletContextListener can usually just become a Spring bean directly,
// Spring Boot auto-registers listener beans:
@Bean
public ServletListenerRegistrationBean<StartupListener> startupListener() {
    return new ServletListenerRegistrationBean<>(new StartupListener());
}
```

## `<context-param>`

```xml
<!-- Before -->
<context-param>
  <param-name>maxUploadSizeMb</param-name>
  <param-value>25</param-value>
</context-param>
```

```yaml
# After — application.yml, bound via a typed @ConfigurationProperties class
app:
  max-upload-size-mb: 25
```
Read the value via `@ConfigurationProperties(prefix = "app")` rather than `ServletContext.getInitParameter(...)` at the call sites that used it.

## `<error-page>`

```xml
<!-- Before -->
<error-page>
  <error-code>404</error-code>
  <location>/errors/not-found.html</location>
</error-page>
```

```yaml
# After
server:
  error:
    whitelabel:
      enabled: false
```
Plus a custom `ErrorController` bean (or a static `/error/404.html` under `src/main/resources/static` / `templates`, which Spring Boot's default `BasicErrorController` resolves automatically by status code).

## `<session-config>`

```xml
<!-- Before -->
<session-config>
  <session-timeout>30</session-timeout>
</session-config>
```

```yaml
# After
server:
  servlet:
    session:
      timeout: 30m
```

## `<welcome-file-list>`

```xml
<!-- Before -->
<welcome-file-list>
  <welcome-file>index.html</welcome-file>
</welcome-file-list>
```
No config needed after migration — Spring Boot's static-resource handling already serves `index.html` from `src/main/resources/static` as the welcome file by convention. Just make sure the file actually lives there after migration.

## `<security-constraint>` / `<login-config>`

These map to Spring Security, not a direct Java-config bean — this is the one translation that's a redesign, not a mechanical port:

```xml
<!-- Before -->
<security-constraint>
  <web-resource-collection>
    <url-pattern>/admin/*</url-pattern>
  </web-resource-collection>
  <auth-constraint><role-name>ADMIN</role-name></auth-constraint>
</security-constraint>
<login-config>
  <auth-method>FORM</auth-method>
  <form-login-config>
    <form-login-page>/login</form-login-page>
  </form-login-config>
</login-config>
```

```java
// After
@Bean
public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
    http.authorizeHttpRequests(auth -> auth
            .requestMatchers("/admin/**").hasRole("ADMIN")
            .anyRequest().permitAll())
        .formLogin(form -> form.loginPage("/login"));
    return http.build();
}
```
If the legacy app has no `<security-constraint>` at all, do not introduce Spring Security speculatively — only migrate what's actually there.

## After translating everything

Once every element above has a Java/YAML equivalent and there is nothing left in `web.xml` that isn't either (a) migrated or (b) explicitly noted as intentionally-kept-because-inexpressible, delete `web.xml`. A `web.xml` with only a `<display-name>` or an XML declaration left in it should still be deleted, not kept as a formality.
