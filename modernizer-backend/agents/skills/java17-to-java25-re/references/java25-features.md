# Java 25 Features Reference

## New Language Features to Adopt

### Virtual Threads (Project Loom — stable since Java 21)
```java
// Before (Java 17): thread pool
ExecutorService pool = Executors.newFixedThreadPool(200);
pool.submit(() -> handleRequest(req));

// After (Java 25): virtual threads
ExecutorService vt = Executors.newVirtualThreadPerTaskExecutor();
vt.submit(() -> handleRequest(req));

// Or directly
Thread.ofVirtual().start(() -> handleRequest(req));
```
**Use when:** Any blocking I/O operation (DB calls, HTTP calls, file reads).

---

### Pattern Matching for switch (stable since Java 21)
```java
// Before (Java 17)
if (shape instanceof Circle) {
    Circle c = (Circle) shape;
    return Math.PI * c.radius() * c.radius();
} else if (shape instanceof Rectangle r) {
    return r.width() * r.height();
}

// After (Java 25)
return switch (shape) {
    case Circle c    -> Math.PI * c.radius() * c.radius();
    case Rectangle r -> r.width() * r.height();
    case null        -> throw new NullPointerException("shape is null");
    default          -> throw new IllegalArgumentException("Unknown shape");
};
```

---

### Records (stable since Java 16 — expand usage in Java 25)
```java
// Before (Java 17 DTO with Lombok)
@Value
public class OrderDto {
    Long id;
    String customerName;
    BigDecimal total;
}

// After (Java 25 record)
public record OrderDto(Long id, String customerName, BigDecimal total) {
    // Compact constructor for validation
    public OrderDto {
        Objects.requireNonNull(customerName, "customerName required");
        if (total.compareTo(BigDecimal.ZERO) < 0) throw new IllegalArgumentException("total must be >= 0");
    }
}
```

---

### Sealed Classes (stable since Java 17 — more adoption in Java 25)
```java
public sealed interface PaymentResult
    permits PaymentSuccess, PaymentFailure, PaymentPending {}

public record PaymentSuccess(String transactionId) implements PaymentResult {}
public record PaymentFailure(String errorCode, String message) implements PaymentResult {}
public record PaymentPending(String referenceId) implements PaymentResult {}

// Exhaustive switch — compiler enforces all cases
String message = switch (result) {
    case PaymentSuccess s  -> "Payment " + s.transactionId() + " approved";
    case PaymentFailure f  -> "Payment failed: " + f.message();
    case PaymentPending p  -> "Awaiting confirmation: " + p.referenceId();
};
```

---

### String Templates (Preview → Stable in Java 25)
```java
// Before
String sql = "SELECT * FROM orders WHERE customer_id = " + customerId + " AND status = '" + status + "'";

// After (String Templates — use prepared statements equivalent)
String msg = STR."Order \{orderId} for customer \{customerName} totals \{total}";
// Note: For SQL, always use PreparedStatement — String Templates are for logging/messages only
```

---

### Sequenced Collections (stable since Java 21)
```java
// New methods on List, Deque, LinkedHashSet, LinkedHashMap
List<String> items = new ArrayList<>(List.of("a", "b", "c"));
String first = items.getFirst();   // replaces items.get(0)
String last  = items.getLast();    // replaces items.get(items.size()-1)
items.addFirst("z");               // replaces items.add(0, "z")
items.addLast("d");                // replaces items.add("d")
List<String> reversed = items.reversed(); // new: reversed view
```

---

### Unnamed Variables (Java 22+)
```java
// Before: unused variable warning
try {
    parse(input);
} catch (ParseException e) {  // 'e' unused
    throw new RuntimeException("parse failed");
}

// After: unnamed variable
try {
    parse(input);
} catch (ParseException _) {
    throw new RuntimeException("parse failed");
}
```

---

## Deprecated / Removed APIs in Java 25

| API | Status | Replacement |
|---|---|---|
| `Thread.stop()`, `Thread.suspend()`, `Thread.resume()` | Removed | Use interruption + cooperative cancellation |
| `SecurityManager` | Removed | JVM security flags / OS-level isolation |
| `Applet API` | Removed | N/A |
| `RMI Activation` | Removed | REST / gRPC |
| `CMS Garbage Collector` | Removed | G1GC (default), ZGC, or Shenandoah |
| `javax.annotation.*` (legacy) | Replaced | `jakarta.annotation.*` |
| `java.util.Date` | Deprecated | `java.time.*` (LocalDate, Instant, etc.) |
| `Finalize` / `Object.finalize()` | Deprecated for removal | `Cleaner` API |

---

## Third-Party Library Compatibility (Java 25)

| Library | Min Version for Java 25 |
|---|---|
| Spring Boot | 3.3+ |
| Hibernate ORM | 6.4+ |
| Jackson | 2.17+ |
| Mockito | 5.x |
| JUnit | 5.10+ |
| Lombok | 1.18.34+ |
| MapStruct | 1.5.5+ |
| Flyway | 10.x |
| Testcontainers | 1.20+ |
