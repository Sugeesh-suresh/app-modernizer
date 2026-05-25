import { Check, Loader2, Clock } from 'lucide-react';
import type { WorkflowStep } from '../types';

const STEPS: { id: WorkflowStep; label: string }[] = [
  { id: 'upload', label: 'Upload' },
  { id: 'reverse-engineering', label: 'Reverse Engineer' },
  { id: 'brd-review', label: 'BRD Review' },
  { id: 'plan-generation', label: 'Plan' },
  { id: 'plan-review', label: 'Plan Review' },
  { id: 'code-generation', label: 'Generate Code' },
  { id: 'test-generation', label: 'Generate Tests' },
  { id: 'complete', label: 'Complete' },
];

const STEP_ORDER = STEPS.map((s) => s.id);

function getStepIndex(step: WorkflowStep): number {
  // Treat brd-generation same as brd-review for progress
  if (step === 'brd-generation') return STEP_ORDER.indexOf('brd-review');
  return STEP_ORDER.indexOf(step);
}

interface Props {
  currentStep: WorkflowStep;
  progress: number;
  progressMessage: string;
}

export function StepIndicator({ currentStep, progress, progressMessage }: Props) {
  const currentIndex = getStepIndex(currentStep);

  return (
    <div className="border-b border-slate-800 bg-slate-950/60 backdrop-blur">
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
                  <div className={`flex-1 h-px ${isComplete ? 'bg-indigo-500' : 'bg-slate-700'} transition-colors duration-500`} />
                )}

                {/* Step circle */}
                <div className="flex flex-col items-center">
                  <div
                    className={`
                      w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold transition-all duration-300 shrink-0
                      ${isComplete ? 'bg-indigo-600 text-white shadow-md shadow-indigo-500/40' : ''}
                      ${isCurrent ? 'bg-indigo-500/20 border-2 border-indigo-500 text-indigo-300 pulse-glow' : ''}
                      ${isPending ? 'bg-slate-800 border border-slate-700 text-slate-600' : ''}
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
                    isCurrent ? 'text-indigo-300' : isComplete ? 'text-slate-300' : 'text-slate-600'
                  }`}>
                    {step.label}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Progress bar */}
        {currentStep !== 'upload' && currentStep !== 'complete' && currentStep !== 'brd-review' && currentStep !== 'plan-review' && currentStep !== 'error' && (
          <div className="mt-4">
            <div className="flex items-center justify-between text-xs text-slate-500 mb-1.5">
              <span>{progressMessage || 'Processing…'}</span>
              <span>{progress}%</span>
            </div>
            <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
