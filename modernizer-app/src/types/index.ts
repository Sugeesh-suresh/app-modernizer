export type PatternId =
  | 'java-8-to-25'
  | 'solr-4-to-9'
  | 'oracle-19c-to-23ai'
  | 'tibco-ems-to-pubsub'
  | 'jsp-to-react-bff';

export type WorkflowStep =
  | 'upload'
  | 'dependency-graph'
  | 'companion-selection'
  | 'reverse-engineering'
  | 'brd-review'
  | 'plan-generation'
  | 'plan-review'
  | 'code-generation'
  | 'complete'
  | 'error';

/** Sub-step within code-generation */
export type CodeSubStep = 'generating' | 'validating' | 'fixing' | 'reviewing' | 'curating';

export type MigrationStrategy = 'bigbang' | 'incremental';

export interface JavaMigrationOptions {
  strategy: MigrationStrategy;
  junitUpgrade: boolean;
  springbootUpgrade: boolean;
}

/** A companion migration pattern auto-detected from repo dependencies (e.g.
 * an Oracle JDBC driver or SolrJ client found inside a java-8-to-25 repo),
 * with the deterministic evidence that triggered the recommendation. */
export interface CompanionRecommendation {
  pattern: PatternId;
  label: string;
  evidence: string[];
}

export interface PatternConfig {
  id: PatternId;
  title: string;
  description: string;
  from: string;
  to: string;
  fromBadge: string;
  toBadge: string;
  gradient: string;
  iconBg: string;
  benefits: string[];
}

export interface GeneratedFile {
  path: string;
  content: string;
  language: string;
}

export interface ChangedFile {
  path: string;
  status: 'added' | 'modified' | 'deleted';
  diff: string;
}

export interface ValidationResult {
  passed: boolean;
  errors: string[];
  summary: string;
  /** How many validate→fix iterations ran before this result */
  iterations: number;
}

/** One completed stage of the java-8-to-25 phased incremental strategy (see data/incrementalStages.ts) */
export interface StageResult extends ValidationResult {
  stage: number;
  phase: number;
  phaseTitle: string;
  title: string;
}

export interface WorkflowState {
  sessionId: string | null;
  pattern: PatternId | null;
  javaOptions: JavaMigrationOptions | null;
  step: WorkflowStep;
  brd: string;
  technicalSpec: string;
  testInventory: string;
  plan: string;
  generatedFiles: GeneratedFile[];
  changedFiles: ChangedFile[];
  streamingContent: string;
  /** Separate stream for validate-agent output */
  validationContent: string;
  progress: number;
  progressMessage: string;
  /** Active sub-step during code-generation */
  codeSubStep: CodeSubStep;
  /** Current validate/fix iteration (1-based; 0 = not yet started) */
  validationIteration: number;
  /** Final validation result, set when validation-complete fires (bigbang / non-Java patterns) */
  validationResult: ValidationResult | null;
  /** Current incremental stage (1-8), 0 = not yet started (java-8-to-25 incremental only) */
  currentStage: number;
  /** How many stages this incremental run executes (4, or 8 with the Spring Boot upgrade), 0 = unknown yet */
  stageTotal: number;
  /** Completed stage results so far, in order (java-8-to-25 incremental only) */
  stageResults: StageResult[];
  /** code_reviewer_agent's independent findings, set when code-review-ready fires (runs after the build loop, before the reporter) */
  codeReview: string;
  /** reporter_agent's closing summary, set when report-ready fires */
  finalReport: string;
  /** skill_curator_agent's summary of what it refined in the skill library (or that it made no changes), set when skill-curator-ready fires — the last thing to happen in the pipeline */
  skillCuratorSummary: string;
  /** True while a refine-brd/refine-plan request is in flight and streaming back */
  refining: boolean;
  /** Auto-detected companion migrations, set when companion-recommendations fires (java-8-to-25 only) */
  companionRecommendations: CompanionRecommendation[];
  error: string | null;
}

export interface SSEEvent {
  type: string;
  step?: WorkflowStep;
  content?: string;
  brd?: string;
  technical_spec?: string;
  test_inventory?: string;
  progress?: number;
  message?: string;
  files?: GeneratedFile[];
  changed_files?: ChangedFile[];
  session_id?: string;
  status?: string;
  /** Validate/fix loop iteration (1-based), sent with validation-agent-start and fix-agent-start */
  iteration?: number;
  /** Sent with validation-complete / stage-complete */
  passed?: boolean;
  errors?: string[];
  summary?: string;
  iterations?: number;
  /** java-8-to-25 incremental strategy: sent with stage-start / stage-complete */
  stage?: number;
  total?: number;
  phase?: number;
  phase_title?: string;
  title?: string;
  /** Sent with companion-recommendations */
  companions?: CompanionRecommendation[];
}
