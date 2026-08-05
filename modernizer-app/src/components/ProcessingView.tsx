import { Brain, FileText, GitBranch, Code2, ShieldCheck, Wrench, CheckCircle2, XCircle } from 'lucide-react';
import type { PatternId, WorkflowStep, CodeSubStep, ValidationResult } from '../types';

const STEP_CONFIG: Record<string, { icon: React.ReactNode; title: string; subtitle: string; color: string }> = {
  'reverse-engineering': {
    icon: <Brain size={28} />,
    title: 'Reverse Engineering',
    subtitle: 'AI is analysing your codebase — architecture, business logic, dependencies…',
    color: 'text-violet-600',
  },
  'brd-generation': {
    icon: <FileText size={28} />,
    title: 'Generating BRD',
    subtitle: 'Drafting the Business Requirements Document based on the analysis…',
    color: 'text-blue-600',
  },
  'plan-generation': {
    icon: <GitBranch size={28} />,
    title: 'Generating Migration Plan',
    subtitle: 'Building a step-by-step plan.md for your migration…',
    color: 'text-emerald-600',
  },
  'code-generation': {
    icon: <Code2 size={28} />,
    title: 'Generating Target Code',
    subtitle: 'Producing the fully migrated codebase…',
    color: 'text-amber-600',
  },
};

const MAX_ITERATIONS = 4;

interface Props {
  step: WorkflowStep;
  pattern: PatternId | null;
  streamingContent: string;
  validationContent: string;
  progress: number;
  progressMessage: string;
  codeSubStep: CodeSubStep;
  validationIteration: number;
  validationResult: ValidationResult | null;
}

