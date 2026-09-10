# Spring Boot 4 BFF Code Patterns

## pom.xml skeleton (JAR, not WAR)

```xml
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>4.0.0</version>
  </parent>
  <groupId>com.acme</groupId>
  <artifactId>bff</artifactId>
  <version>1.0.0</version>
  <packaging>jar</packaging>
  <properties>
    <java.version>25</java.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-validation</artifactId>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
```

## Application entry point

```java
@SpringBootApplication
public class Application {
    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}
```

## Thin controller delegating to a service

```java
@RestController
@RequestMapping("/api/cart")
public class CartController {

    private final CartService cartService;

    public CartController(CartService cartService) {
        this.cartService = cartService;
    }

    @GetMapping
    public CartResponse getCart(@AuthenticationPrincipal UserPrincipal user) {
        return cartService.getCart(user.id());
    }

    @PostMapping("/items")
    public CartResponse addItem(
            @AuthenticationPrincipal UserPrincipal user,
            @Valid @RequestBody AddItemRequest request) {
        return cartService.addItem(user.id(), request);
    }
}
```

## Service holding the classified business logic

```java
@Service
public class CartService {

    private final CartRepository cartRepository;
    private final PricingService pricingService;

    public CartService(CartRepository cartRepository, PricingService pricingService) {
        this.cartRepository = cartRepository;
        this.pricingService = pricingService;
    }

    public CartResponse getCart(String userId) {
        var cart = cartRepository.findByUserId(userId);
        // Authoritative pricing/discount calculation lives here, server-side --
        // ported directly from the legacy scriptlet's discount logic.
        var total = pricingService.calculateTotal(cart);
        return new CartResponse(cart.items(), total);
    }
}
```

## record DTOs, not exposed entities

```java
public record CartResponse(List<CartItemDto> items, BigDecimal total) {}
public record CartItemDto(String productId, String name, int quantity, BigDecimal unitPrice) {}
public record AddItemRequest(@NotBlank String productId, @Min(1) int quantity) {}
```

## Structured validation error response

```java
@RestControllerAdvice
public class ApiExceptionHandler {

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleValidation(MethodArgumentNotValidException ex) {
        var fieldErrors = ex.getBindingResult().getFieldErrors().stream()
            .map(fe -> new FieldError(fe.getField(), fe.getDefaultMessage()))
            .toList();
        return ResponseEntity.badRequest().body(new ErrorResponse("VALIDATION_ERROR", fieldErrors));
    }
}

public record ErrorResponse(String code, List<FieldError> fieldErrors) {}
public record FieldError(String field, String message) {}
```

## Session-cookie-based auth (the usual translation of legacy HttpSession)

```java
@Bean
public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
    http.authorizeHttpRequests(auth -> auth
            .requestMatchers("/api/auth/**").permitAll()
            .anyRequest().authenticated())
        .sessionManagement(session -> session
            .sessionCreationPolicy(SessionCreationPolicy.IF_REQUIRED));
    return http.build();
}
```
The browser carries the session cookie automatically on every subsequent request — the React app does not need to manage a token at all in this mode. Only reach for JWT/token-based auth if the plan's Session & Auth Strategy explicitly calls for statelessness.
