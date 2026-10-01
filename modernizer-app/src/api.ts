import type { PatternId, JavaMigrationOptions } from './types';

const BASE = 'http://localhost:8000';

/** Which patterns show their analysis for review before planning, as this
 * server is configured (MIGRATION_ANALYSIS / JAVA11_ANALYSIS). */
export async function fetchAnalysisReview(): Promise<Partial<Record<PatternId, boolean>>> {
  const res = await fetch(`${BASE}/api/patterns/analysis-review`);
  if (!res.ok) throw new Error('Failed to load analysis settings');
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
  if (!res.ok) throw new Error('Failed to confirm BRD');
}

export async function selectCompanions(sessionId: string, selected: PatternId[]): Promise<void> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/select-companions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ selected }),
  });
  if (!res.ok) throw new Error('Failed to confirm companion migrations');
}

export async function refineBrd(sessionId: string, feedback: string): Promise<void> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/refine-brd`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback }),
  });
  if (!res.ok) throw new Error('Failed to refine BRD');
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
  if (!res.ok) throw new Error('Failed to confirm Plan');
}

export async function refinePlan(sessionId: string, feedback: string): Promise<void> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/refine-plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback }),
  });
  if (!res.ok) throw new Error('Failed to refine plan');
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
  if (!res.ok) throw new Error('Failed to upload context files');
  return res.json();
}

export const brdDownloadUrl = (sessionId: string) =>
  `${BASE}/api/sessions/${sessionId}/download/brd`;

/** The whole reverse-engineering document (BRD + Technical Specification + Test
 * Inventory) as one file, rather than brdDownloadUrl's BRD slice. For a
 * stack-discovery run this is the deliverable. */
export const reverseEngineeringDownloadUrl = (sessionId: string) =>
  `${BASE}/api/sessions/${sessionId}/download/reverse-engineering`;

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
