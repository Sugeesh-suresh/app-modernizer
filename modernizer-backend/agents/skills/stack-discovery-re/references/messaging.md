# Messaging (Kafka, ActiveMQ/Artemis, RabbitMQ, IBM MQ, JMS) — what to document

Where to look:
- Client code: producers, consumers, listeners, message-driven beans, Spring JMS/Kafka/AMQP templates and listener containers
- Configuration: broker URLs, connection factories, JNDI names, topics/queues/exchanges/bindings, consumer groups, serialisers, security
- Message formats: schemas (Avro/JSON/XML), DTOs, mapping code

What to record:
- Every destination (queue/topic/exchange/stream): name, where defined, producers and consumers (class and method)
- Connection and client configuration (credentials redacted), retries, reconnection, concurrency
- Message types, payload structure, headers/properties, keys and partitioning
- Acknowledgement, transactions, ordering, idempotency, dead-letter and error handling
- The business flow each message carries end to end
- Tests that exercise messaging and what they need (embedded broker, mocks, real broker)
