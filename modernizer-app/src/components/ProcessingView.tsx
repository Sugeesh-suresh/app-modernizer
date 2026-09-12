import { Brain, FileText, GitBranch, Code2, ShieldCheck, Wrench, CheckCircle2, Network, Search, Sparkles, Circle, Loader2 } from 'lucide-react';
import type { PatternId, WorkflowStep, CodeSubStep, ValidationResult, StageResult, TaskProgress } from '../types';
import { phasesForRun } from '../data/incrementalStages';

const SUB_STEP_BADGE: Partial<Record<CodeSubStep, { icon: React.ReactNode; label: string; color: string }>> = {
  validating: { icon: <ShieldCheck size={13} />, label: 'Validating…', color: 'bg-blue-500/10 text-blue-600 border-blue-500/20' },
  fixing: { icon: <Wrench size={13} />, label: 'Fixing issues…', color: 'bg-rose-500/10 text-rose-600 border-rose-500/20' },
  reviewing: { icon: <Search size={13} />, label: 'Independent code review…', color: 'bg-cyan-500/10 text-cyan-600 border-cyan-500/20' },
  curating: { icon: <Sparkles size={13} />, label: 'Curating the skill library…', color: 'bg-violet-500/10 text-violet-600 border-violet-500/20' },
};

const STEP_CONFIG: Record<string, { icon: React.ReactNode; title: string; subtitle: string; color: string }> = {
  'dependency-graph': {
    icon: <Network size={28} />,
    title: 'Building Dependency Graph',
    subtitle: 'Deterministically scanning the repository to sequence the migration into groups…',
    color: 'text-cyan-600',
  },
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
    title: 'Migration In Progress',
    subtitle: 'Applying the plan to your repository and validating the build…',
    color: 'text-amber-600',
  },
};

const MAX_ITERATIONS = 4;

