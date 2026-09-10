# TIBCO EMS Baseline — Patterns to Look For, and How They Map to Pub/Sub

## Destination types
- **Queue** (point-to-point, one consumer per message) → a Pub/Sub **topic with a single subscription** (or, if multiple competing consumers were pulling from the same EMS queue for load-balancing, a single Pub/Sub subscription pulled by multiple worker instances — Pub/Sub subscriptions already load-balance across pullers)
- **Topic** (publish/subscribe, every durable subscriber gets every message) → a Pub/Sub **topic with one subscription per durable subscriber**
- **Durable subscriber** (`createDurableSubscriber`, survives consumer disconnects) → a Pub/Sub subscription (subscriptions persist independently of subscriber connectivity by default — this maps naturally)

## Message selectors
- JMS selector syntax (`JMSType = 'order' AND priority > 5`) has **no direct Pub/Sub equivalent** at the broker level. Pub/Sub filters on **message attributes** using its own filter syntax (`attributes.type = "order"`) but does NOT support arbitrary SQL-92-like expressions (no numeric comparisons like `priority > 5` in filters as of common Pub/Sub versions — verify against current Pub/Sub filter syntax docs, and if the selector can't be expressed as a filter, plan for filtering in the consumer application code instead)
- Every selector must be translated to either a Pub/Sub subscription filter (simple equality/attribute-presence checks) or moved into consumer-side logic (anything more complex)

## Delivery semantics
- EMS supports transacted sessions and `CLIENT_ACKNOWLEDGE` for precise redelivery control
- Pub/Sub is **at-least-once by default** (exactly-once delivery is available as a specific subscription setting in some configurations — call out explicitly whether the BRD requires it) — any consumer logic that assumed EMS wouldn't redeliver must become idempotent
- EMS preserves strict FIFO per queue by default in many configurations; Pub/Sub ordering requires explicitly enabling **message ordering keys** on the topic/subscription — flag any flow relying on strict ordering

## Client API mapping
| TIBCO EMS / JMS | Google Cloud Pub/Sub |
|---|---|
| `javax.jms.ConnectionFactory` / `com.tibco.tibjms.TibjmsConnectionFactory` | `com.google.cloud.pubsub.v1.Publisher` / `Subscriber` |
| `Session.createProducer(destination)` + `producer.send(message)` | `Publisher.publish(PubsubMessage)` |
| `MessageConsumer.setMessageListener(listener)` | `Subscriber.newBuilder(subscriptionName, receiver).build()` |
| `TextMessage`/`BytesMessage` | `PubsubMessage` with `ByteString` data + `attributes` map (JMS properties → Pub/Sub attributes) |
| `Session.CLIENT_ACKNOWLEDGE` + `message.acknowledge()` | `AckReplyConsumer.ack()` / `.nack()` passed to the message receiver callback |
| Durable subscriber name | Pub/Sub subscription name (create once, reuse) |

## Configuration tells
- `.substvar` files with EMS connection URLs (`tcp://` or `ssl://` TIBCO EMS server addresses)
- Spring JMS (`<jms:listener-container>`, `@JmsListener`) wired to a TIBCO `ConnectionFactory` bean
- TIBCO BusinessWorks `.bwp` process files with JMS Queue/Topic Receiver or Sender activities
