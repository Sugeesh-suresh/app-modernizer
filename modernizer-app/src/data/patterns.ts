import type { PatternConfig } from '../types';

export const PATTERNS: PatternConfig[] = [
  {
    id: 'java-8-to-25',
    title: 'Java 8 → Java 25',
    description:
      'A tool-driven agent scans your real repository, plans a bigbang or phased incremental migration (Readiness → Java 17 → Spring Boot 2.7 → 3.x → Java 25 → Spring Boot 4 → executable JAR), applies it file by file, then actually compiles it and iterates until the build passes.',
    from: 'Java 8',
    to: 'Java 25',
    fromBadge: 'bg-amber-500/20 text-amber-700 border-amber-500/30',
    toBadge: 'bg-blue-500/20 text-blue-700 border-blue-500/30',
    gradient: 'from-amber-500/10 via-transparent to-blue-500/10',
    iconBg: 'bg-gradient-to-br from-amber-500 to-blue-600',
    benefits: [
      'Bigbang, or 4-phase incremental with a real build after every step',
      'Real repo scan + real mvn/gradle compile validation',
      'Optional JUnit 4→5 and Spring Boot 4.x executable-JAR upgrade with Spring Data JPA',
      'Records, sealed types, pattern matching & virtual threads',
      'javax.* → jakarta.* namespace migration',
    ],
  },
  {
    id: 'solr-4-to-9',
    title: 'Solr 4x → Solr 9x',
    description:
      'Migrate Solr 4.x schema, solrconfig.xml, and SolrJ client code to Solr 9.x — Point field types, modern request handlers, and the current SolrJ client API.',
    from: 'Solr 4.x',
    to: 'Solr 9.x',
    fromBadge: 'bg-red-500/20 text-red-700 border-red-500/30',
    toBadge: 'bg-orange-500/20 text-orange-700 border-orange-500/30',
    gradient: 'from-red-500/10 via-transparent to-orange-500/10',
    iconBg: 'bg-gradient-to-br from-red-500 to-orange-600',
    benefits: [
      'Trie* fields → Point field types',
      'solrconfig.xml handler & luceneMatchVersion updates',
      'HttpSolrServer/CloudSolrServer → *Client builder API',
      'Deterministic config validation (no live Solr needed)',
      'Reindexing & SolrCloud follow-up called out explicitly',
    ],
  },
  {
    id: 'oracle-19c-to-23ai',
    title: 'Oracle 19c → 23ai',
    description:
      'Migrate Oracle 19c SQL/PLSQL to 23ai compatibility — deprecated construct cleanup, optional JSON-relational duality and AI Vector Search adoption where it fits.',
    from: 'Oracle 19c',
    to: 'Oracle 23ai',
    fromBadge: 'bg-rose-500/20 text-rose-700 border-rose-500/30',
    toBadge: 'bg-red-600/20 text-red-800 border-red-600/30',
    gradient: 'from-rose-500/10 via-transparent to-red-600/10',
    iconBg: 'bg-gradient-to-br from-rose-600 to-red-800',
    benefits: [
      'LONG/LONG RAW → CLOB/BLOB and other compatibility fixes',
      'Optional JSON-relational duality views & native VECTOR type',
      'Deterministic SQL/PLSQL syntax validation',
      'JDBC driver version bump',
      'DB engine upgrade & data migration explicitly out of scope',
    ],
  },
  {
    id: 'tibco-ems-to-pubsub',
    title: 'TIBCO EMS → Google Cloud Pub/Sub',
    description:
      'Migrate TIBCO EMS queues/topics, producers, consumers, and message selectors to Google Cloud Pub/Sub — with delivery-semantics reconciliation for at-least-once delivery.',
    from: 'TIBCO EMS',
    to: 'Cloud Pub/Sub',
    fromBadge: 'bg-red-500/20 text-red-700 border-red-500/30',
    toBadge: 'bg-blue-500/20 text-blue-700 border-blue-500/30',
    gradient: 'from-red-500/10 via-transparent to-blue-500/10',
    iconBg: 'bg-gradient-to-br from-red-600 to-blue-600',
    benefits: [
      'Destination → topic/subscription mapping',
      'Message selector → Pub/Sub filter translation',
      'Idempotency guidance for at-least-once delivery',
      'JMS client → Google Cloud Pub/Sub client API',
      'Real mvn/gradle build or config validation, whichever applies',
    ],
  },
  {
    id: 'jsp-to-react-bff',
    title: 'JSP → React + BFF',
    description:
      'Architectural transformation, not a refactor — decouples a monolithic server-rendered JSP app into a React frontend and a Java 25 / Spring Boot 4 Backend-For-Frontend, packaged as a standalone JAR.',
    from: 'JSP (WAR)',
    to: 'React + BFF (JAR)',
    fromBadge: 'bg-orange-500/20 text-orange-700 border-orange-500/30',
    toBadge: 'bg-cyan-500/20 text-cyan-700 border-cyan-500/30',
    gradient: 'from-orange-500/10 via-transparent to-cyan-500/10',
    iconBg: 'bg-gradient-to-br from-orange-500 to-cyan-600',
    benefits: [
      'Extracts logic, then decides React vs BFF placement',
      'BFF API contract designed before any code is generated',
      'Standalone Spring Boot 4 JAR — no more WAR/external container',
      'Real mvn compile (backend) + npm build (frontend) validation',
      'Session/state semantics explicitly reconciled, not assumed',
    ],
  },
];
