# TIBCO EMS messaging — what to document

Where to look:
- Client code: `com.tibco.tibjms.*`, JMS API usage (`javax.jms`/`jakarta.jms`), Spring JMS templates and listener containers, MDBs
- Configuration: connection-factory definitions, JNDI properties, server URLs, destination names, `tibjmsd.conf`/`queues.conf`/`topics.conf`/`factories.conf` if present, Spring XML
- Message formats: XML schemas, JSON samples, serialised classes, mapping code

What to record:
- Every queue and topic: name, where it is defined, producers and consumers (class and method)
- Connection factories, server URLs, SSL and authentication settings (credentials redacted), reconnect and failover settings
- Message types (Text/Map/Object/Bytes), payload structure, headers and properties set and read
- Acknowledgement and transaction modes, durable subscriptions, selectors, redelivery and error/dead-letter handling
- Request/reply patterns, temporary destinations, correlation IDs
- The business flow each message carries, end to end
- Tests that exercise messaging and what they need (embedded broker, mocks, real server)
