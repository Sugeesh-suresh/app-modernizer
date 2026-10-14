# camel-jboss-monorepo

Legacy-style Java 8 monorepo used as a **test fixture for the Java 8 -> 25 + Spring Boot 4
migration pipeline**. It is a small order platform: **10 REST endpoints** (Spring MVC 4.3) that feed
**Apache Camel 2.25** integration routes, packaged as a WAR for **JBoss EAP 7 / WildFly**.
No database, broker or network is needed; everything is in-process or file based.

Stack: Java 1.8, Maven multi-module, Spring 4.3.30, Apache Camel 2.25.4, Jackson 2.9.10, JUnit 4.13.2,
Mockito 4.11, Hibernate Validator 5.3 (tests), log4j 1.2 + slf4j, servlet 3.1.

```
mvn -B -nsu test                    # 37 tests, all modules
mvn -B -nsu -DskipTests package     # orders-api/target/orders-api.war
```

## Module map

| Module | Packaging | Contents |
|--------|-----------|----------|
| `shared-model` | jar | `Order`, `OrderLine`, `Customer`, `Shipment`, `StatusReport`, `OrderStatus`, `OrderUtil`; javax.validation constraints |
| `camel-routes` | jar | Java DSL route builders, Spring XML route (`META-INF/spring/camel-context.xml`), processors, beans, predicate, aggregation strategy, `CamelRoutesConfig`, `camel.properties` |
| `orders-api` | war | `@RestController`s, `@ControllerAdvice`, `CorrelationIdFilter`, `CamelContextListener`, `WEB-INF` XML (web, applicationContext, api-servlet), JBoss descriptors |

Other: `deploy/jboss-cli/orders-api.cli`, `docs/DEPLOY.md`.

## REST endpoints (context root `/orders-api`)

| # | Method and path | Behaviour |
|---|-----------------|-----------|
| 1 | `GET /api/orders` | list orders |
| 2 | `GET /api/orders/{id}` | one order, 404 JSON error if unknown |
| 3 | `POST /api/orders` | validated, stored, sent to `direct:orderIn` through `ProducerTemplate`; 202 |
| 4 | `PUT /api/orders/{id}` | replace order content |
| 5 | `DELETE /api/orders/{id}` | 204, or 404 |
| 6 | `GET /api/orders/{id}/shipment` | shipment created by the fulfilment route |
| 7 | `GET /api/customers` | list customers |
| 8 | `GET /api/customers/{id}` | one customer |
| 9 | `POST /api/routes/report/trigger` | runs `direct:report` once and returns the `StatusReport` |
| 10 | `GET /api/health` | Camel context and per-route status |

Errors are JSON (`ApiError`): 400 for validation/malformed JSON (with `fieldErrors`), 404 for unknown ids.

## Camel routes

| Route id | Style | Flow |
|----------|-------|------|
| `order-intake` | Java DSL | `direct:orderIn` -> validate processor -> `choice` on `PriorityPredicate` (lane header) -> `split` lines -> `LineEnricher` bean -> `OrderRegistry` -> `seda:fulfilment` |
| `fulfilment` | Java DSL | `seda:fulfilment` -> `ShipmentService` -> marshal JSON -> `file:target/outbox` -> `direct:notify` |
| `notify` | Java DSL | `direct:notify` -> aggregator (per carrier, size 3 / timeout 1.5 s) -> log |
| `report-timer`, `report` | Java DSL | `timer:report` -> registry -> `direct:report` -> `StatusReportBuilder` -> log |
| `dead-letter` | Java DSL | `direct:deadLetter` -> `DeadLetterProcessor` (marks order REJECTED) -> `DeadLetterStore` |
| `customer-lookup` | Spring XML | `direct:customerLookup` -> `<bean ref="customerDirectory">` -> `<marshal><json/>`, with `<onException>` redelivery and dead letter |

Error handling: `AbstractOrderRoute` sets a `deadLetterChannel("direct:deadLetter")` with 2 redeliveries,
plus `onException` clauses. Placeholders (`{{outbox.dir}}`, `{{report.period}}`) come from `camel.properties`.

## JBoss shape

* `WEB-INF/jboss-web.xml`: context root `/orders-api`, security domain `orders-security-domain`
* `WEB-INF/jboss-deployment-structure.xml`: excludes jaxrs subsystem and container log4j/slf4j/Jackson/RESTEasy modules, depends on `org.hibernate.validator`
* `Dependencies: javax.api` in the WAR manifest
* `servlet-api` and `validation-api` are `provided`
* See `docs/DEPLOY.md` and `deploy/jboss-cli/orders-api.cli`

## Tests (37)

shared-model 6 (Bean Validation), camel-routes 13 (`CamelTestSupport` with mock endpoints and
`adviceWith`, `CamelSpringTestSupport` against the XML context, `NotifyBuilder`), orders-api 18
(MockMvc standalone for all 10 endpoints, filter, listener, real WEB-INF context wiring).
