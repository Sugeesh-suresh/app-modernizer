import type { PatternId, JavaMigrationOptions } from './types';

const BASE = 'http://localhost:8000';

export async function uploadRepository(
  pattern: PatternId,
  file: File,
  options?: JavaMigrationOptions | null,
): Promise<{ session_id: string; files_found: number }> {
  const form = new FormData();
  form.append('pattern', pattern);
  form.append('file', file);
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
