# Spring Boot Integration Patterns Reference

## BW Process → Spring Service Pattern

```java
// TIBCO: OrderProcess.bwp (HTTP Receive → JDBC Insert → JMS Send)
// Spring Boot equivalent:

@Service
@Slf4j
public class OrderProcessService {

    private final OrderRepository orderRepository;
    private final JmsTemplate jmsTemplate;

    public OrderProcessService(OrderRepository orderRepository, JmsTemplate jmsTemplate) {
        this.orderRepository = orderRepository;
        this.jmsTemplate = jmsTemplate;
    }

    @Transactional // MIGRATED FROM: BW Checkpoint
    public OrderResponse processOrder(OrderRequest request) {
        // MIGRATED FROM: JDBC Insert activity
        Order order = new Order(request.getCustomerId(), request.getTotal());
        orderRepository.save(order);

        // MIGRATED FROM: JMS Send activity
        jmsTemplate.convertAndSend("orders.processed", new OrderEvent(order.getId()));

        log.info("Order {} processed successfully", order.getId());
        return new OrderResponse(order.getId(), "CREATED");
    }
}
```

---

## HTTP Receive → @RestController

```java
// TIBCO: HTTP Receive on POST /orders
// Spring Boot:

@RestController
@RequestMapping("/orders")
public class OrderController {

    private final OrderProcessService orderProcessService;

    public OrderController(OrderProcessService orderProcessService) {
        this.orderProcessService = orderProcessService;
    }

    @PostMapping
    public ResponseEntity<OrderResponse> createOrder(@Valid @RequestBody OrderRequest request) {
        OrderResponse response = orderProcessService.processOrder(request);
        return ResponseEntity.status(HttpStatus.CREATED).body(response);
    }
}
```

---

## JMS Receive → @JmsListener

```java
// TIBCO: JMS Get from queue "orders.incoming"
// Spring Boot:

@Component
@Slf4j
public class OrderMessageConsumer {

    private final OrderProcessService orderProcessService;

    public OrderMessageConsumer(OrderProcessService orderProcessService) {
        this.orderProcessService = orderProcessService;
    }

    @JmsListener(destination = "${jms.queue.orders.incoming}")
    public void onMessage(OrderRequest request) {
        // MIGRATED FROM: JMS Queue Get + process flow
        log.info("Received order message: {}", request);
        orderProcessService.processOrder(request);
    }
}
```

---

## Timer → @Scheduled

```java
// TIBCO: Timer trigger every hour
// Spring Boot:

@Component
@Slf4j
public class OrderCleanupScheduler {

    private final OrderRepository orderRepository;

    public OrderCleanupScheduler(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    @Scheduled(cron = "${scheduler.cleanup.cron:0 0 * * * ?}") // every hour
    public void cleanupExpiredOrders() {
        // MIGRATED FROM: Timer + JDBC Delete activity
        log.info("Running order cleanup");
        orderRepository.deleteExpiredOrders(LocalDateTime.now().minusDays(30));
    }
}
```

---

## XSLT Transform → MapStruct Mapper

```java
// TIBCO: XSLT transform from OrderXML to OrderDTO
// Spring Boot: MapStruct mapper

@Mapper(componentModel = "spring")
public interface OrderMapper {

    // MIGRATED FROM: XSLT transform order-to-dto.xsl
    OrderDTO toDto(Order order);
    Order toEntity(OrderDTO dto);

    @Mapping(source = "lineItems", target = "items")
    @Mapping(source = "custId", target = "customerId")
    OrderDTO orderXmlToDto(OrderXml orderXml);
}
```

---

## Parallel Group → CompletableFuture

```java
// TIBCO: Group (Parallel) with HTTP Send to two services
// Spring Boot:

@Service
public class EnrichmentService {

    private final CustomerClient customerClient;
    private final InventoryClient inventoryClient;

    @Async
    public CompletableFuture<EnrichedOrder> enrichOrder(Order order) {
        // MIGRATED FROM: Parallel Group with 2 HTTP Send activities
        CompletableFuture<CustomerInfo> customerFuture =
            CompletableFuture.supplyAsync(() -> customerClient.get(order.getCustomerId()));
        CompletableFuture<InventoryInfo> inventoryFuture =
            CompletableFuture.supplyAsync(() -> inventoryClient.check(order.getProductId()));

        return CompletableFuture.allOf(customerFuture, inventoryFuture)
            .thenApply(v -> new EnrichedOrder(order,
                customerFuture.join(),
                inventoryFuture.join()));
    }
}
```

---

## Content-Based Routing → Strategy Pattern

```java
// TIBCO: Choice gateway routing on order.type
// Spring Boot:

@Service
public class OrderRouter {

    private final Map<String, OrderProcessor> processors;

    public OrderRouter(List<OrderProcessor> processorList) {
        this.processors = processorList.stream()
            .collect(Collectors.toMap(OrderProcessor::getType, p -> p));
    }

    public void route(Order order) {
        // MIGRATED FROM: TIBCO Choice/Switch activity
        OrderProcessor processor = processors.get(order.getType());
        if (processor == null) {
            throw new IllegalArgumentException("No processor for order type: " + order.getType());
        }
        processor.process(order);
    }
}

public interface OrderProcessor {
    String getType();
    void process(Order order);
}
```

---

## Dead Letter Queue (DLQ) Configuration

```java
// application.properties (ActiveMQ DLQ)
// spring.activemq.broker-url=tcp://localhost:61616

// DLQ handler
@Component
@Slf4j
public class DeadLetterHandler {

    @JmsListener(destination = "ActiveMQ.DLQ")
    public void handleDeadLetter(Message message) throws JMSException {
        log.error("Dead letter received: messageId={}, body={}",
            message.getJMSMessageID(),
            message instanceof TextMessage ? ((TextMessage) message).getText() : "binary");
        // Alert, store, or replay logic here
    }
}
```

---

## Global Exception Handler

```java
@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler {

    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<ErrorResponse> handleValidation(ConstraintViolationException e) {
        List<String> errors = e.getConstraintViolations().stream()
            .map(v -> v.getPropertyPath() + ": " + v.getMessage())
            .collect(Collectors.toList());
        return ResponseEntity.badRequest().body(new ErrorResponse("VALIDATION_ERROR", errors.toString()));
    }

    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ErrorResponse> handleBusiness(BusinessException e) {
        return ResponseEntity.status(e.getStatus())
            .body(new ErrorResponse(e.getCode(), e.getMessage()));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleGeneric(Exception e) {
        log.error("Unhandled exception", e);
        return ResponseEntity.internalServerError()
            .body(new ErrorResponse("INTERNAL_ERROR", "An unexpected error occurred"));
    }
}
```
