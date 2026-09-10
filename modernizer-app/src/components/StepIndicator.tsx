import { Check, Loader2, Clock } from 'lucide-react';
import type { PatternId, WorkflowStep } from '../types';

const ALL_STEPS: { id: WorkflowStep; label: string }[] = [
  { id: 'upload', label: 'Upload' },
  { id: 'dependency-graph', label: 'Dependency Graph' },
  { id: 'companion-selection', label: 'Additional Migrations' },
  { id: 'reverse-engineering', label: 'Reverse Engineer' },
  { id: 'brd-review', label: 'Analysis Review' },
  { id: 'plan-generation', label: 'Plan' },
  { id: 'plan-review', label: 'Plan Review' },
  { id: 'code-generation', label: 'Migrate & Build' },
  { id: 'complete', label: 'Complete' },
];

interface Props {
  currentStep: WorkflowStep;
  pattern: PatternId | null;
  progress: number;
  progressMessage: string;
  /** Steps to omit from the rail — e.g. 'companion-selection' when no
   * companion migrations were recommended for this session, so the rail
   * doesn't show a step that will never actually fire. */
  skipSteps?: WorkflowStep[];
}

export function StepIndicator({ currentStep, progress, progressMessage, skipSteps = [] }: Props) {
  const STEPS = ALL_STEPS.filter((s) => !skipSteps.includes(s.id));
  const STEP_ORDER = STEPS.map((s) => s.id);
  const currentIndex = STEP_ORDER.indexOf(currentStep);

  return (
    <div className="glass-strong border-b border-slate-900/10">
      <div className="max-w-7xl mx-auto px-6 py-5">
        {/* Steps */}
        <div className="flex items-center gap-0">
          {STEPS.map((step, i) => {
            const isComplete = i < currentIndex || (i === currentIndex && step.id === 'complete');
            const isCurrent = i === currentIndex && step.id !== 'complete';
            const isPending = i > currentIndex;

            return (
              <div key={step.id} className="flex items-center gap-0 flex-1 last:flex-none">
                {/* Connector line before */}
                {i > 0 && (
                  <div className={`flex-1 h-px ${isComplete ? 'bg-red-500' : 'bg-slate-900/10'} transition-colors duration-500`} />
                )}

                {/* Step circle */}
                <div className="flex flex-col items-center">
                  <div
                    className={`
                      w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold transition-all duration-300 shrink-0
                      ${isComplete ? 'bg-red-600 text-white shadow-md shadow-red-500/40' : ''}
                      ${isCurrent ? 'bg-red-500/20 border-2 border-red-500 text-red-700 pulse-glow' : ''}
                      ${isPending ? 'bg-slate-900/5 border border-slate-900/10 text-slate-600' : ''}
                    `}
                  >
                    {isComplete ? (
                      <Check size={14} />
                    ) : isCurrent ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Clock size={12} />
                    )}
                  </div>
                  <span className={`text-[10px] mt-1.5 font-medium whitespace-nowrap ${
                    isCurrent ? 'text-red-700' : isComplete ? 'text-slate-700' : 'text-slate-600'
                  }`}>
                    {step.label}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Progress bar */}
        {currentStep !== 'upload' && currentStep !== 'dependency-graph' && currentStep !== 'companion-selection' && currentStep !== 'complete' && currentStep !== 'brd-review' && currentStep !== 'plan-review' && currentStep !== 'error' && (
          <div className="mt-4">
            <div className="flex items-center justify-between text-xs text-slate-500 mb-1.5">
              <span>{progressMessage || 'Processing…'}</span>
              <span>{progress}%</span>
            </div>
            <div className="h-1.5 bg-slate-900/5 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-red-500 to-red-700 rounded-full transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