export function ProcessingView({
  step,
  pattern,
  streamingContent,
  validationContent,
  progress,
  progressMessage,
  codeSubStep,
  validationIteration,
  validationResult,
}: Props) {
  const config = STEP_CONFIG[step] ?? STEP_CONFIG['reverse-engineering'];
  const isCodeStep = step === 'code-generation';
  const isQuarkus = pattern === 'java-to-quarkus';
  const showValidationPanel = isCodeStep && isQuarkus;

  // Which stream to show: validation output during validating, code/fix output otherwise
  const activeStream = isCodeStep && codeSubStep === 'validating' ? validationContent : streamingContent;

  return (
    <div className="max-w-4xl mx-auto px-6 py-12">
      {/* Status card */}
      <div className="glass rounded-2xl p-8 mb-6 text-center">
        <div className={`inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-slate-900/5 border border-slate-900/10 ${config.color} mb-5`}>
          {config.icon}
        </div>
        <h2 className="text-xl font-bold text-slate-900 mb-2">{config.title}</h2>
        <p className="text-slate-600 text-sm mb-6">{config.subtitle}</p>

        {/* Sub-step badge — Quarkus code generation only */}
        {showValidationPanel && codeSubStep !== 'generating' && (
          <div className={`inline-flex items-center gap-2 text-xs font-medium mb-4 px-3 py-1.5 rounded-full border ${
            codeSubStep === 'validating'
              ? 'bg-blue-500/10 text-blue-600 border-blue-500/20'
              : 'bg-rose-500/10 text-rose-600 border-rose-500/20'
          }`}>
            {codeSubStep === 'validating' ? <ShieldCheck size={13} /> : <Wrench size={13} />}
            {codeSubStep === 'validating' ? 'Validating for compilation errors…' : 'Fixing compilation errors…'}
          </div>
        )}

        {/* Progress bar */}
        <div className="max-w-md mx-auto">
          <div className="flex items-center justify-between text-xs text-slate-500 mb-2">
            <span>{progressMessage || 'Processing…'}</span>
            <span>{progress}%</span>
          </div>
          <div className="h-2 bg-slate-900/5 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-red-500 to-red-700 rounded-full transition-all duration-500"
              style={{ width: `${Math.max(progress, 3)}%` }}
            />
          </div>
        </div>
      </div>

      {/* Quarkus validation loop panel */}
      {showValidationPanel && (
        <div className="glass rounded-2xl overflow-hidden mb-4">
          <div className="px-5 py-3 border-b border-slate-900/10 glass-inset flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
              Quarkus Build Loop — LoopAgent (max {MAX_ITERATIONS} iterations)
            </span>
            {/* Iteration dots */}
            {validationIteration > 0 && (
              <div className="flex items-center gap-1.5">
                {Array.from({ length: MAX_ITERATIONS }).map((_, i) => {
                  const n = i + 1;
                  const isDone = n < validationIteration;
                  const isCurrent = n === validationIteration;
                  const dotColor = isDone
                    ? 'bg-rose-500'           // past iterations → had errors, fix was applied
                    : isCurrent && validationResult
                    ? validationResult.passed ? 'bg-emerald-400' : 'bg-rose-500'
                    : isCurrent
                    ? codeSubStep === 'validating' ? 'bg-blue-400 animate-pulse'
                      : codeSubStep === 'fixing'   ? 'bg-rose-400 animate-pulse'
                      : 'bg-amber-400 animate-pulse'
                    : 'bg-slate-300';
                  return (
                    <div
                      key={i}
                      title={`Iteration ${n}`}
                      className={`w-2.5 h-2.5 rounded-full transition-all duration-300 ${dotColor}`}
                    />
                  );
                })}
                <span className="text-xs text-slate-500 ml-1 font-mono">
                  {validationIteration}/{MAX_ITERATIONS}
                </span>
              </div>
            )}
          </div>

          <div className="p-5 space-y-3">
            {/* Agent pipeline diagram */}
            <div className="flex items-center gap-2 flex-wrap">
              {[
                { key: 'generating', icon: <Code2 size={13} />, label: 'Code Agent', color: 'amber' },
                { label: '→', isArrow: true },
                { key: 'validating', icon: <ShieldCheck size={13} />, label: 'Validate Agent', color: 'blue' },
                { label: '↺', isArrow: true },
                { key: 'fixing', icon: <Wrench size={13} />, label: 'Fix Agent', color: 'rose' },
              ].map((item, i) => {
                if ((item as { isArrow?: boolean }).isArrow) {
                  return <span key={i} className="text-slate-500 text-sm font-mono">{item.label}</span>;
                }
                const isActive = codeSubStep === item.key;
                return (
                  <div
                    key={i}
                    className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border transition-all ${
                      isActive
                        ? item.color === 'amber' ? 'bg-amber-500/20 text-amber-700 border-amber-500/40'
                          : item.color === 'blue'  ? 'bg-blue-500/20 text-blue-700 border-blue-500/40'
                          : 'bg-rose-500/20 text-rose-700 border-rose-500/40'
                        : 'bg-slate-900/5 text-slate-500 border-slate-900/10'
                    }`}
                  >
                    {item.icon}
                    {item.label}
                    {isActive && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
                  </div>
                );
              })}
            </div>

            {/* In-progress context banners */}
            {codeSubStep === 'validating' && validationIteration > 0 && (
              <div className="flex items-center gap-2 text-xs px-3 py-2 rounded-lg bg-blue-500/10 text-blue-700 border border-blue-500/20">
                <ShieldCheck size={13} className="shrink-0" />
                Running `mvn compile` check — iteration {validationIteration} of {MAX_ITERATIONS}…
              </div>
            )}
            {codeSubStep === 'fixing' && validationIteration > 0 && (
              <div className="flex items-center gap-2 text-xs px-3 py-2 rounded-lg bg-rose-500/10 text-rose-700 border border-rose-500/20">
                <Wrench size={13} className="shrink-0" />
                Applying fixes and re-outputting full codebase — iteration {validationIteration} of {MAX_ITERATIONS}…
              </div>
            )}

            {/* Final validation result */}
            {validationResult && (
              <div className={`flex items-start gap-2 text-xs px-3 py-2 rounded-lg border ${
                validationResult.passed
                  ? 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20'
                  : 'bg-amber-500/10 text-amber-600 border-amber-500/20'
              }`}>
                {validationResult.passed
                  ? <CheckCircle2 size={13} className="shrink-0 mt-0.5" />
                  : <XCircle size={13} className="shrink-0 mt-0.5" />
                }
                <span>
                  {validationResult.passed
                    ? `Build clean after ${validationResult.iterations} iteration(s) — ${validationResult.summary}`
                    : `${validationResult.errors.length} issue(s) remain after ${validationResult.iterations} iteration(s) — ${validationResult.summary}`
                  }
                </span>
              </div>
            )}

            {/* Remaining error list when loop exhausted */}
            {validationResult && !validationResult.passed && validationResult.errors.length > 0 && (
              <div className="glass-inset border border-slate-900/10 rounded-lg px-3 py-2 max-h-28 overflow-y-auto space-y-1">
                {validationResult.errors.map((err, i) => (
                  <p key={i} className="text-xs text-rose-700 font-mono leading-relaxed">• {err}</p>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Live streaming output */}
      {activeStream && (
        <div className="glass rounded-2xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-900/10 glass-inset">
            <span className="text-xs font-medium text-slate-600">
              {isCodeStep && codeSubStep === 'validating' ? 'Validation output' : 'Live output'}
            </span>
            <span className="flex items-center gap-1.5 text-xs text-emerald-600">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Streaming
            </span>
          </div>
          <div className="p-4 max-h-96 overflow-y-auto font-mono text-xs text-slate-700 leading-relaxed whitespace-pre-wrap">
            {activeStream}
            <span className="inline-block w-1.5 h-3.5 bg-red-400 animate-pulse ml-0.5 align-middle" />
          </div>
        </div>
      )}
    </div>
  );
}
