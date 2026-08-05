# Java 11 → Java 25 Code Patterns

## Records replace boilerplate DTOs
```java
// Before (Java 11)
public class OrderDto {
    private final Long id;
    private final String customerName;
    public OrderDto(Long id, String customerName) { this.id = id; this.customerName = customerName; }
    public Long getId() { return id; }
    public String getCustomerName() { return customerName; }
    // equals/hashCode/toString omitted for brevity
}

// After (Java 25)
public record OrderDto(Long id, String customerName) {
    public OrderDto {
        Objects.requireNonNull(customerName, "customerName required");
    }
}
```

## Pattern matching replaces instanceof chains
```java
// Before
if (shape instanceof Circle) {
    Circle c = (Circle) shape;
    return Math.PI * c.getRadius() * c.getRadius();
} else if (shape instanceof Rectangle) {
    Rectangle r = (Rectangle) shape;
    return r.getWidth() * r.getHeight();
}

// After — pattern matching for switch (Java 21+)
return switch (shape) {
    case Circle c    -> Math.PI * c.radius() * c.radius();
    case Rectangle r -> r.width() * r.height();
    case null        -> throw new NullPointerException("shape is null");
    default          -> throw new IllegalArgumentException("Unknown shape");
};
```

## Virtual threads replace blocking-I/O thread pools
```java
// Before (Java 11)
ExecutorService pool = Executors.newFixedThreadPool(200);
pool.submit(() -> handleRequest(req));

// After (Java 25)
ExecutorService vt = Executors.newVirtualThreadPerTaskExecutor();
vt.submit(() -> handleRequest(req));
```

## Text blocks replace concatenated multi-line strings
```java
// Before
String sql = "SELECT id, name, status\n" +
             "FROM orders\n" +
             "WHERE customer_id = ?";

// After
String sql = """
    SELECT id, name, status
    FROM orders
    WHERE customer_id = ?
    """;
```

## Sealed hierarchies replace open class hierarchies
```java
// Before
public interface PaymentResult {}
public class PaymentSuccess implements PaymentResult { /* ... */ }
public class PaymentFailure implements PaymentResult { /* ... */ }

// After
public sealed interface PaymentResult permits PaymentSuccess, PaymentFailure {}
public record PaymentSuccess(String transactionId) implements PaymentResult {}
public record PaymentFailure(String errorCode, String message) implements PaymentResult {}
```

## Sequenced collections replace index-0/size-1 idioms
```java
// Before
String first = items.get(0);
String last = items.get(items.size() - 1);
items.add(0, "z");

// After (Java 21+)
String first = items.getFirst();
String last = items.getLast();
items.addFirst("z");
```

## javax.* -> jakarta.* (only if the plan calls for a Jakarta EE 9+ bump)
```java
// Before
import javax.persistence.Entity;
import javax.validation.constraints.NotNull;
import javax.servlet.http.HttpServletRequest;

// After
import jakarta.persistence.Entity;
import jakarta.validation.constraints.NotNull;
import jakarta.servlet.http.HttpServletRequest;
```
