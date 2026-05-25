export type PatternId = 'java17-to-java25' | 'java-to-go' | 'java-to-quarkus' | 'tibco-to-springboot';

export type WorkflowStep =
  | 'upload'
  | 'reverse-engineering'
  | 'brd-generation'
  | 'brd-review'
  | 'plan-generation'
  | 'plan-review'
  | 'code-generation'
  | 'test-generation'
  | 'complete'
  | 'error';

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

export interface ValidationState {
  attempt: number;
  maxAttempts: number;
  /** null = not yet run, true = passed, false = issues found */
  passed: boolean | null;
  issues: string[];
  summary: string;
  attemptsUsed: number;
  fixingAttempt: number;  // > 0 while a fix is in flight
}

export interface WorkflowState {
  sessionId: string | null;
  pattern: PatternId | null;
  step: WorkflowStep;
  brd: string;
  plan: string;
  generatedFiles: GeneratedFile[];
  testFiles: GeneratedFile[];
  streamingContent: string;
  progress: number;
  progressMessage: string;
  error: string | null;
  validation: ValidationState | null;
}

export interface SSEEvent {
  type: string;
  step?: WorkflowStep;
  content?: string;
  progress?: number;
  message?: string;
  files?: GeneratedFile[];
  source_files?: GeneratedFile[];
  test_files?: GeneratedFile[];
  session_id?: string;
  status?: string;
  // validation / fix events
  passed?: boolean;
  attempt?: number;
  max_retries?: number;
  issues?: string[];
  summary?: string;
  attempts_used?: number;
  final_issues?: string[];
}
