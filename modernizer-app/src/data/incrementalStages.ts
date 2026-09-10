/**
 * The java-8-to-25 phased incremental strategy — mirrors INCREMENTAL_STAGES in
 * modernizer-backend/agents/java_8_to_25/agents.py (keep the two in sync).
 * JDK and Spring Boot steps interleave so every step lands on a supported
 * combination; Spring Boot steps only run when the Spring Boot upgrade is requested.
 */
export interface IncrementalStep {
  /** Stable id — matches IncrementalStage.idx in the backend */
  id: number;
  title: string;
  detail: string;
  springboot: boolean;
}

export interface IncrementalPhase {
  phase: number;
  title: string;
  steps: IncrementalStep[];
}

export const INCREMENTAL_PHASES: IncrementalPhase[] = [
  {
    phase: 1,
    title: 'Readiness',
    steps: [
      { id: 1, title: 'Modernize Build Systems (Maven/Gradle)', detail: 'pinned plugins, reproducible build — still Java 8', springboot: false },
      { id: 2, title: 'Automate Code Analysis (OpenRewrite)', detail: 'recipes to preview every later step', springboot: false },
    ],
  },
  {
    phase: 2,
    title: 'Java 17 Baseline',
    steps: [
      { id: 3, title: 'Java 8 → Java 17 LTS', detail: 'module system, deprecated API removal', springboot: false },
      { id: 4, title: 'Upgrade to Spring Boot 2.7 (WAR intact)', detail: 'on Java 17, javax.* kept', springboot: true },
    ],
  },
  {
    phase: 3,
    title: 'Java 25 Baseline',
    steps: [
      { id: 5, title: 'Upgrade to Spring Boot 3.x (Jakarta namespace transition)', detail: 'on Java 17, javax.* → jakarta.*', springboot: true },
      { id: 6, title: 'Java 17 → Java 25 LTS', detail: 'virtual threads, modern language features', springboot: false },
    ],
  },
  {
    phase: 4,
    title: 'Spring Boot 4 & Cloud Native',
    steps: [
      { id: 7, title: 'Upgrade to Spring Boot 4.x', detail: 'Spring Framework 7, Jakarta EE 11', springboot: true },
      { id: 8, title: 'Convert WAR → Executable JAR (Embedded Container)', detail: 'runs standalone with java -jar', springboot: true },
    ],
  },
];

export interface RunStep extends IncrementalStep {
  /** 1-based position in this run — what the stage-start / stage-complete events call `stage` */
  stage: number;
}

export interface RunPhase extends Omit<IncrementalPhase, 'steps'> {
  steps: RunStep[];
}

/** The phases and steps an actual run executes, numbered by position (same filtering as the backend). */
export function phasesForRun(springbootUpgrade: boolean): RunPhase[] {
  let position = 0;
  return INCREMENTAL_PHASES
    .map((p) => ({
      ...p,
      steps: p.steps
        .filter((s) => springbootUpgrade || !s.springboot)
        .map((s) => ({ ...s, stage: ++position })),
    }))
    .filter((p) => p.steps.length > 0);
}
