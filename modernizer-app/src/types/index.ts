export type PatternId =
  | 'java11-to-java25'
  | 'java17-to-java25'
  | 'java-to-go'
  | 'java-to-quarkus'
  | 'tibco-to-springboot'
  | 'dotnet4-to-dotnet8'
  | 'dotnet8-to-dotnet9'
  | 'dotnet9-to-dotnet10'
  | 'dotnet10-to-dotnet11'
  | 'dotnet-to-java';

export type WorkflowStep =
  | 'upload'
  | 'reverse-engineering'
  | 'brd-generation'
  | 'brd-review'
  | 'plan-generation'
  | 'plan-review'
  | 'code-generation'
  | 'complete'
  | 'error';

/** Sub-step within code-generation (only active for Quarkus which has a validate/fix loop) */
export type CodeSubStep = 'generating' | 'validating' | 'fixing';

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

export interface ValidationResult {
  passed: boolean;
  errors: string[];
  summary: string;
  /** How many validate→fix iterations ran before this result */
  iterations: number;
}

export interface WorkflowState {
  sessionId: string | null;
  pattern: PatternId | null;
  step: WorkflowStep;
  brd: string;
  technicalSpec: string;
  plan: string;
  generatedFiles: GeneratedFile[];
  streamingContent: string;
  /** Separate stream for validate-agent output */
  validationContent: string;
  progress: number;
  progressMessage: string;
  /** Active sub-step during code-generation (Quarkus only) */
  codeSubStep: CodeSubStep;
  /** Current validate/fix iteration (1-based; 0 = not yet started) */
  validationIteration: number;
  /** Final validation result, set when validation-complete fires */
  validationResult: ValidationResult | null;
  /** reporter_agent's closing summary (java11-to-java25 only), set when report-ready fires */
  finalReport: string;
  error: string | null;
}

export interface SSEEvent {
  type: string;
  step?: WorkflowStep;
  content?: string;
  brd?: string;
  technical_spec?: string;
  progress?: number;
  message?: string;
  files?: GeneratedFile[];
  session_id?: string;
  status?: string;
  /** Validate/fix loop iteration (1-based), sent with validation-agent-start and fix-agent-start */
  iteration?: number;
  /** Sent with validation-complete */
  passed?: boolean;
  errors?: string[];
  summary?: string;
  iterations?: number;
}
