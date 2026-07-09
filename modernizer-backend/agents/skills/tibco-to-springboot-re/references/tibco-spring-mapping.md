# TIBCO BusinessWorks → Spring Boot Mapping Reference

## Activity → Spring Boot Class Mapping

| TIBCO BW Activity | Spring Boot Equivalent | Notes |
|---|---|---|
| HTTP Receive | `@RestController` + `@RequestMapping` | Maps inbound HTTP trigger to Spring REST endpoint |
| HTTP Send/Invoke | `RestTemplate` or `WebClient` | Outbound HTTP calls |
| SOAP Send/Invoke | `JAX-WS @WebServiceClient` or CXF | WSDL-based service calls |
| JDBC Execute | `JdbcTemplate.query/update` or Spring Data JPA | SQL operations |
| JMS Get / JMS Queue Get | `@JmsListener` | Async message consumption |
| JMS Send | `JmsTemplate.convertAndSend()` | Message publishing |
| File Read | `Files.readAllBytes()` / `FileSystemResource` | File input |
| File Write | `Files.write()` / `FileOutputStream` | File output |
| File Poller | `@Scheduled` + directory watch or `FileSystemWatcher` | Directory polling |
| Parse XML | Jackson XML / JAXB `@XmlRootElement` | XML → Java object |
| Render XML | Jackson XML / JAXB `Marshaller` | Java object → XML |
| XSLT Transform | MapStruct mapper or `javax.xml.transform.Transformer` | Data transformation |
| Call Process (sub-process) | Private `@Service` method call | Method invocation |
| Group (Parallel) | `CompletableFuture.allOf()` or `@Async` | Parallel execution |
| Group (Iterate) | `for` loop or stream `.forEach()` | Sequential iteration |
| Checkpoint | `@Transactional` boundary | Transaction commit point |
| Set Shared Variable | Spring `@Component` singleton state or Redis | Shared state |
| Get Shared Variable | Inject `@Autowired` component or Redis get | State retrieval |
| Sleep | `Thread.sleep()` or `@Scheduled(fixedDelay=...)` | Delay |
| Log | SLF4J `logger.info/error/warn()` | Logging |
| Throw (fault) | `throw new CustomException()` | Error signalling |
| Catch (error handler) | `@ExceptionHandler` or try/catch in service | Error handling |
| Dead Letter | Spring DLQ config for JMS/Kafka | Unprocessable messages |
| Timer | `@Scheduled(cron="...")` | Cron-based scheduling |
| FTP Get/Put | Apache Commons Net `FTPClient` or Spring Integration FTP | FTP operations |

## Configuration Migration (.substvar → application.properties)

| TIBCO .substvar Key Pattern | Spring Boot application.properties |
|---|---|
| `HTTP.port` | `server.port` |
| `JDBC.url` | `spring.datasource.url` |
| `JDBC.username` | `spring.datasource.username` |
| `JDBC.password` | `spring.datasource.password` |
| `JMS.broker.url` | `spring.activemq.broker-url` or `spring.artemis.host` |
| `JMS.queue.name` | Custom `@Value("${jms.queue.name}")` |
| `HTTP.endpoint.url` | Custom `@Value("${external.service.url}")` |
| `FTP.host` | Custom `@Value("${ftp.host}")` |

## Spring Boot Architecture Decisions

### Spring Integration vs Apache Camel
- **Spring Integration**: Best when flows are simple (HTTP → DB → JMS). Native Spring, smaller dependency.
- **Apache Camel**: Best for complex routing (CBR, split/aggregate, transformation chains). Richer connector library.

### Transaction Strategy
| BW Checkpoint | Spring Boot |
|---|---|
| Process-level checkpoint | `@Transactional` on `@Service` method |
| Group checkpoint | Nested `@Transactional(propagation = REQUIRES_NEW)` |
| JMS + JDBC in same transaction | `@JmsTransactionManager` + `ChainedTransactionManager` |
| XA (distributed) transaction | `JtaTransactionManager` + Atomikos/Narayana |

## Error Handling Patterns

```java
// Global exception handler (replaces BW error handler on all processes)
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ErrorResponse> handleBusiness(BusinessException e) {
        return ResponseEntity.badRequest()
            .body(new ErrorResponse(e.getCode(), e.getMessage()));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleGeneric(Exception e) {
        log.error("Unexpected error", e);
        return ResponseEntity.internalServerError()
            .body(new ErrorResponse("INTERNAL_ERROR", "An unexpected error occurred"));
    }
}

// Dead Letter Queue configuration (ActiveMQ)
// application.properties:
// spring.activemq.packages.trust-all=true
// spring.jms.listener.acknowledge-mode=auto
```

## Common TIBCO → Spring Data Types

| TIBCO Data Type | Java/Spring Equivalent |
|---|---|
| `anyType` | `Object` or `Map<String, Object>` |
| `anySimpleType` | `String` |
| `xsd:string` | `String` |
| `xsd:int` | `Integer` / `int` |
| `xsd:long` | `Long` / `long` |
| `xsd:decimal` | `BigDecimal` |
| `xsd:dateTime` | `java.time.LocalDateTime` |
| `xsd:date` | `java.time.LocalDate` |
| `Document` (TIBCO) | `org.w3c.dom.Document` or `String` (XML) |
