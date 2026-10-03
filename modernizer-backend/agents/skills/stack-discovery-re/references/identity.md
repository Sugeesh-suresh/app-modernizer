# Identity and directory (LDAP, Active Directory, SSO) — what to document

Where to look:
- Security configuration: Spring Security configuration classes (`WebSecurityConfigurerAdapter`, `SecurityFilterChain` beans), `ldapAuthentication()`, `LdapAuthenticationProvider`, `ActiveDirectoryLdapAuthenticationProvider`, `LdapTemplate`, JNDI/`javax.naming` directory code
- Properties: `spring.ldap.*`, custom `ldap.*` keys, profile-specific files (`application-<env>.properties|yml`) — URLs, base DNs, search filters, group search bases, bind users (credentials `[REDACTED]`)
- Authorisation: URL rules (`antMatchers`/`mvcMatchers`/`requestMatchers` with `hasRole`/`hasAuthority`/`permitAll`), method security (`@PreAuthorize`, `@Secured`, `@RolesAllowed`), view security (`sec:authorize`)
- Login and session: login pages, success/failure handlers, logout, session timeout, remember-me, CSRF settings

What to record:
- How a user is authenticated: provider, directory URL and base DN, user search filter or DN pattern, and whether it is switchable per environment (a property that enables or disables it)
- How directory groups become application roles (group search base and filter, role prefix, authority mapping)
- Every role, and what each role can reach: URL patterns, methods and page elements — as a table of Role | Can access | Defined in
- Anonymous/public paths
- Where each setting comes from per environment, with unresolved `${...}` values marked unresolved
- Tests that cover authentication or authorisation and what they need (embedded LDAP, mocks)
