package com.acme.orders.camel;

import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.ImportResource;

/**
 * Spring entry point of the camel-routes module. Importing it into an application context
 * brings in the CamelContext ("orderCamelContext"), the ProducerTemplate ("producerTemplate"),
 * the ConsumerTemplate ("consumerTemplate"), every Java DSL RouteBuilder and the XML route,
 * all declared in META-INF/spring/camel-context.xml.
 */
@Configuration
@ImportResource("classpath:META-INF/spring/camel-context.xml")
public class CamelRoutesConfig {
}
