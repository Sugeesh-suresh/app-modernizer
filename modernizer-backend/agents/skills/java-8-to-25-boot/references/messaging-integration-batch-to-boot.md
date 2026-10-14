# Messaging, integration, batch, scheduling, mail → Spring Boot
<!-- applies-to: jms, amqp, kafka, batch, integration -->

Each Spring messaging or job module becomes its Boot starter plus `application.yml`; the listener and job code stays, the XML infrastructure goes. Convert one module at a time, keep destination names, selectors, concurrency, acknowledgement mode and cron expressions exactly, and never change a payload shape. Where the repository contains the module, the conformance scanner (B006) names the starter for any explicit `org.springframework.*` dependency — use that name.

## JMS

```xml
<jee:jndi-lookup id="connectionFactory" jndi-name="jms/ConnectionFactory"/>
<jms:listener-container connection-factory="connectionFactory" concurrency="3-10" acknowledge="auto">
  <jms:listener destination="orders.in" ref="orderListener" method="onMessage"/>
</jms:listener-container>
<bean id="jmsTemplate" class="org.springframework.jms.core.JmsTemplate"><property name="connectionFactory" ref="connectionFactory"/></bean>
```
```java
@Component
class OrderListener {
    @JmsListener(destination = "orders.in", concurrency = "3-10")
    void onMessage(String body) { … }          // jakarta.jms.* — not javax
}
```
```yaml
spring:
  jms:
    listener: { concurrency: 3, max-concurrency: 10, acknowledge-mode: auto }
  artemis:                       # or spring.activemq.* — the broker the app already uses; TIBCO EMS / other vendors: vendor's own starter or a ConnectionFactory bean (the one legitimate manual bean)
    broker-url: ${JMS_URL}
    user: ${JMS_USER}
    password: ${JMS_PASSWORD}
```
`JmsTemplate` is auto-configured: delete the bean and inject it. A JNDI `ConnectionFactory` becomes broker properties bound to environment variables. A `MessageListener` class with `onMessage(Message)` can stay a `@JmsListener`-annotated method or implement `MessageListener` registered through a `JmsListenerConfigurer`.

## AMQP / RabbitMQ and Kafka

- `<rabbit:connection-factory>`, `<rabbit:template>`, `<rabbit:listener-container>` → `spring.rabbitmq.host/port/username/password/virtual-host`, `@RabbitListener`; queues, exchanges and bindings declared as `Queue`/`Exchange`/`Binding` beans (kept: they are topology, not auto-configured). Concurrency/ack → `spring.rabbitmq.listener.simple.*`.
- Kafka: `ProducerFactory`/`ConsumerFactory`/`KafkaTemplate` beans → `spring.kafka.bootstrap-servers`, `.consumer.group-id`, `.consumer.auto-offset-reset`, `.producer.*`, serializers by class name; `@KafkaListener` stays. A custom `ErrorHandler` becomes a `CommonErrorHandler` bean.

## Spring Integration and Spring Batch

- **Integration:** `spring-boot-starter-integration`; XML `<int:*>` flows → the Java DSL (`IntegrationFlow` `@Bean` methods) or `@MessagingGateway`/`@ServiceActivator`. Keep channel names. A flow too large to convert in one task is split by flow, never half-converted.
- **Batch:** `spring-boot-starter-batch`; delete the `JobRepository`/`JobLauncher`/`DataSourceTransactionManager` beans Boot auto-configures. `<batch:job>` XML → a `Job` bean built with `JobBuilder`/`StepBuilder` (Batch 6 style: a `JobRepository` and transaction manager are injected into the builders). Jobs launched at startup: `spring.batch.job.enabled`, `spring.batch.job.name`; schema: `spring.batch.jdbc.initialize-schema`. A job started by `CommandLineJobRunner` or a `main` method is launched by Boot's runner or an explicit `JobLauncher` call from the existing trigger.

## Scheduling, async, mail

```xml
<task:annotation-driven executor="exec" scheduler="sched"/>
<task:scheduled-tasks scheduler="sched"><task:scheduled ref="cleaner" method="run" cron="0 0 2 * * ?"/></task:scheduled-tasks>
```
```java
@Component class Cleaner { @Scheduled(cron = "0 0 2 * * ?") void run() { … } }   // same cron, same bean, one registration
```
```yaml
spring:
  task:
    scheduling: { pool.size: 4, thread-name-prefix: sched- }
    execution:  { pool: { core-size: 8, max-size: 16, queue-capacity: 100 } }
  mail: { host: ${MAIL_HOST}, port: 587, username: ${MAIL_USER}, password: ${MAIL_PASSWORD} }
```
- `@EnableScheduling` / `@EnableAsync` stay on a `@Configuration` (or the application class) — Boot does not turn them on. The executors are auto-configured: delete `ThreadPoolTaskExecutor`/`ThreadPoolTaskScheduler` beans unless they carry a non-property setting. An `@Async("exec")` qualifier keeps its name. Never enable virtual threads (`spring.threads.virtual.enabled`) unless the plan says so.
- A Quartz `SchedulerFactoryBean` → `spring-boot-starter-quartz`, `spring.quartz.*`; jobs stay `Job` classes.
- `JavaMailSenderImpl` bean → `spring.mail.*`, inject `JavaMailSender`; `javax.mail` → `jakarta.mail`.

## Check list

Same destinations and cron values; each listener or job registered exactly once; broker and mail credentials are `${ENV}` placeholders listed for ops; no `javax.jms`/`javax.mail` import; no XML `<jms:*>`, `<rabbit:*>`, `<int:*>`, `<batch:*>`, `<task:*>` left.
