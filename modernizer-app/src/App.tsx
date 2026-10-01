import { useCallback, useEffect, useRef, useState } from 'react';
import { Header } from './components/Header';
import { PatternSelection } from './components/PatternSelection';
import { JavaMigrationOptions } from './components/JavaMigrationOptions';
import { FileUpload } from './components/FileUpload';
import { StepIndicator } from './components/StepIndicator';
import { ProcessingView } from './components/ProcessingView';
import { BRDReview } from './components/BRDReview';
import { PlanReview } from './components/PlanReview';
import { CodeOutput } from './components/CodeOutput';
import { CompanionSelection } from './components/CompanionSelection';
import {
  confirmBrd, confirmPlan, refineBrd, refinePlan, selectCompanions, createSSEConnection,
  reverseEngineeringDownloadUrl,
} from './api';
import { PATTERNS } from './data/patterns';
import type {
  PatternId, JavaMigrationOptions as JavaOptions, WorkflowState, WorkflowStep, SSEEvent, StageResult,
} from './types';
import { RE_ONLY_PATTERNS } from './types';

const INITIAL_STATE: WorkflowState = {
  sessionId: null,
  pattern: null,
  javaOptions: null,
  step: 'upload',
  brd: '',
  technicalSpec: '',
  testInventory: '',
  plan: '',
  generatedFiles: [],
  generatedFilesTotal: 0,
  filesTruncated: 0,
  analysisReview: true,
  preflight: false,
  preflightSummary: '',
  changedFiles: [],
  streamingContent: '',
  validationContent: '',
  progress: 0,
  progressMessage: '',
  codeSubStep: 'generating',
  validationIteration: 0,
  validationResult: null,
  currentStage: 0,
  stageTotal: 0,
  stageResults: [],
  currentTask: null,
  codeReview: '',
  finalReport: '',
  skillCuratorSummary: '',
  refining: false,
  companionRecommendations: [],
  error: null,
};

