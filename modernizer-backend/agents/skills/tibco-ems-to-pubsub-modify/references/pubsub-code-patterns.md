# TIBCO EMS → Google Cloud Pub/Sub Code Patterns

## Producer: JMS send → Pub/Sub publish
```java
// Before (TIBCO EMS / JMS)
ConnectionFactory cf = new TibjmsConnectionFactory("tcp://ems-host:7222");
Connection conn = cf.createConnection();
Session session = conn.createSession(false, Session.AUTO_ACKNOWLEDGE);
Destination dest = session.createQueue("orders.queue");
MessageProducer producer = session.createProducer(dest);
TextMessage msg = session.createTextMessage(payload);
msg.setStringProperty("type", "order");
producer.send(msg);

// After (Google Cloud Pub/Sub)
TopicName topicName = TopicName.of("my-project", "orders-topic");
Publisher publisher = Publisher.newBuilder(topicName).build();
PubsubMessage message = PubsubMessage.newBuilder()
    .setData(ByteString.copyFromUtf8(payload))
    .putAttributes("type", "order")
    .build();
publisher.publish(message).get();
```

## Consumer: JMS MessageListener → Pub/Sub Subscriber
```java
// Before
MessageConsumer consumer = session.createConsumer(dest, "type = 'order'");
consumer.setMessageListener(message -> {
    TextMessage tm = (TextMessage) message;
    process(tm.getText());
    message.acknowledge();
});

// After — the "type = 'order'" selector becomes a subscription filter
// (configured on the subscription itself, not in code) plus a plain receiver:
SubscriptionName subscriptionName = SubscriptionName.of("my-project", "orders-sub");
MessageReceiver receiver = (message, consumer) -> {
    process(message.getData().toStringUtf8());
    consumer.ack();
};
Subscriber subscriber = Subscriber.newBuilder(subscriptionName, receiver).build();
subscriber.startAsync().awaitRunning();
```

## Selector too complex for a subscription filter → move into consumer code
```java
// Before: JMS selector "priority > 5 AND region = 'EU'" (numeric comparison — no direct Pub/Sub filter equivalent)

// After: subscription filter only covers what it can (region = "EU"),
// the numeric comparison moves into the receiver:
MessageReceiver receiver = (message, consumer) -> {
    int priority = Integer.parseInt(message.getAttributesOrDefault("priority", "0"));
    if (priority <= 5) {
        consumer.ack(); // not for us, but still acknowledge so it isn't redelivered forever
        return;
    }
    process(message);
    consumer.ack();
};
```

## Idempotency under at-least-once delivery
```java
// After — guard against Pub/Sub redelivery when the old code assumed
// EMS's CLIENT_ACKNOWLEDGE meant "delivered exactly once in practice"
MessageReceiver receiver = (message, consumer) -> {
    String messageId = message.getMessageId();
    if (alreadyProcessed(messageId)) {
        consumer.ack();
        return;
    }
    process(message);
    markProcessed(messageId);
    consumer.ack();
};
```
