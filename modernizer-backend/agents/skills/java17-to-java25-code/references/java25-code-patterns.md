# Java 25 Code Pattern Examples

## Virtual Threads for Blocking I/O

```java
// Before (Java 17): platform thread pool for DB/HTTP calls
@Configuration
public class AsyncConfig implements AsyncConfigurer {
    @Bean
    public Executor asyncExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(20);
        executor.setMaxPoolSize(100);
        return executor;
    }
}

// After (Java 25): virtual thread executor
@Configuration
public class AsyncConfig implements AsyncConfigurer {
    @Override
    public Executor getAsyncExecutor() {
        return Executors.newVirtualThreadPerTaskExecutor();
    }
}

// Spring Boot shortcut in application.properties:
// spring.threads.virtual.enabled=true
```

---

## Records as DTOs

```java
// Before (Java 17 with Lombok)
@Value
@Builder
public class CreateOrderRequest {
    Long customerId;
    List<OrderItem> items;
    BigDecimal total;
}

// After (Java 25 record)
public record CreateOrderRequest(
    Long customerId,
    List<OrderItem> items,
    BigDecimal total
) {
    public CreateOrderRequest {
        Objects.requireNonNull(customerId, "customerId required");
        Objects.requireNonNull(items, "items required");
        if (items.isEmpty()) throw new IllegalArgumentException("items must not be empty");
        items = List.copyOf(items); // defensive copy
    }
}
```

---

## Sealed Classes for Domain Results

```java
// Before (Java 17): unconstrained class hierarchy
public abstract class ProcessingResult {}
public class SuccessResult extends ProcessingResult { String id; }
public class FailureResult extends ProcessingResult { String error; }

// After (Java 25): sealed hierarchy
public sealed interface ProcessingResult
    permits ProcessingResult.Success, ProcessingResult.Failure {

    record Success(String id) implements ProcessingResult {}
    record Failure(String errorCode, String message) implements ProcessingResult {}
}

// Exhaustive pattern matching — no default needed
String message = switch (result) {
    case ProcessingResult.Success(var id) -> "Processed: " + id;
    case ProcessingResult.Failure(var code, var msg) -> "Failed [" + code + "]: " + msg;
};
```

---

## Pattern Matching Switch

```java
// Before (Java 17)
public BigDecimal calculateArea(Shape shape) {
    if (shape instanceof Circle) {
        Circle c = (Circle) shape;
        return BigDecimal.valueOf(Math.PI * c.radius() * c.radius());
    } else if (shape instanceof Rectangle) {
        Rectangle r = (Rectangle) shape;
        return r.width().multiply(r.height());
    }
    throw new IllegalArgumentException("Unknown shape: " + shape);
}

// After (Java 25)
public BigDecimal calculateArea(Shape shape) {
    return switch (shape) {
        case Circle c    -> BigDecimal.valueOf(Math.PI * c.radius() * c.radius());
        case Rectangle r -> r.width().multiply(r.height());
        case Triangle t  -> t.base().multiply(t.height()).divide(BigDecimal.TWO);
    };
}
```

---

## Sequenced Collections

```java
// Before (Java 17)
List<Task> tasks = taskRepository.findAll();
Task first = tasks.get(0);
Task last  = tasks.get(tasks.size() - 1);
tasks.add(0, urgentTask);

// After (Java 25)
List<Task> tasks = taskRepository.findAll();
Task first = tasks.getFirst();
Task last  = tasks.getLast();
tasks.addFirst(urgentTask);
List<Task> reversed = tasks.reversed(); // view, not copy
```

---

## String Templates (for messages/logging only — never for SQL)

```java
// Before (Java 17)
log.info("Order " + orderId + " created for customer " + customerId + " with total " + total);

// After (Java 25)
log.info(STR."Order \{orderId} created for customer \{customerId} with total \{total}");

// IMPORTANT: Never use String Templates for SQL queries
// Always use PreparedStatement / JPA parameters
```

---

## Unnamed Variables

```java
// Before (Java 17): suppress unused warning
for (int i = 0; i < retries; i++) {
    try {
        return callExternalService();
    } catch (TimeoutException e) {   // e is unused
        log.warn("Timeout, retrying...");
    }
}

// After (Java 25)
for (int _ = 0; _ < retries; _++) {
    try {
        return callExternalService();
    } catch (TimeoutException _) {
        log.warn("Timeout, retrying...");
    }
}
```

---

## Replacing Object.finalize()

```java
// Before (Java 17) — DEPRECATED
public class ResourceHolder {
    @Override
    protected void finalize() {
        releaseResource();
    }
}

// After (Java 25) — use Cleaner
public class ResourceHolder implements AutoCloseable {
    private static final Cleaner CLEANER = Cleaner.create();
    private final Cleaner.Cleanable cleanable;

    public ResourceHolder() {
        cleanable = CLEANER.register(this, this::releaseResource);
    }

    private void releaseResource() {
        // cleanup code
    }

    @Override
    public void close() {
        cleanable.clean();
    }
}
```

---

## ReentrantLock instead of synchronized (for Virtual Thread compatibility)

```java
// Before — synchronized can pin virtual threads to carrier threads
public synchronized void process(Order order) {
    // critical section
}

// After — ReentrantLock doesn't pin virtual threads
private final ReentrantLock lock = new ReentrantLock();

public void process(Order order) {
    lock.lock();
    try {
        // critical section
    } finally {
        lock.unlock();
    }
}
```
