import { Brain, FileText, GitBranch, Code2, TestTube2, CheckCircle2, XCircle, Wrench, Loader2 } from 'lucide-react';
import type { WorkflowStep, ValidationState } from '../types';

const STEP_CONFIG: Record<string, { icon: React.ReactNode; title: string; subtitle: string; color: string }> = {
  'reverse-engineering': {
    icon: <Brain size={28} />,
    title: 'Reverse Engineering',
    subtitle: 'AI is analysing your codebase — architecture, business logic, dependencies…',
    color: 'text-violet-400',
  },
  'brd-generation': {
    icon: <FileText size={28} />,
    title: 'Generating BRD',
    subtitle: 'Drafting the Business Requirements Document based on the analysis…',
    color: 'text-blue-400',
  },
  'plan-generation': {
    icon: <GitBranch size={28} />,
    title: 'Generating Migration Plan',
    subtitle: 'Building a step-by-step plan.md for your migration…',
    color: 'text-emerald-400',
  },
  'code-generation': {
    icon: <Code2 size={28} />,
    title: 'Generating Target Code',
    subtitle: 'Producing the fully migrated codebase…',
    color: 'text-amber-400',
  },
  'test-generation': {
    icon: <TestTube2 size={28} />,
    title: 'Generating Unit Tests',
    subtitle: 'Creating a test suite targeting >80% code coverage…',
    color: 'text-rose-400',
  },
};

// ── Validation status panel (shown during test-generation step) ───────────────

function ValidationPanel({ v }: { v: ValidationState }) {
  const rows: Array<{ label: string; status: 'done' | 'active' | 'pending' | 'error' }> = [];

  for (let i = 1; i <= v.maxAttempts; i++) {
    if (i < v.attemptsUsed) {
      // completed attempt
      rows.push({ label: `Attempt ${i}/${v.maxAttempts} — validated`, status: 'done' });
      if (i < v.attemptsUsed) {
        rows.push({ label: `Attempt ${i}/${v.maxAttempts} — applied fixes`, status: 'done' });
      }
    } else if (i === v.attemptsUsed) {
      if (v.fixingAttempt > 0) {
        rows.push({ label: `Attempt ${i}/${v.maxAttempts} — issues found, fixing…`, status: 'active' });
      } else if (v.passed === null) {
        rows.push({ label: `Attempt ${i}/${v.maxAttempts} — validating…`, status: 'active' });
      } else if (v.passed) {
        rows.push({ label: `Attempt ${i}/${v.maxAttempts} — passed ✓`, status: 'done' });
      } else {
        rows.push({ label: `Attempt ${i}/${v.maxAttempts} — issues found`, status: 'error' });
      }
    } else {
      rows.push({ label: `Attempt ${i}/${v.maxAttempts}`, status: 'pending' });
    }
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden mt-4">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800 bg-slate-950/50">
        <TestTube2 size={13} className="text-rose-400" />
        <span className="text-xs font-medium text-slate-400">Validation &amp; Auto-fix</span>
        <span className="ml-auto text-[10px] text-slate-600">
          up to {v.maxAttempts} attempt{v.maxAttempts !== 1 ? 's' : ''}
        </span>
      </div>
      <div className="p-4 space-y-2">
        {rows.map((row, i) => (
          <div key={i} className="flex items-center gap-2.5">
            {row.status === 'active' && <Loader2 size={13} className="text-indigo-400 animate-spin shrink-0" />}
            {row.status === 'done'   && <CheckCircle2 size={13} className="text-emerald-400 shrink-0" />}
            {row.status === 'error'  && <XCircle size={13} className="text-rose-400 shrink-0" />}
            {row.status === 'pending' && <div className="w-3 h-3 rounded-full border border-slate-700 shrink-0" />}
            <span className={`text-xs ${
              row.status === 'active'  ? 'text-indigo-300' :
              row.status === 'done'   ? 'text-slate-300' :
              row.status === 'error'  ? 'text-rose-300' : 'text-slate-600'
            }`}>{row.label}</span>
          </div>
        ))}

        {/* Issues list */}
        {v.issues.length > 0 && v.passed === false && (
          <div className="mt-3 pt-3 border-t border-slate-800">
            <p className="text-[10px] text-slate-500 mb-1.5 uppercase tracking-wide">Issues detected</p>
            <ul className="space-y-1">
              {v.issues.map((iss, i) => (
                <li key={i} className="flex items-start gap-1.5 text-xs text-slate-400">
                  <Wrench size={11} className="text-amber-400 mt-0.5 shrink-0" />
                  {iss}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

interface Props {
  step: WorkflowStep;
  streamingContent: string;
  progress: number;
  progressMessage: string;
  validation?: ValidationState | null;
}

export function ProcessingView({ step, streamingContent, progress, progressMessage, validation }: Props) {
  const config = STEP_CONFIG[step] ?? STEP_CONFIG['reverse-engineering'];

  return (
    <div className="max-w-4xl mx-auto px-6 py-12">
      {/* Status card */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 mb-6 text-center">
        <div className={`inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-slate-800 border border-slate-700 ${config.color} mb-5`}>
          {config.icon}
        </div>
        <h2 className="text-xl font-bold text-white mb-2">{config.title}</h2>
        <p className="text-slate-400 text-sm mb-6">{config.subtitle}</p>

        {/* Progress */}
        <div className="max-w-md mx-auto">
          <div className="flex items-center justify-between text-xs text-slate-500 mb-2">
            <span>{progressMessage || 'Processing…'}</span>
            <span>{progress}%</span>
          </div>
          <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all duration-500"
              style={{ width: `${Math.max(progress, 3)}%` }}
            />
          </div>
        </div>
      </div>

      {/* Validation panel (only during test-generation) */}
      {step === 'test-generation' && validation && (
        <ValidationPanel v={validation} />
      )}

      {/* Live streaming output */}
      {streamingContent && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden mt-4">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-950/50">
            <span className="text-xs font-medium text-slate-400">Live output</span>
            <span className="flex items-center gap-1.5 text-xs text-emerald-400">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Streaming
            </span>
          </div>
          <div className="p-4 max-h-96 overflow-y-auto font-mono text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">
            {streamingContent}
            <span className="inline-block w-1.5 h-3.5 bg-indigo-400 animate-pulse ml-0.5 align-middle" />
          </div>
        </div>
      )}
    </div>
  );
}
