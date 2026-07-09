# Quarkus Common Fix Recipes

## Fix: javax → jakarta Namespace

**Error:** `cannot find symbol: class Inject` / `package javax.ws.rs does not exist`

**Fix:** Global find-and-replace in all `.java` files:
```
javax.ws.rs       → jakarta.ws.rs
javax.inject      → jakarta.inject
javax.persistence → jakarta.persistence
javax.transaction → jakarta.transaction
javax.validation  → jakarta.validation
javax.annotation  → jakarta.annotation
```

---

## Fix: Missing CDI Scope

**Error:** `Unsatisfied dependencies for type OrderService`

**Fix:** Add `@ApplicationScoped` (or appropriate scope) to the class:
```java
// Before
public class OrderService { ... }

// After
@ApplicationScoped
public class OrderService { ... }
```

---

## Fix: Wrong Panache Parent Class

**Error:** `cannot find symbol: method list(String, Object)`

**Fix:** Ensure entity extends `PanacheEntity` (not plain `Object` or other base):
```java
// Before
@Entity
public class Order { @Id @GeneratedValue Long id; ... }

// After
@Entity
public class Order extends PanacheEntity { ... }
// id field is inherited — remove any manual @Id field
```

---

## Fix: Missing Jackson Extension

**Error:** `No message body writer found for class X`

**Fix:** Add to `pom.xml`:
```xml
<dependency>
  <groupId>io.quarkus</groupId>
  <artifactId>quarkus-resteasy-reactive-jackson</artifactId>
</dependency>
```

---

## Fix: Missing Quarkus BOM

**Error:** `Could not find artifact io.quarkus:quarkus-resteasy-reactive`

**Fix:** Add BOM to `<dependencyManagement>` in `pom.xml`:
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

---

## Fix: @ConfigProperty Not Resolving

**Error:** `javax.inject.Provider is not a valid injection type`  
or `No ConfigSource found for key X`

**Fix:** Correct import and ensure property exists in `application.properties`:
```java
import org.eclipse.microprofile.config.inject.ConfigProperty;

@ConfigProperty(name = "my.key", defaultValue = "default-value")
String myKey;
```

---

## Fix: @Transactional Scope Missing

**Error:** `Transaction is required to perform this operation`

**Fix:** Add `@Transactional` to the service method (not the resource):
```java
import jakarta.transaction.Transactional;

@ApplicationScoped
public class OrderService {

    @Transactional
    public Order create(OrderDto dto) {
        Order order = new Order();
        // ... map fields
        order.persist(); // Panache
        return order;
    }
}
```

---

## Fix: application.properties Wrong Keys

**Error:** `Unrecognised configuration key "spring.datasource.url"`

**Fix:** Replace Spring keys with Quarkus equivalents:
```properties
# Wrong (Spring)
spring.datasource.url=jdbc:postgresql://localhost/mydb
spring.datasource.username=user
spring.datasource.password=pass
server.port=8080

# Correct (Quarkus)
quarkus.datasource.db-kind=postgresql
quarkus.datasource.jdbc.url=jdbc:postgresql://localhost/mydb
quarkus.datasource.username=user
quarkus.datasource.password=pass
quarkus.http.port=8080
```

---

## Fix: @RegisterForReflection for Native Image

**Error:** `ClassNotFoundException` or `InstantiationException` at native runtime

**Fix:** Add reflection registration:
```java
@RegisterForReflection
public class MyDto { ... }

// Or register multiple classes:
@RegisterForReflection(targets = {OrderDto.class, CustomerDto.class})
public class NativeConfig {}
```

---

## Fix: REST Client URL Not Configured

**Error:** `io.quarkus.restclient.runtime.RestClientBase: URL not configured`

**Fix:** Add to `application.properties`:
```properties
quarkus.rest-client."com.example.PaymentClient".url=https://api.payment.example.com
# Or use configKey:
quarkus.rest-client.payment-api.url=https://api.payment.example.com
```

And annotate the client:
```java
@RegisterRestClient(configKey = "payment-api")
public interface PaymentClient { ... }
```
