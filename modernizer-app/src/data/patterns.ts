import type { PatternConfig } from '../types';

export const PATTERNS: PatternConfig[] = [
  {
    id: 'java17-to-java25',
    title: 'Java 17 → Java 25',
    description:
      'Modernise your Java 17 codebase to Java 25 — adopting Virtual Threads, Pattern Matching, Value Types, and all LTS improvements.',
    from: 'Java 17',
    to: 'Java 25',
    fromBadge: 'bg-orange-500/20 text-orange-300 border-orange-500/30',
    toBadge: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
    gradient: 'from-orange-500/10 via-transparent to-blue-500/10',
    iconBg: 'bg-gradient-to-br from-orange-500 to-blue-600',
    benefits: [
      'Virtual Threads (Project Loom)',
      'Pattern matching & sealed classes',
      'Value types (Valhalla preview)',
      'String templates',
      'Improved GC performance',
    ],
  },
  {
    id: 'java-to-go',
    title: 'Java → Go',
    description:
      'Rewrite your Java services in idiomatic Go for cloud-native performance — low memory, fast startup, and native concurrency with goroutines.',
    from: 'Java',
    to: 'Go',
    fromBadge: 'bg-orange-500/20 text-orange-300 border-orange-500/30',
    toBadge: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
    gradient: 'from-orange-500/10 via-transparent to-cyan-500/10',
    iconBg: 'bg-gradient-to-br from-orange-500 to-cyan-500',
    benefits: [
      'Single binary deployment',
      'Goroutines & channels',
      'Sub-millisecond startup',
      'Minimal memory footprint',
      'Static type safety',
    ],
  },
  {
    id: 'java-to-quarkus',
    title: 'Java → Quarkus',
    description:
      'Migrate your Spring Boot app to Quarkus for Kubernetes-native architecture — native image compilation, live coding, and reactive-first design.',
    from: 'Spring Boot',
    to: 'Quarkus',
    fromBadge: 'bg-green-500/20 text-green-300 border-green-500/30',
    toBadge: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
    gradient: 'from-green-500/10 via-transparent to-purple-500/10',
    iconBg: 'bg-gradient-to-br from-green-500 to-purple-600',
    benefits: [
      'Native image via GraalVM',
      'Sub-100ms startup',
      '<50 MB memory (native)',
      'Reactive + imperative modes',
      'Dev Services (auto Testcontainers)',
    ],
  },
  {
    id: 'tibco-to-springboot',
    title: 'TIBCO BW → Spring Boot',
    description:
      'Migrate your TIBCO BusinessWorks integration processes to Java Spring Boot — eliminating proprietary licensing while preserving every integration flow.',
    from: 'TIBCO BW',
    to: 'Spring Boot',
    fromBadge: 'bg-red-500/20 text-red-300 border-red-500/30',
    toBadge: 'bg-green-500/20 text-green-300 border-green-500/30',
    gradient: 'from-red-500/10 via-transparent to-green-500/10',
    iconBg: 'bg-gradient-to-br from-red-600 to-green-600',
    benefits: [
      'Eliminate TIBCO licensing costs',
      'Process-by-process migration',
      'XSLT → MapStruct mappers',
      'JMS / HTTP / JDBC preserved',
      'Cloud-native & containerised',
    ],
  },
];
