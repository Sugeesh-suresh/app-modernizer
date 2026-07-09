# Quarkus Build Error Checklist

## Import Errors

| Error Pattern | Likely Cause | Fix |
|---|---|---|
| `cannot find symbol: javax.ws.rs.*` | Wrong namespace | Change `javax.ws.rs` → `jakarta.ws.rs` |
| `cannot find symbol: javax.inject.*` | Wrong namespace | Change `javax.inject` → `jakarta.inject` |
| `cannot find symbol: javax.persistence.*` | Wrong namespace | Change `javax.persistence` → `jakarta.persistence` |
| `cannot find symbol: javax.transaction.*` | Wrong namespace | Change `javax.transaction` → `jakarta.transaction` |
| `cannot find symbol: javax.validation.*` | Wrong namespace | Change `javax.validation` → `jakarta.validation` |
| `PanacheEntity not found` | Missing extension | Add `quarkus-hibernate-orm-panache` to pom.xml |
| `@ConfigProperty not found` | Missing import | `import org.eclipse.microprofile.config.inject.ConfigProperty` |
| `@RegisterRestClient not found` | Missing import | `import org.eclipse.microprofile.rest.client.inject.RegisterRestClient` |

## CDI / Injection Errors

| Error Pattern | Likely Cause | Fix |
|---|---|---|
| `Unsatisfied dependency for type X` | Bean not found | Add CDI scope annotation (`@ApplicationScoped`, etc.) |
| `Ambiguous dependency for type X` | Multiple beans | Add `@Default` or `@Named` qualifier |
| `@Inject on non-managed type` | Class not CDI-managed | Add scope annotation to the class |
| `Cannot use @Inject on static field` | Static injection | Use `Arc.container().instance(X.class).get()` instead |
| `@Produces method in non-bean` | No scope on producer class | Add `@ApplicationScoped` to the class containing `@Produces` |

## JAX-RS / RESTEasy Errors

| Error Pattern | Likely Cause | Fix |
|---|---|---|
| `No message body writer found for type X` | Missing Jackson | Add `quarkus-resteasy-reactive-jackson` extension |
| `@Path must start with '/'` | Missing slash | Prepend `/` to `@Path` value |
| `Method not allowed (405)` | Missing HTTP verb annotation | Add `@GET`, `@POST`, etc. |
| `Multiple resource methods match` | Ambiguous paths | Make `@Path` values unique |
| `@PathParam not found in @Path` | Name mismatch | Ensure `{name}` in `@Path` matches `@PathParam("name")` |

## Panache Errors

| Error Pattern | Likely Cause | Fix |
|---|---|---|
| `Entity class must not be final` | Final class | Remove `final` modifier |
| `PanacheEntity.id is null after persist` | Auto-ID not configured | Add `@GeneratedValue(strategy = GenerationType.IDENTITY)` |
| `list() not found on PanacheEntity` | Wrong parent class | Use `PanacheEntity` (not `PanacheEntityBase`) or `PanacheRepository<T>` |
| `No @Entity annotation` | Missing annotation | Add `@Entity` to the entity class |
| `Unknown column in field list` | Column name mismatch | Add `@Column(name = "actual_column_name")` |

## pom.xml Errors

| Error Pattern | Likely Cause | Fix |
|---|---|---|
| `Plugin goal not found: quarkus:build` | Missing plugin | Add `quarkus-maven-plugin` to `<build><plugins>` |
| `Dependency version conflict` | Missing BOM | Import `quarkus-bom` in `<dependencyManagement>` |
| `Extension artifact not found` | Wrong artifact ID | Use `io.quarkus:quarkus-<name>` (no version needed with BOM) |
| `javax namespace artifacts` | Old Spring dependencies | Remove `javax.*` dependencies; Quarkus uses Jakarta EE |

## application.properties Errors

| Error Pattern | Likely Cause | Fix |
|---|---|---|
| `Unknown property: spring.datasource.url` | Spring key used | Change to `quarkus.datasource.jdbc.url` |
| `Unknown property: server.port` | Spring key used | Change to `quarkus.http.port` |
| `%prod.quarkus... not recognised` | Missing profile prefix | Use `%dev.`, `%test.`, `%prod.` prefixes |
| `Datasource not configured` | Missing driver config | Set `quarkus.datasource.db-kind` (postgresql, mysql, h2) |

## Native Image Errors

| Error Pattern | Likely Cause | Fix |
|---|---|---|
| `ClassNotFoundException at runtime` | Missing reflection config | Add `@RegisterForReflection` to affected classes |
| `NoClassDefFoundError for proxy` | Missing proxy config | Add interface to `proxy-config.json` |
| `Resource not found in native image` | Missing resource config | Add path to `resource-config.json` |
| `UnsupportedFeatureException: Invoke dynamic` | Dynamic class loading | Refactor to avoid `Class.forName()` or register via config |
