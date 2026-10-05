export type PatternId =
  | 'java-8-to-25'
  /** JDK-only upgrade: JSP views and the WildFly deployment are frozen. No
   * strategy or toggles, so it goes straight to upload. */
  | 'java-8-to-11'
  | 'solr-4-to-9'
  | 'oracle-19c-to-23ai'
  | 'tibco-ems-to-pubsub'
  | 'jsp-to-react-bff'
  /** Reverse engineering only — maps the stacks in the repo and documents each
   * one. No plan, no generated code: the run ends at brd-review. */
  | 'stack-discovery'
  /** Not selectable. One leg of a stack-discovery fan-out (an RE skill with no
   * migration target), so it only ever arrives as a CompanionRecommendation. */
  | 'wildfly';

/** Patterns that produce a plan and generated code. `stack-discovery` stops at
 * the reverse-engineering document, so every plan/code affordance is hidden for
 * it — see MIGRATION_PATTERNS in App.tsx. */
export const RE_ONLY_PATTERNS: PatternId[] = ['stack-discovery'];

export type WorkflowStep =
  | 'upload'
  | 'dependency-graph'
  /** stack-discovery only: the dependency mapper working out what is in the repo. */
  | 'stack-mapping'
  | 'companion-selection'
  | 'preflight'
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
 * with the deterministic evidence that triggered the recommendation.
 *
 * Reused verbatim for stack-discovery's detected stacks: same shape, same
 * confirmation screen, same endpoint — from the reviewer's side it is the same
 * decision about which detected things to work on. */
/** stack-discovery: whether UI screenshots can be produced for this repository,
 * sent with companion-recommendations only when the repository has a UI. */
export interface ScreenshotsOffer {
  available: boolean;
  /** Whether the checkbox starts ticked (UI_SCREENSHOTS_DEFAULT). */
  default: boolean;
  /** The UI stacks the screens are rendered for; unticking all of them turns screenshots off. */
  stacks: string[];
  /** Why the option is unavailable, or a note about what will be produced. */
  reason: string;
}

/** stack-discovery: a document the reviewer can choose to generate. */
export type DiscoveryDocument = 'brd' | 'technical_spec' | 'test_inventory' | 'ui_screens';

export interface CompanionRecommendation {
  /** A PatternId for a companion migration; for stack-discovery, a stack id found
   * in the repository (`java`, `backbone`, `python`, or any id the mapper chose). */
  pattern: string;
  label: string;
  evidence: string[];
  /** stack-discovery only: server, database, search, messaging, web-tier,
   * frontend, service, application, language or other. */
  kind?: string;
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

/** One task of the current incremental stage (java-8-to-25 only) — the modifier runs once per task */
export interface TaskProgress {
  id: string;
  title: string;
  index: number;
  total: number;
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
  /** Total files in the result; >generatedFiles.length when the preview is capped. */
  generatedFilesTotal: number;
  /** Files the upload could not unpack (server ingestion limit). */
  filesTruncated: number;
  /** False when the server passes a deterministic inventory straight to the
   * planner: no reverse-engineering or analysis-review step in this run. */
  analysisReview: boolean;
  /** True when the run starts with the environment check (JDK, Maven, the
   * uploaded code built on the target JDK) — Java 8 -> 11. */
  preflight: boolean;
  /** The environment check's one-line result, shown for the rest of the run. */
  preflightSummary: string;
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
  /** Task the current stage's modifier is applying, when the plan has a task breakdown */
  currentTask: TaskProgress | null;
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
  /** stack-discovery: the UI screenshots option, when the repository has a UI */
  screenshotsOffer: ScreenshotsOffer | null;
  /** stack-discovery: the UI Screens document, when screenshots were chosen */
  uiScreens: string;
  error: string | null;
}

export interface SSEEvent {
  type: string;
  step?: WorkflowStep;
  content?: string;
  brd?: string;
  technical_spec?: string;
  test_inventory?: string;
  /** stack-discovery with screenshots chosen: the UI Screens document */
  ui_screens?: string;
  /** Sent with stack-discovery's companion-recommendations when the repository has a UI */
  screenshots?: ScreenshotsOffer;
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
  /** Stage count with stage-start/stage-complete. Also sent with code-ready, where
   * it is how many files the result really has — `files` there is a capped
   * browsable preview, while the ZIP download is always complete. */
  total?: number;
  phase?: number;
  phase_title?: string;
  title?: string;
  /** Sent with task-start / task-complete */
  task_id?: string;
  task_title?: string;
  task_index?: number;
  task_total?: number;
  /** Sent with companion-recommendations, and with stack-discovery's
   * companion-recommendations carrying the detected stacks */
  companions?: CompanionRecommendation[];
  /** Sent with stack-inventory-ready (stack-discovery): the reconciled stacks
   * the RE fan-out will actually run */
  stacks?: CompanionRecommendation[];
}
