# Security → Spring Boot (Spring Security 7)
<!-- applies-to: security, spring-security -->

Target: `spring-boot-starter-security` with Spring Security 7 (Boot 4.x). Boot registers the security filter chain with the servlet container itself — there is no `DelegatingFilterProxy` and no `springSecurityFilterChain` in `web.xml`. Security 7 supports only the lambda DSL: `and()`, `authorizeRequests()`, `antMatchers()`, `mvcMatchers()` and `WebSecurityConfigurerAdapter` do not exist. Only convert the security the application already has; never introduce Spring Security speculatively. The base `webxml-to-javaconfig.md` shows the `<security-constraint>` case; the stage split is in the plan step (the adapter → `SecurityFilterChain` change fits the Boot 2.7 stage, the 6/7 DSL changes the 3.x and 4.x stages).

## XML `<http>` and the adapter → `SecurityFilterChain`

```xml
<security:http auto-config="true">
  <security:intercept-url pattern="/admin/**" access="hasRole('ADMIN')"/>
  <security:intercept-url pattern="/api/**"   access="isAuthenticated()"/>
  <security:intercept-url pattern="/**"       access="permitAll"/>
  <security:form-login login-page="/login" default-target-url="/home"/>
  <security:logout logout-success-url="/login?out"/>
  <security:csrf disabled="true"/>
</security:http>
```
```java
@Configuration
@EnableMethodSecurity
public class SecurityConfig {
    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http.authorizeHttpRequests(a -> a
                .requestMatchers("/admin/**").hasRole("ADMIN")      // order = the XML's order; first match wins
                .requestMatchers("/api/**").authenticated()
                .anyRequest().permitAll())
            .formLogin(f -> f.loginPage("/login").defaultSuccessUrl("/home"))
            .logout(l -> l.logoutSuccessUrl("/login?out"))
            .csrf(c -> c.disable());                                  // only if the XML disabled it — say so
        return http.build();
    }
}
```
A class that `extends WebSecurityConfigurerAdapter` converts the same way: `configure(HttpSecurity)` becomes the bean method; `configure(WebSecurity).ignoring()` becomes `requestMatchers(...).permitAll()` in the chain (or static resources via `PathRequest.toStaticResources().atCommonLocations()`). Keep the rule order exactly; add nothing the old config did not have.

| Old | New |
|---|---|
| `authorizeRequests()` / `antMatchers()` / `mvcMatchers()` | `authorizeHttpRequests(...)` / `requestMatchers(...)` |
| `.and()` chains | one lambda per concern |
| `hasAuthority`/`hasRole`/`access("…")` expressions | same names; `access(...)` takes an `AuthorizationManager` |
| `<intercept-url requires-channel="https">` | `server.ssl.*` and `http.requiresChannel(...)` only if HTTP still listens |
| `<http security="none" pattern="/static/**"/>` | a first, separate `SecurityFilterChain` with `@Order(1)` and `securityMatcher`, or `permitAll` |

## Users, passwords, authentication manager

```xml
<security:authentication-manager>
  <security:authentication-provider user-service-ref="userDetailsService">
    <security:password-encoder ref="passwordEncoder"/>
  </security:authentication-provider>
</security:authentication-manager>
```
```java
@Bean PasswordEncoder passwordEncoder() { return new BCryptPasswordEncoder(); }   // the encoder the stored hashes use
// a UserDetailsService bean is picked up automatically: @Service class UserDetailsServiceImpl implements UserDetailsService
```
- Keep the stored-hash format. Legacy `StandardPasswordEncoder`, `Md5PasswordEncoder`, `ShaPasswordEncoder` and `{plain}` are removed or deprecated: use `DelegatingPasswordEncoder` (`PasswordEncoderFactories.createDelegatingPasswordEncoder()`) with the id prefix the hashes carry, and flag a weak encoder as a follow-up instead of rehashing silently.
- `AuthenticationManagerBuilder` in `configureGlobal` → a `UserDetailsService` + `PasswordEncoder` bean (Boot builds the `DaoAuthenticationProvider`); a LDAP/custom provider → an `AuthenticationProvider` bean. An `AuthenticationManager` bean is only needed for programmatic login: `config.getAuthenticationManager()` from `AuthenticationConfiguration`.
- In-memory users in XML (`<user-service>`) → an `InMemoryUserDetailsManager` bean — with `{noop}`/`{bcrypt}` prefixes — or `spring.security.user.*` for a single user.

## Method security, CSRF, CORS, sessions

- `@EnableGlobalMethodSecurity(prePostEnabled = true)` / `<global-method-security>` → `@EnableMethodSecurity` (`@PreAuthorize`/`@PostAuthorize` on by default; `securedEnabled`/`jsr250Enabled` only if used).
- **CSRF** is on by default for state-changing requests. The old config's choice (disabled for a stateless API, exempt paths via `ignoringRequestMatchers`) is preserved exactly — a silent change here is a 403 regression or a vulnerability.
- **CORS:** `http.cors(Customizer.withDefaults())` plus one `CorsConfigurationSource` bean (`UrlBasedCorsConfigurationSource`) carrying the old origins/methods/headers; without it Security rejects pre-flight requests.
- **Sessions:** `<session-management>` → `.sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))` (or the old policy), `maximumSessions(...)`, `sessionFixation(...)`; timeouts in `server.servlet.session.timeout`, cookie flags in `server.servlet.session.cookie.*`.
- `<remember-me>` → `.rememberMe(...)`; `<anonymous>`, `<headers>` → `.anonymous(...)`, `.headers(...)` with the same values.
- Custom filters (`addFilterBefore(new JwtFilter(), UsernamePasswordAuthenticationFilter.class)`) keep their position; do not also register them as servlet filter beans (register once: a `FilterRegistrationBean` with `setEnabled(false)` stops the duplicate).
- The login success/failure handlers, `AuthenticationEntryPoint` and `AccessDeniedHandler` beans carry over as beans referenced in the chain.

## Check list

Every old URL rule has an equal; the first-match order is unchanged; login/logout URLs and the role names (`ROLE_` prefix) are the same; CSRF/CORS/session behaviour matches; a test (`@WebMvcTest` + `spring-security-test`) or the Evidence Plan row says how it is proved.
