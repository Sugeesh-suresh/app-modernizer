export type PatternId = 'java17-to-java25' | 'java-to-go' | 'java-to-quarkus' | 'tibco-to-springboot';

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

export interface WorkflowState {
  sessionId: string | null;
  pattern: PatternId | null;
  step: WorkflowStep;
  brd: string;
  technicalSpec: string;
  plan: string;
  generatedFiles: GeneratedFile[];
  streamingContent: string;
  progress: number;
  progressMessage: string;
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
}