export default function App() {
  const [state, setState] = useState<WorkflowState>(INITIAL_STATE);
  const esRef = useRef<EventSource | null>(null);

  // ── SSE connection ────────────────────────────────────────────────────────

  const connectSSE = useCallback((sessionId: string) => {
    if (esRef.current) {
      esRef.current.close();
    }
    const es = createSSEConnection(
      sessionId,
      (e: MessageEvent) => {
        let event: SSEEvent;
        try {
          event = JSON.parse(e.data);
        } catch {
          return;
        }
        handleSSEEvent(event);
      },
      () => {
        // Silently handle connection drops; SSE auto-reconnects
      },
    );
    esRef.current = es;
  }, []);

  const handleSSEEvent = useCallback((event: SSEEvent) => {
    switch (event.type) {
      case 'connected':
        break;

      case 'step-change':
        if (event.step) {
          setState((s) => ({
            ...s,
            step: event.step as WorkflowStep,
            streamingContent: '',
            validationContent: '',
            progress: 0,
            progressMessage: '',
            codeSubStep: 'generating',
            validationIteration: 0,
            validationResult: null,
            currentStage: 0,
            stageTotal: 0,
            stageResults: [],
            currentTask: null,
          }));
        }
        break;

      case 'progress':
        setState((s) => ({
          ...s,
          progress: event.progress ?? s.progress,
          progressMessage: event.message ?? s.progressMessage,
        }));
        break;

      case 're-stream':
      case 'brd-stream':
      case 'plan-stream':
      case 'code-stream':
        setState((s) => ({
          ...s,
          streamingContent: s.streamingContent + (event.content ?? ''),
          progress: event.progress ?? s.progress,
          codeSubStep: s.step === 'code-generation' ? 'generating' : s.codeSubStep,
        }));
        break;

      // ── java-8-to-25 incremental strategy: true staged builds ────────────

      case 'stage-start':
        setState((s) => ({
          ...s,
          currentStage: event.stage ?? s.currentStage,
          stageTotal: event.total ?? s.stageTotal,
          currentTask: null,
          codeSubStep: 'generating',
          streamingContent: '',
          validationIteration: 0,
          validationResult: null,
          progressMessage: `Step ${event.stage}/${event.total ?? s.stageTotal} · Phase ${event.phase}: ${event.title}`,
        }));
        break;

      // Each plan task is applied by its own modifier run, within the current stage
      case 'task-start':
        setState((s) => ({
          ...s,
          codeSubStep: 'generating',
          streamingContent: '',
          currentTask: {
            id: event.task_id ?? '',
            title: event.task_title ?? '',
            index: event.task_index ?? 0,
            total: event.task_total ?? 0,
          },
          progressMessage: `Step ${event.stage}/${event.total} · Task ${event.task_index}/${event.task_total}: ${event.task_title}`,
        }));
        break;

      case 'task-complete':
        setState((s) => ({ ...s, currentTask: null }));
        break;

      case 'stage-complete':
        setState((s) => {
          const result: StageResult = {
            stage: event.stage ?? 0,
            phase: event.phase ?? 0,
            phaseTitle: event.phase_title ?? '',
            title: event.title ?? '',
            passed: event.passed ?? true,
            errors: event.errors ?? [],
            summary: event.summary ?? '',
            iterations: event.iterations ?? 0,
          };
          return {
            ...s,
            stageResults: [...s.stageResults.filter((r) => r.stage !== result.stage), result],
          };
        });
        break;

      // ── Build/validate/fix loop events (bigbang + all non-Java patterns) ──

      case 'validation-agent-start':
        setState((s) => ({
          ...s,
          codeSubStep: 'validating',
          validationContent: '',
          validationIteration: event.iteration ?? s.validationIteration + 1,
          progressMessage: `Validating — iteration ${event.iteration ?? s.validationIteration + 1}…`,
        }));
        break;

      case 'validate-stream':
        setState((s) => ({
          ...s,
          validationContent: s.validationContent + (event.content ?? ''),
          progress: event.progress ?? s.progress,
        }));
        break;

      case 'fix-agent-start':
        setState((s) => ({
          ...s,
          codeSubStep: 'fixing',
          streamingContent: '',
          progressMessage: `Fixing issues — iteration ${event.iteration ?? s.validationIteration}…`,
        }));
        break;

      case 'fix-stream':
        setState((s) => ({
          ...s,
          streamingContent: s.streamingContent + (event.content ?? ''),
          progress: event.progress ?? s.progress,
        }));
        break;

      case 'validation-complete':
        setState((s) => ({
          ...s,
          codeSubStep: 'generating',
          validationResult: {
            passed: event.passed ?? true,
            errors: event.errors ?? [],
            summary: event.summary ?? '',
            iterations: event.iterations ?? s.validationIteration,
          },
          // Build/compile loop finished → the migration is complete, regardless of remaining errors
          progressMessage: 'Migration is complete',
        }));
        break;

      // ── Independent code review (runs after the build loop, before the reporter) ──

      case 'review-stream':
        setState((s) => ({
          ...s,
          codeSubStep: 'reviewing',
          streamingContent: s.streamingContent + (event.content ?? ''),
          progressMessage: 'Independent code review…',
        }));
        break;

      case 'code-review-ready':
        setState((s) => ({
          ...s,
          codeReview: event.content ?? '',
          streamingContent: '',
          codeSubStep: 'generating',
        }));
        break;

      // ── Skill curator (runs last, after the reporter) ─────────────────────

      case 'curator-stream':
        setState((s) => ({
          ...s,
          codeSubStep: 'curating',
          streamingContent: s.streamingContent + (event.content ?? ''),
          progressMessage: 'Curating the skill library…',
        }));
        break;

      case 'skill-curator-ready':
        setState((s) => ({
          ...s,
          skillCuratorSummary: event.content ?? '',
          streamingContent: '',
          codeSubStep: 'generating',
        }));
        break;

      // ── End build/validate/fix loop events ───────────────────────────────

      case 'dependency-graph-ready':
        break; // graph is folded into technical_spec server-side; nothing to do here

      case 'companion-recommendations':
        setState((s) => ({ ...s, companionRecommendations: event.companions ?? [] }));
        break;

      // stack-discovery: the dependency mapper's streamed reasoning, then its
      // reconciled result. The inventory itself lands in the document, so this
      // only needs to clear the stream before the confirmation screen renders.
      case 'mapper-stream':
        setState((s) => ({
          ...s,
          streamingContent: s.streamingContent + (event.content ?? ''),
          progress: event.progress ?? s.progress,
        }));
        break;

      // Java 8 -> 11 environment check: its one-line result stays on screen for
      // the rest of the run (an environment failure arrives as an `error`).
      case 'preflight-stream':
        setState((s) => ({ ...s, preflightSummary: (event.content ?? '').replace(/\*\*/g, '').trim() }));
        break;

      case 'stack-inventory-ready':
        setState((s) => ({ ...s, streamingContent: '' }));
        break;

      case 'brd-ready':
        setState((s) => ({
          ...s,
          brd: event.brd ?? s.streamingContent,
          technicalSpec: event.technical_spec ?? '',
          testInventory: event.test_inventory ?? '',
          step: 'brd-review',
          streamingContent: '',
          refining: false,
          progress: 100,
        }));
        break;

      case 'plan-ready':
        setState((s) => ({
          ...s,
          plan: event.content ?? s.streamingContent,
          step: 'plan-review',
          streamingContent: '',
          refining: false,
          progress: 100,
        }));
        break;

      case 'diff-ready':
        setState((s) => ({ ...s, changedFiles: event.changed_files ?? [] }));
        break;

      case 'code-ready':
        setState((s) => ({
          ...s,
          generatedFiles: event.files ?? [],
          // `files` is a capped preview on a large repo; `total` is the real
          // count, so the browser can say it is showing a subset.
          generatedFilesTotal: event.total ?? (event.files ?? []).length,
          streamingContent: '',
          progress: 100,
        }));
        break;

      // reporter_agent's closing summary
      case 'report-ready':
        setState((s) => ({ ...s, finalReport: event.content ?? '' }));
        break;

      case 'workflow-complete':
        setState((s) => ({ ...s, step: 'complete' }));
        if (esRef.current) {
          esRef.current.close();
          esRef.current = null;
        }
        break;

      case 'error':
        setState((s) => ({
          ...s,
          step: 'error',
          error: event.message ?? 'An error occurred',
        }));
        if (esRef.current) {
          esRef.current.close();
          esRef.current = null;
        }
        break;
    }
  }, []);

  useEffect(() => {
    return () => {
      esRef.current?.close();
    };
  }, []);

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleSelectPattern = (id: PatternId) => {
    setState((s) => ({ ...s, pattern: id, step: 'upload' }));
  };

  const handleJavaOptionsContinue = (options: JavaOptions) => {
    setState((s) => ({ ...s, javaOptions: options }));
  };

  const handleSessionCreated = (sessionId: string, filesTruncated = 0, analysisReview = true, preflight = false) => {
    setState((s) => ({
      ...s,
      sessionId,
      filesTruncated,
      analysisReview,
      preflight,
      step: 'dependency-graph',
      streamingContent: '',
      progress: 0,
    }));
    connectSSE(sessionId);
  };

  const handleSelectCompanions = async (selected: PatternId[]) => {
    if (!state.sessionId) return;
    // The backend's next step-change (reverse-engineering) advances the view,
    // same as the BRD/plan confirm flows.
    await selectCompanions(state.sessionId, selected);
  };

  const handleConfirmBrd = async (brdContent: string, techSpecContent: string, feedback?: string) => {
    if (!state.sessionId) return;
    await confirmBrd(state.sessionId, brdContent, techSpecContent, feedback);
    setState((s) => ({ ...s, step: 'plan-generation', streamingContent: '', progress: 0 }));
  };

  const handleRefineBrd = async (feedback: string) => {
    if (!state.sessionId) return;
    setState((s) => ({ ...s, refining: true, streamingContent: '' }));
    try {
      await refineBrd(state.sessionId, feedback);
    } catch (err) {
      setState((s) => ({
        ...s,
        refining: false,
        error: err instanceof Error ? err.message : 'Failed to refine BRD',
      }));
    }
  };

  const handleConfirmPlan = async (content: string, feedback?: string) => {
    if (!state.sessionId) return;
    await confirmPlan(state.sessionId, content, feedback);
    setState((s) => ({ ...s, step: 'code-generation', streamingContent: '', progress: 0 }));
  };

  const handleRefinePlan = async (feedback: string) => {
    if (!state.sessionId) return;
    setState((s) => ({ ...s, refining: true, streamingContent: '' }));
    try {
      await refinePlan(state.sessionId, feedback);
    } catch (err) {
      setState((s) => ({
        ...s,
        refining: false,
        error: err instanceof Error ? err.message : 'Failed to refine plan',
      }));
    }
  };

  const handleStartNew = () => {
    esRef.current?.close();
    esRef.current = null;
    setState(INITIAL_STATE);
  };

  const handleBack = () => {
    setState(INITIAL_STATE);
  };

  // ── Render ────────────────────────────────────────────────────────────────

  const patternConfig = PATTERNS.find((p) => p.id === state.pattern);
  const showStepIndicator = state.pattern !== null && state.step !== 'upload';
  const needsJavaOptions = state.pattern === 'java-8-to-25' && !state.javaOptions;
  const reOnly = state.pattern !== null && RE_ONLY_PATTERNS.includes(state.pattern);

  // The rail shows only the steps this run will actually reach: an RE-only run
  // never plans or generates, and every other run never maps stacks. A step left
  // in that never fires reads as one that failed.
  const skipSteps: WorkflowStep[] = reOnly
    ? ['plan-generation', 'plan-review', 'code-generation']
    : ['stack-mapping'];
  if (state.companionRecommendations.length === 0) skipSteps.push('companion-selection');
  // A deterministic inventory goes from the dependency mapper straight to the
  // planner: the server never enters these steps, so the rail does not show them.
  if (!state.analysisReview) skipSteps.push('reverse-engineering', 'brd-review');
  if (!state.preflight) skipSteps.push('preflight');

  return (
    <div className="min-h-screen">
      <Header />

      {state.preflightSummary && state.step !== 'upload' && (
        <div className="max-w-5xl mx-auto px-6 pt-4">
          <div className="rounded-xl border border-slate-900/10 bg-slate-900/5 px-4 py-2 text-xs text-slate-700">
            {state.preflightSummary}
          </div>
        </div>
      )}

      {/* Stays visible for the whole run, not just at upload: every document and
          manifest produced afterwards describes only the part of the repository
          that was unpacked, and the person approving them has to know that. */}
      {state.filesTruncated > 0 && (
        <div className="max-w-5xl mx-auto px-6 pt-4">
          <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-900">
            <strong>Incomplete repository.</strong>{' '}
            {state.filesTruncated.toLocaleString()} file
            {state.filesTruncated === 1 ? '' : 's'} exceeded this server's ingestion limit and{' '}
            <strong>were not unpacked</strong>. Everything below was produced from a partial copy —
            inventories, file manifests and coverage claims cover only what was unpacked. Raise{' '}
            <code className="font-mono text-xs">WORKSPACE_MAX_FILES</code> /{' '}
            <code className="font-mono text-xs">WORKSPACE_MAX_TOTAL_BYTES</code> and re-run before
            relying on these results.
          </div>
        </div>
      )}

      {showStepIndicator && (
        <StepIndicator
          currentStep={state.step}
          pattern={state.pattern}
          progress={state.progress}
          progressMessage={state.progressMessage}
          skipSteps={skipSteps}
        />
      )}

      <main>
        {state.pattern === null && (
          <PatternSelection onSelect={handleSelectPattern} />
        )}

        {state.pattern !== null && state.step === 'upload' && needsJavaOptions && (
          <JavaMigrationOptions onContinue={handleJavaOptionsContinue} onBack={handleBack} />
        )}

        {state.pattern !== null && state.step === 'upload' && !needsJavaOptions && (
          <FileUpload
            pattern={state.pattern}
            options={state.javaOptions}
            onSessionCreated={handleSessionCreated}
            onBack={handleBack}
          />
        )}

        {state.step === 'companion-selection' && state.companionRecommendations.length > 0 && (
          <CompanionSelection
            primaryLabel={patternConfig?.title ?? state.pattern ?? ''}
            recommendations={state.companionRecommendations}
            onConfirm={handleSelectCompanions}
            discovery={reOnly}
          />
        )}

        {(state.step === 'dependency-graph' ||
          state.step === 'preflight' ||
          state.step === 'stack-mapping' ||
          state.step === 'reverse-engineering' ||
          state.step === 'plan-generation' ||
          state.step === 'code-generation') && (
          <ProcessingView
            step={state.step}
            pattern={state.pattern}
            streamingContent={state.streamingContent}
            validationContent={state.validationContent}
            progress={state.progress}
            progressMessage={state.progressMessage}
            codeSubStep={state.codeSubStep}
            validationIteration={state.validationIteration}
            validationResult={state.validationResult}
            currentStage={state.currentStage}
            stageTotal={state.stageTotal}
            stageResults={state.stageResults}
            currentTask={state.currentTask}
            springbootUpgrade={state.javaOptions?.springbootUpgrade ?? false}
          />
        )}

        {state.step === 'brd-review' && state.brd && state.sessionId && (
          <BRDReview
            sessionId={state.sessionId}
            brd={state.brd}
            technicalSpec={state.technicalSpec}
            testInventory={state.testInventory}
            refining={state.refining}
            refiningContent={state.streamingContent}
            onConfirm={handleConfirmBrd}
            onRefine={handleRefineBrd}
            reOnly={reOnly}
          />
        )}

        {state.step === 'plan-review' && state.plan && state.sessionId && (
          <PlanReview
            sessionId={state.sessionId}
            plan={state.plan}
            refining={state.refining}
            refiningContent={state.streamingContent}
            onConfirm={handleConfirmPlan}
            onRefine={handleRefinePlan}
          />
        )}

        {state.step === 'complete' && state.generatedFiles.length > 0 && (
          <CodeOutput
            sessionId={state.sessionId ?? ''}
            files={state.generatedFiles}
            filesTotal={state.generatedFilesTotal}
            changedFiles={state.changedFiles}
            pattern={patternConfig?.title ?? state.pattern ?? ''}
            codeReview={state.codeReview}
            report={state.finalReport}
            skillCuratorSummary={state.skillCuratorSummary}
            onStartNew={handleStartNew}
          />
        )}

        {state.step === 'complete' && state.generatedFiles.length === 0 && (
          <div className="max-w-xl mx-auto px-6 py-20 text-center">
            <div className="glass rounded-2xl p-8">
              <div className="w-14 h-14 rounded-full bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center mx-auto mb-4">
                <span className="text-2xl text-emerald-600">✓</span>
              </div>
              <h2 className="text-xl font-bold text-slate-900 mb-2">
                {reOnly ? 'Reverse engineering is complete' : 'Migration is complete'}
              </h2>
              {reOnly && (
                <>
                  <p className="text-sm text-slate-600 mb-6">
                    {state.companionRecommendations.length > 0 ? (
                      <>
                        Documented{' '}
                        {state.companionRecommendations.map((r) => r.label).join(', ')}. Nothing in
                        the repository was modified.
                      </>
                    ) : (
                      <>Nothing in the repository was modified.</>
                    )}
                  </p>
                  {state.sessionId && (
                    <a
                      href={reverseEngineeringDownloadUrl(state.sessionId)}
                      download
                      className="inline-flex items-center gap-2 bg-violet-600 hover:bg-violet-500 text-white px-6 py-2.5 rounded-xl text-sm font-medium transition-colors cursor-pointer mb-3"
                    >
                      Download the reverse-engineering document
                    </a>
                  )}
                  <div />
                </>
              )}
              {!reOnly && <div className="mb-6" />}
              <button
                onClick={handleStartNew}
                className="bg-emerald-600 hover:bg-emerald-500 text-white px-6 py-2.5 rounded-xl text-sm font-medium transition-colors cursor-pointer"
              >
                {reOnly ? 'Start New Run' : 'Start New Migration'}
              </button>
            </div>
          </div>
        )}

        {state.step === 'error' && (
          <div className="max-w-xl mx-auto px-6 py-20 text-center">
            <div className="glass rounded-2xl p-8">
              <div className="w-14 h-14 rounded-full bg-red-500/20 border border-red-500/30 flex items-center justify-center mx-auto mb-4">
                <span className="text-2xl">⚠</span>
              </div>
              <h2 className="text-xl font-bold text-slate-900 mb-2">Something went wrong</h2>
              <p className="text-slate-600 text-sm mb-6">{state.error}</p>
              <button
                onClick={handleStartNew}
                className="bg-red-600 hover:bg-red-500 text-white px-6 py-2.5 rounded-xl text-sm font-medium transition-colors cursor-pointer"
              >
                Start Over
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