/** Shown once the build/compile loop has finished — regardless of any errors it left behind. */
function MigrationCompleteBanner() {
  return (
    <div className="flex items-center gap-2 text-sm font-medium px-3 py-2.5 rounded-lg border bg-emerald-500/10 text-emerald-700 border-emerald-500/20">
      <CheckCircle2 size={15} className="shrink-0" />
      Migration is complete
    </div>
  );
}

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
  currentStage: number;
  stageTotal: number;
  stageResults: StageResult[];
  /** Task the current step's modifier is applying, when the plan has a task breakdown */
  currentTask: TaskProgress | null;
  /** Whether the Spring Boot steps are part of this incremental run */
  springbootUpgrade: boolean;
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
  currentStage,
  stageTotal,
  stageResults,
  currentTask,
  springbootUpgrade,
}: Props) {
  const config = STEP_CONFIG[step] ?? STEP_CONFIG['reverse-engineering'];
  const isCodeStep = step === 'code-generation';
  const isIncrementalJava = pattern === 'java-8-to-25' && currentStage > 0;
  const showBuildLoopPanel = isCodeStep && !isIncrementalJava;
  const showStagePanel = isCodeStep && isIncrementalJava;

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

        {/* Sub-step badge */}
        {isCodeStep && codeSubStep !== 'generating' && SUB_STEP_BADGE[codeSubStep] && (
          <div className={`inline-flex items-center gap-2 text-xs font-medium mb-4 px-3 py-1.5 rounded-full border ${SUB_STEP_BADGE[codeSubStep]!.color}`}>
            {SUB_STEP_BADGE[codeSubStep]!.icon}
            {SUB_STEP_BADGE[codeSubStep]!.label}
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

      {/* Phased incremental Java 8→25 stage panel */}
      {showStagePanel && (
        <div className="glass rounded-2xl overflow-hidden mb-4">
          <div className="px-5 py-3 border-b border-slate-900/10 glass-inset flex items-center justify-between gap-3">
            <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
              Incremental Migration — Step {currentStage} of {stageTotal}
            </span>
            <span className="text-xs text-slate-500 font-mono shrink-0">
              {stageResults.length}/{stageTotal} complete
            </span>
          </div>

          <div className="p-5 space-y-4">
            {phasesForRun(springbootUpgrade).map((phase) => (
              <div key={phase.phase}>
                <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
                  Phase {phase.phase} · {phase.title}
                </p>
                <div className="space-y-1.5">
                  {phase.steps.map((step) => {
                    const done = stageResults.some((s) => s.stage === step.stage);
                    const isCurrent = !done && step.stage === currentStage;
                    const inBuildLoop = isCurrent && validationIteration > 0
                      && (codeSubStep === 'validating' || codeSubStep === 'fixing');
                    return (
                      <div
                        key={step.stage}
                        className={`flex items-center gap-2 text-xs px-3 py-2 rounded-lg border ${
                          done
                            ? 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20'
                            : isCurrent
                            ? 'bg-amber-500/10 text-amber-700 border-amber-500/30'
                            : 'bg-slate-900/5 text-slate-500 border-slate-900/10'
                        }`}
                      >
                        {done ? (
                          <CheckCircle2 size={13} className="shrink-0" />
                        ) : isCurrent ? (
                          <Loader2 size={13} className="shrink-0 animate-spin" />
                        ) : (
                          <Circle size={13} className="shrink-0" />
                        )}
                        <span className="font-mono text-[10px] opacity-70 shrink-0">Step {step.stage}</span>
                        <span className="flex-1 min-w-0">
                          {step.title}
                          {isCurrent && currentTask && (
                            <span className="block text-[10px] opacity-80 truncate">
                              Task {currentTask.index}/{currentTask.total}: {currentTask.title}
                            </span>
                          )}
                        </span>
                        {done && <span className="text-[10px] font-medium shrink-0">complete</span>}
                        {inBuildLoop && (
                          <span className="text-[10px] font-mono shrink-0">
                            {codeSubStep === 'fixing' ? 'fixing' : 'validating'} · iteration {validationIteration}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
            {stageTotal > 0 && stageResults.length === stageTotal && <MigrationCompleteBanner />}
          </div>
        </div>
      )}

      {/* Bigbang / non-Java build loop panel */}
      {showBuildLoopPanel && (
        <div className="glass rounded-2xl overflow-hidden mb-4">
          <div className="px-5 py-3 border-b border-slate-900/10 glass-inset flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
              Build / Fix Loop (max {MAX_ITERATIONS} iterations)
            </span>
            {/* Iteration dots */}
            {validationIteration > 0 && (
              <div className="flex items-center gap-1.5">
                {Array.from({ length: MAX_ITERATIONS }).map((_, i) => {
                  const n = i + 1;
                  const isDone = n < validationIteration;
                  const isCurrent = n === validationIteration;
                  const dotColor = validationResult && n <= validationIteration
                    ? 'bg-emerald-400'        // loop finished → migration is complete, regardless of errors
                    : isDone
                    ? 'bg-rose-500'           // past iterations → had errors, fix was applied
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
                { key: 'generating', icon: <Code2 size={13} />, label: 'Modifier Agent', color: 'amber' },
                { label: '→', isArrow: true },
                { key: 'validating', icon: <ShieldCheck size={13} />, label: 'Validator Agent', color: 'blue' },
                { label: '↺', isArrow: true },
                { key: 'fixing', icon: <Wrench size={13} />, label: 'Fixer Agent', color: 'rose' },
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
                Validating — iteration {validationIteration} of {MAX_ITERATIONS}…
              </div>
            )}
            {codeSubStep === 'fixing' && validationIteration > 0 && (
              <div className="flex items-center gap-2 text-xs px-3 py-2 rounded-lg bg-rose-500/10 text-rose-700 border border-rose-500/20">
                <Wrench size={13} className="shrink-0" />
                Applying fixes — iteration {validationIteration} of {MAX_ITERATIONS}…
              </div>
            )}

            {/* Build/compile loop finished → migration is complete, regardless of any remaining errors */}
            {validationResult && <MigrationCompleteBanner />}
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
