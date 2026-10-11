# TIBCO EMS → Google Cloud Pub/Sub Migration Checklist

## Destination Mapping

| EMS Construct | Pub/Sub Equivalent |
|---|---|
| Queue (point-to-point) | Topic + single subscription (or one subscription pulled by multiple worker instances for load balancing) |
| Topic (pub/sub) | Topic + one subscription per durable subscriber |
| Durable subscriber | A named Pub/Sub subscription, created once and reused |
| Non-durable subscriber | A Pub/Sub subscription with a short/no retained-message policy, or an ephemeral subscription created at consumer startup and deleted at shutdown |

## Message Selector Translation

| Selector Complexity | Action |
|---|---|
| Simple attribute equality (`JMSType = 'order'`) | Pub/Sub subscription filter: `attributes.type = "order"` |
| Attribute presence check | Pub/Sub filter: `attributes:type` |
| Numeric/range comparison, boolean logic beyond simple AND of equalities | No direct filter support — move the check into consumer application code after receiving the message |

## Delivery Semantics

| EMS Assumption | Pub/Sub Reality | Required Change |
|---|---|---|
| `CLIENT_ACKNOWLEDGE` / transacted session | At-least-once by default | Ensure consumer logic is idempotent (dedupe by message ID or business key) before relying on redelivery being rare |
| Strict per-queue FIFO | No ordering by default | Enable message ordering keys on the topic AND matching ordering on the subscription if strict order is a hard requirement; otherwise document that ordering is no longer guaranteed |
| Exactly-once processing assumption | Pub/Sub offers exactly-once delivery only under specific subscription configuration | Explicitly configure it if required, and document the throughput/latency trade-off |

## Client API Migration

| TIBCO EMS / JMS | Google Cloud Pub/Sub |
|---|---|
| `TibjmsConnectionFactory` | `TopicAdminClient`/`SubscriptionAdminClient` (admin) + `Publisher`/`Subscriber` (data plane) |
| `producer.send(TextMessage)` | `publisher.publish(PubsubMessage.newBuilder().setData(ByteString.copyFromUtf8(text)).build())` |
| `MessageConsumer.setMessageListener` | `Subscriber.newBuilder(subscriptionName, (message, consumer) -> { ...; consumer.ack(); }).build()` |
| JMS message properties | Pub/Sub message `attributes` map |
| `message.acknowledge()` | `AckReplyConsumer.ack()` |
| Redelivery / rollback (`session.recover()`) | `AckReplyConsumer.nack()` |

## Dependency Changes
- Add: `com.google.cloud:google-cloud-pubsub` (Java) at a current version
- Remove: the TIBCO EMS client JAR (`tibjms.jar` / `com.tibco:tibjms`) once every reference is migrated

## Explicitly Out of Scope (document, do not attempt)
- Provisioning the actual GCP topics/subscriptions (Terraform/gcloud) — infrastructure work
- EMS server decommissioning
- Draining in-flight messages during cutover
