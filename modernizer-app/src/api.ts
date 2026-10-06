import type { DiscoveryDocument, PatternId, JavaMigrationOptions } from './types';

const BASE = 'http://localhost:8000';

/** The server's own explanation (FastAPI `detail`) when it gives one — e.g. why a
 * refine was refused or which model error stopped it — else `fallback`. */
async function apiError(res: Response, fallback: string): Promise<Error> {
  const body = await res.json().catch(() => null);
  const detail = body && typeof body.detail === 'string' ? body.detail : '';
  return new Error(detail ? `${fallback}: ${detail}` : fallback);
}

/** Which patterns show their analysis for review before planning, as this
 * server is configured (MIGRATION_ANALYSIS / JAVA11_ANALYSIS). */
export async function fetchAnalysisReview(): Promise<Partial<Record<PatternId, boolean>>> {
  const res = await fetch(`${BASE}/api/patterns/analysis-review`);
  if (!res.ok) throw await apiError(res, 'Failed to load analysis settings');
  return res.json();
}

export async function uploadRepository(
  pattern: PatternId,
  file: File,
  options?: JavaMigrationOptions | null,
  uxFiles: File[] = [],
  contextFiles: File[] = [],
): Promise<{
  session_id: string;
  files_found: number;
  /** Files that exceeded the server's ingestion limit and were NOT unpacked.
   * Non-zero means every result from this session covers only part of the repo. */
  files_truncated?: number;
  ux_designs: number;
  /** False when the analysis is a deterministic inventory passed straight to
   * the planner: the run has no reverse-engineering or analysis-review step. */
  analysis_review?: boolean;
  context_files?: number;
  /** True when the run starts with the environment check (Java 8 -> 11). */
  preflight?: boolean;
}> {
  const form = new FormData();
  form.append('pattern', pattern);
  form.append('file', file);
  // Optional UX designs — the backend only accepts them for the JSP → React pattern.
  for (const design of uxFiles) form.append('ux_files', design);
  // Optional Swagger / OpenAPI / design docs for the planner.
  for (const doc of contextFiles) form.append('context_files', doc);
  if (options) {
    form.append('migration_strategy', options.strategy);
    form.append('junit_upgrade', String(options.junitUpgrade));
    form.append('springboot_upgrade', String(options.springbootUpgrade));
  }

  const res = await fetch(`${BASE}/api/upload`, { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? 'Upload failed');
  }
  return res.json();
}

export async function confirmBrd(
  sessionId: string,
  brdContent: string,
  techSpecContent: string,
  feedback?: string,
): Promise<void> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/confirm-brd`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      content: brdContent,
      technical_spec_content: techSpecContent,
      feedback: feedback ?? null,
    }),
  });
  if (!res.ok) throw await apiError(res, 'Failed to confirm BRD');
}

/** `documents`: stack-discovery's chosen documents; omitted for a migration's companions. */
export async function selectCompanions(
  sessionId: string, selected: string[], documents?: DiscoveryDocument[],
): Promise<void> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/select-companions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(documents
      ? { selected, documents, screenshots: documents.includes('ui_screens') }
      : { selected }),
  });
  if (!res.ok) throw await apiError(res, 'Failed to confirm companion migrations');
}

export async function refineBrd(
  sessionId: string, feedback: string, target?: 'brd' | 'technical_spec',
): Promise<void> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/refine-brd`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback, target }),
  });
  if (!res.ok) throw await apiError(res, 'Failed to refine BRD');
}

export async function confirmPlan(
  sessionId: string,
  content: string,
  feedback?: string,
): Promise<void> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/confirm-plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, feedback: feedback ?? null }),
  });
  if (!res.ok) throw await apiError(res, 'Failed to confirm Plan');
}

export async function refinePlan(sessionId: string, feedback: string): Promise<void> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/refine-plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback }),
  });
  if (!res.ok) throw await apiError(res, 'Failed to refine plan');
}

export async function uploadContextFiles(
  sessionId: string,
  files: File[],
): Promise<{ files_added: number; filenames: string[] }> {
  const form = new FormData();
  files.forEach((f) => form.append('files', f));
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/context-files`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) throw await apiError(res, 'Failed to upload context files');
  return res.json();
}

/** Markdown, or Word (.docx) converted from the same Markdown. */
export type DocFormat = 'md' | 'docx';

export const brdDownloadUrl = (sessionId: string, format: DocFormat = 'md') =>
  `${BASE}/api/sessions/${sessionId}/download/brd?format=${format}`;

/** The technical documentation: Technical Specification + Existing Test Inventory. */
export const technicalSpecDownloadUrl = (sessionId: string, format: DocFormat | 'zip' = 'md') =>
  `${BASE}/api/sessions/${sessionId}/download/technical-spec?format=${format}`;

/** The whole reverse-engineering document (BRD + Technical Specification + Test
 * Inventory) as one file, rather than brdDownloadUrl's BRD slice. For a
 * stack-discovery run this is the deliverable. */
export const reverseEngineeringDownloadUrl = (sessionId: string, format: DocFormat = 'md') =>
  `${BASE}/api/sessions/${sessionId}/download/reverse-engineering?format=${format}`;

/** stack-discovery: the complete business-rules ledger (every rule and every
 * candidate with its classification) as CSV — the document lists up to a limit. */
export const businessRulesDownloadUrl = (sessionId: string) =>
  `${BASE}/api/sessions/${sessionId}/download/business-rules`;

/** stack-discovery: every decision point found in the code and how it was accounted for, as CSV. */
export const decisionPointsDownloadUrl = (sessionId: string) =>
  `${BASE}/api/sessions/${sessionId}/download/decision-points`;

/** stack-discovery: the UI Screens document — Markdown and images as one zip, or Word with the images inside. */
export const uiScreensDownloadUrl = (sessionId: string, format: 'zip' | 'docx' = 'docx') =>
  `${BASE}/api/sessions/${sessionId}/download/ui-screens?format=${format}`;

/** One rendered screen of the UI Screens document (`screens/SCR-0001.png` in its Markdown). */
export const uiScreenUrl = (sessionId: string, name: string) =>
  `${BASE}/api/sessions/${sessionId}/screens/${encodeURIComponent(name)}`;

/** An architecture diagram (HLD-1.png, LLD-2.png …) the pipeline drew for this session's specification. */
export const diagramUrl = (sessionId: string, name: string) =>
  `${BASE}/api/sessions/${sessionId}/diagrams/${encodeURIComponent(name)}`;

export const planDownloadUrl = (sessionId: string) =>
  `${BASE}/api/sessions/${sessionId}/download/plan`;

export const codeZipDownloadUrl = (sessionId: string) =>
  `${BASE}/api/sessions/${sessionId}/download/code`;

export function createSSEConnection(
  sessionId: string,
  onEvent: (e: MessageEvent) => void,
  onError: (e: Event) => void,
): EventSource {
  const es = new EventSource(`${BASE}/api/stream/${sessionId}`);
  es.onmessage = onEvent;
  es.onerror = onError;
  return es;
}
