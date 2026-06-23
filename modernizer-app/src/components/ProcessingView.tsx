import { Brain, FileText, GitBranch, Code2 } from 'lucide-react';
import type { WorkflowStep } from '../types';

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
};

interface Props {
  step: WorkflowStep;
  streamingContent: string;
  progress: number;
  progressMessage: string;
}

export function ProcessingView({ step, streamingContent, progress, progressMessage }: Props) {
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

      {/* Live streaming output */}
      {streamingContent && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
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
