# Quarkus Code Patterns Reference

## JAX-RS Resource (replaces @RestController)
```java
@Path("/orders")
@Produces(MediaType.APPLICATION_JSON)
@Consumes(MediaType.APPLICATION_JSON)
@ApplicationScoped
public class OrderResource {

    @Inject
    OrderService orderService;

    @GET
    public List<OrderDto> listAll() {
        return orderService.findAll();
    }

    @GET
    @Path("/{id}")
    public OrderDto getById(@PathParam("id") Long id) {
        return orderService.findById(id)
            .orElseThrow(() -> new NotFoundException("Order " + id + " not found"));
    }

    @POST
    @Transactional
    public Response create(OrderDto dto) {
        OrderDto created = orderService.create(dto);
        return Response.status(Response.Status.CREATED).entity(created).build();
    }
}
```

## CDI Service Bean (replaces @Service)
```java
@ApplicationScoped
public class OrderService {

    @Inject
    OrderRepository orderRepository;

    public List<OrderDto> findAll() {
        return orderRepository.listAll().stream()
            .map(this::toDto)
            .collect(Collectors.toList());
    }

    @Transactional
    public OrderDto create(OrderDto dto) {
        Order order = toEntity(dto);
        orderRepository.persist(order);
        return toDto(order);
    }
}
```

## Panache Entity Pattern (replaces @Entity + JpaRepository)
```java
@Entity
@Table(name = "orders")
public class Order extends PanacheEntity {
    // id field inherited from PanacheEntity

    @Column(nullable = false)
    public String customerName;

    public BigDecimal total;

    @Enumerated(EnumType.STRING)
    public OrderStatus status;

    // Static finder methods
    public static List<Order> findByStatus(OrderStatus status) {
        return list("status", status);
    }

    public static Optional<Order> findByIdOptional(Long id) {
        return findByIdOptional(id);
    }
}
```

## Panache Repository Pattern (alternative)
```java
@ApplicationScoped
public class OrderRepository implements PanacheRepository<Order> {

    public List<Order> findByCustomer(String customerName) {
        return list("customerName", customerName);
    }

    public Page<Order> findAllPaged(int page, int size) {
        return findAll().page(Page.of(page, size));
    }
}
```

## Configuration Injection (replaces @Value)
```java
@ApplicationScoped
public class PaymentService {

    @ConfigProperty(name = "payment.gateway.url")
    String gatewayUrl;

    @ConfigProperty(name = "payment.timeout", defaultValue = "30")
    int timeoutSeconds;
}
```

## Configuration Group (replaces @ConfigurationProperties)
```java
@ConfigMapping(prefix = "payment")
public interface PaymentConfig {
    String gatewayUrl();
    int timeout();
    TlsConfig tls();

    interface TlsConfig {
        boolean enabled();
        String certPath();
    }
}
```

## Scheduler (replaces @Scheduled)
```java
@ApplicationScoped
public class ReportScheduler {

    @Scheduled(every = "1h", identity = "report-job")
    void generateReport() {
        // runs every hour
    }

    @Scheduled(cron = "0 0 2 * * ?")
    void nightlyCleanup() {
        // runs at 2am daily
    }
}
```

## CDI Event (replaces @EventListener / ApplicationEventPublisher)
```java
// Publisher
@ApplicationScoped
public class OrderService {
    @Inject
    Event<OrderCreatedEvent> orderCreatedEvent;

    public void create(Order order) {
        orderRepository.persist(order);
        orderCreatedEvent.fire(new OrderCreatedEvent(order.id));
    }
}

// Listener
@ApplicationScoped
public class NotificationService {
    void onOrderCreated(@Observes OrderCreatedEvent event) {
        // handle event
    }
}
```

## Exception Mapper (replaces @ControllerAdvice)
```java
@Provider
public class ValidationExceptionMapper
    implements ExceptionMapper<ConstraintViolationException> {

    @Override
    public Response toResponse(ConstraintViolationException e) {
        return Response.status(Response.Status.BAD_REQUEST)
            .entity(Map.of("errors", e.getConstraintViolations().stream()
                .map(v -> v.getPropertyPath() + ": " + v.getMessage())
                .collect(Collectors.toList())))
            .build();
    }
}
```

## Security Role Check (replaces @PreAuthorize)
```java
@Path("/admin")
@RolesAllowed("admin")
public class AdminResource {

    @GET
    @Path("/users")
    @RolesAllowed({"admin", "manager"})
    public List<User> listUsers() { ... }
}
```

## REST Client (replaces RestTemplate / WebClient)
```java
@RegisterRestClient(configKey = "payment-api")
@Path("/payments")
public interface PaymentClient {

    @POST
    @Produces(MediaType.APPLICATION_JSON)
    PaymentResponse charge(PaymentRequest request);
}

// In application.properties:
// quarkus.rest-client.payment-api.url=https://payment.example.com
```

## Native Image: Register for Reflection
```java
@RegisterForReflection(targets = {OrderDto.class, CustomerDto.class})
public class ReflectionConfig {}
```
