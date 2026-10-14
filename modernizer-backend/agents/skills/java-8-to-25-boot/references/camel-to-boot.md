# Apache Camel on Spring Boot 4 (from Camel 2.x)
<!-- applies-to: camel -->

Camel is not a Spring component, but a Camel application ships its routes through Spring, and the Spring Boot conversion decides how they start. Every fact below was found by building a Camel 2.25 application up to Spring Boot 4.1 / Camel 4.22.

## Versions and BOMs

- Camel 2.x runs on Java 8; **Camel 4.x needs Java 17+ and Jakarta**. A Camel Spring Boot release targets one Boot line — read the `camel-parent` pom of the release you choose (`spring-boot-version`): 4.18.x targets Boot 3.5.x, 4.19–4.20 Boot 4.0.x, 4.22.x Boot 4.1.x. Resolve the pair from Maven Central; never guess it.
- Import **both** `org.apache.camel.springboot:camel-spring-boot-bom` and, from Camel 4.22 on, `camel-spring-boot-dependencies` (the first no longer manages plain `org.apache.camel` artifacts such as `camel-test-spring-junit5`). Declare them in `dependencyManagement` of the parent next to the Boot parent.

## Artifacts

| Camel 2.x | Camel 4 on Boot |
|---|---|
| `camel-core`, `camel-spring` | `camel-spring-boot-starter` |
| Spring XML `<camelContext>` | `camel-spring-boot-xml-starter` (note the name) while XML routes remain; Java route builders as `@Component` need nothing else |
| `camel-jackson` | `camel-jackson-starter` (Jackson 2 data format — see "When Jackson 2 stays on purpose" in `boot4-dependency-cleanup.md`); `camel-jackson3-starter` exists from 4.22 |
| `camel-http4` | `camel-http` |
| `camel-test`, `camel-test-spring` (JUnit 4) | `camel-test-spring-junit5` (JUnit 5 only: assertion message order flips, `assertTrue(cond, msg)`) |

## Application wiring

- A route builder becomes a `@Component extends RouteBuilder`; the starter creates, starts and stops the `CamelContext`, so delete any listener/bean that starts or stops it by hand. `camel.main.name` names the context.
- XML-declared beans become `@Component("<same id>")` (keep ids other code looks up). `ProducerTemplate` / `ConsumerTemplate` are provided by the starter: do not declare them again (`NoUniqueBeanDefinitionException`).
- Boot refuses bean-definition overriding, which Camel 2's XML relied on: an `<endpoint id>` that is also registered by the context, and a `<propertyPlaceholder id="properties">` (Camel's starter defines a bean called `properties`), fail the context at startup. Use `<from uri="…"/>` instead of `<endpoint>`, rename the placeholder id, or move the routes to Java.
- `camel.properties` keys move into `application.yml`; reference them with `{{key}}` placeholders as before.

## Camel 2 → 4 API changes that break compilation

| 2.x | 4.x |
|---|---|
| `beanRef(…)` | `bean(…)` |
| `.inOnly("uri")` | `.to(ExchangePattern.InOnly, "uri")` |
| `context.getRouteStatus(id)` | `context.getRouteController().getRouteStatus(id)` |
| `org.apache.camel.processor.aggregate.AggregationStrategy` | `org.apache.camel.AggregationStrategy` |
| `org.apache.camel.impl.DefaultExchange` | `org.apache.camel.support.DefaultExchange` |
| `JndiRegistry` | `context.getRegistry().bind(name, bean)` |
| `assertMockEndpointsSatisfied()` | `MockEndpoint.assertIsSatisfied(context)` |
| `context.getRouteDefinition(id).adviceWith(…)` | `AdviceWith.adviceWith(context, id, a -> …)` |

Find them by compiling, not by grep alone: every row above surfaced as a compile error in a real conversion.

## Java 17 and the XML bindings

Camel 2.25's `jaxb-impl` 2.3.0 fails on Java 17+ with `NPE … Injector.defineClass is null` until it is pinned (see `boot27-on-war.md`); the pin is unnecessary once Camel 4 is in.
