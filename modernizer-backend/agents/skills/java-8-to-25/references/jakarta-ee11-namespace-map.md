# javax.* → jakarta.* Namespace Map (Jakarta EE 11 surface)

Spring Boot 4 / Spring Framework 7 sit on Jakarta EE 11. This is a superset of the handful of packages most migrations remember (Servlet, Persistence, Validation) — a legacy WAR app frequently touches several of the others below too, especially if it predates Spring Boot entirely. Only rename a package if it appears in this table; if you find a `javax.*` import that isn't listed here, it's almost certainly a **Java SE** package (e.g. `javax.crypto`, `javax.net.ssl`, `javax.sql`, `javax.management`) that never moved to `jakarta.*` and must be left alone.

| Legacy `javax.*` package | Modern `jakarta.*` package | Where it shows up in a legacy WAR |
|---|---|---|
| `javax.servlet` | `jakarta.servlet` | `HttpServlet`, `ServletContext`, `ServletContainerInitializer` |
| `javax.servlet.http` | `jakarta.servlet.http` | `HttpServletRequest`/`Response`, `HttpSession`, `Cookie` |
| `javax.servlet.annotation` | `jakarta.servlet.annotation` | `@WebServlet`, `@WebFilter`, `@WebListener`, `@MultipartConfig` |
| `javax.servlet.jsp` | `jakarta.servlet.jsp` | Legacy JSP pages/tag handlers, if any survive the migration |
| `javax.servlet.jsp.jstl` | `jakarta.servlet.jsp.jstl` | JSTL tag library usage in JSPs |
| `javax.persistence` | `jakarta.persistence` | JPA entities, `EntityManager`, `@Table`/`@Column`/`@Id` |
| `javax.validation` | `jakarta.validation` | Bean Validation (`@NotNull`, `@Size`, `Validator`) |
| `javax.annotation` | `jakarta.annotation` | `@PostConstruct`, `@PreDestroy`, `@Resource` (note: `@Generated` and a few others moved to `jakarta.annotation` too — do not assume this package is Servlet-only) |
| `javax.transaction` | `jakarta.transaction` | `@Transactional` (JTA form), `UserTransaction` |
| `javax.ejb` | `jakarta.ejb` | Legacy EJB annotations, if the app has an EJB-lite layer |
| `javax.jms` | `jakarta.jms` | JMS `ConnectionFactory`, `MessageListener` |
| `javax.mail` | `jakarta.mail` | Legacy `javax.mail.*` mail-sending code (note: many apps already use `org.simplejavamail`/Spring's `JavaMailSender` wrapper instead — only rename raw `javax.mail.*` usage) |
| `javax.ws.rs` | `jakarta.ws.rs` | JAX-RS annotations (`@Path`, `@GET`) if the app mixes JAX-RS with Spring MVC |
| `javax.xml.bind` | `jakarta.xml.bind` | JAXB (`@XmlRootElement`) — also requires an explicit runtime dependency since it was removed from the JDK entirely at Java 11 |
| `javax.websocket` | `jakarta.websocket` | `@ServerEndpoint`, `Session` for raw WebSocket usage |
| `javax.enterprise.context` / `javax.enterprise.inject` | `jakarta.enterprise.context` / `jakarta.enterprise.inject` | CDI scopes (`@ApplicationScoped`) — rare in a Spring app, but present if the WAR was originally CDI-based before Spring was layered in |
| `javax.inject` | `jakarta.inject` | `@Inject`, `@Qualifier` used instead of Spring's own `@Autowired`/`@Qualifier` |
| `javax.interceptor` | `jakarta.interceptor` | `@AroundInvoke`, `@Interceptors` |
| `javax.faces` | `jakarta.faces` | JSF, if present — flag for manual review rather than auto-converting; JSF-on-Spring-Boot-4 combinations are uncommon enough to warrant a human decision on whether to keep JSF at all |
| `javax.security.auth.message` | `jakarta.security.auth.message` | JASPIC-based custom authentication, if present |

## Things that look like this pattern but are NOT part of the rename

- `javax.crypto`, `javax.net.ssl`, `javax.sql`, `javax.naming`, `javax.management`, `javax.script` — these are Java SE packages, not Jakarta EE, and keep the `javax.*` prefix forever regardless of Jakarta EE version.
- `javax.swing`, `javax.imageio` — Java SE desktop/AWT packages, irrelevant to a web app but sometimes dragged in by a legacy dependency; leave untouched.

## Verification after renaming

After renaming imports, grep the whole in-scope file set for the string `javax.` once more — any hit should be one of the Java SE packages above (expected) or a genuine miss (needs fixing). Do not consider the namespace shift complete until that check comes back clean.
