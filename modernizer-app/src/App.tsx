import { useCallback, useEffect, useRef, useState } from 'react';
import { Header } from './components/Header';
import { PatternSelection } from './components/PatternSelection';
import { FileUpload } from './components/FileUpload';
import { StepIndicator } from './components/StepIndicator';
import { ProcessingView } from './components/ProcessingView';
import { BRDReview } from './components/BRDReview';
import { PlanReview } from './components/PlanReview';
import { CodeOutput } from './components/CodeOutput';
import { confirmBrd, confirmPlan, createSSEConnection } from './api';
import { PATTERNS } from './data/patterns';
import type { PatternId, WorkflowState, WorkflowStep, SSEEvent, ValidationState } from './types';

const INITIAL_STATE: WorkflowState = {
  sessionId: null,
  pattern: null,
  step: 'upload',
  brd: '',
  plan: '',
  generatedFiles: [],
  testFiles: [],
  streamingContent: '',
  progress: 0,
  progressMessage: '',
  error: null,
  validation: null,
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
      (_e: Event) => {
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
            progress: 0,
            progressMessage: '',
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
      case 'test-stream':
        setState((s) => ({
          ...s,
          streamingContent: s.streamingContent + (event.content ?? ''),
          progress: event.progress ?? s.progress,
        }));
        break;

      case 'brd-ready':
        setState((s) => ({
          ...s,
          brd: event.content ?? s.streamingContent,
          step: 'brd-review',
          streamingContent: '',
          progress: 100,
        }));
        break;

      case 'plan-ready':
        setState((s) => ({
          ...s,
          plan: event.content ?? s.streamingContent,
          step: 'plan-review',
          streamingContent: '',
          progress: 100,
        }));
        break;

      case 'code-ready':
        setState((s) => ({
          ...s,
          generatedFiles: event.files ?? [],
          streamingContent: '',
          progress: 100,
        }));
        break;

      case 'tests-ready':
        setState((s) => ({
          ...s,
          testFiles: event.files ?? [],
          streamingContent: '',
          progress: 100,
        }));
        break;

      case 'validation-start':
        setState((s) => ({
          ...s,
          streamingContent: '',
          progressMessage: `Validating tests (attempt ${event.attempt ?? 1}/${event.max_retries ?? 3})…`,
          validation: {
            attempt: event.attempt ?? 1,
            maxAttempts: event.max_retries ?? 3,
            passed: null,
            issues: [],
            summary: '',
            attemptsUsed: event.attempt ?? 1,
            fixingAttempt: 0,
          } satisfies ValidationState,
        }));
        break;

      case 'validation-result':
        setState((s) => ({
          ...s,
          validation: s.validation
            ? {
                ...s.validation,
                passed: event.passed ?? null,
                issues: event.issues ?? [],
                summary: event.summary ?? '',
                attemptsUsed: event.attempt ?? s.validation.attemptsUsed,
              }
            : null,
        }));
        break;

      case 'fix-start':
        setState((s) => ({
          ...s,
          streamingContent: '',
          progressMessage: `Fixing issues (attempt ${event.attempt ?? 1}/${event.max_retries ?? 3})…`,
          validation: s.validation
            ? { ...s.validation, fixingAttempt: event.attempt ?? 1 }
            : null,
        }));
        break;

      case 'validate-stream':
        // Validation output is JSON — don't render it in the streaming panel
        setState((s) => ({ ...s, progress: event.progress ?? s.progress }));
        break;

      case 'fix-stream':
        setState((s) => ({
          ...s,
          streamingContent: s.streamingContent + (event.content ?? ''),
          progress: event.progress ?? s.progress,
        }));
        break;

      case 'fix-applied': {
        const srcFixed = event.source_files ?? [];
        const tstFixed = event.test_files ?? [];
        setState((s) => {
          const mergeByPath = (orig: typeof s.generatedFiles, fixes: typeof srcFixed) => {
            const map = new Map(orig.map((f) => [f.path, f]));
            fixes.forEach((f) => map.set(f.path, f));
            return Array.from(map.values());
          };
          return {
            ...s,
            generatedFiles: srcFixed.length ? mergeByPath(s.generatedFiles, srcFixed) : s.generatedFiles,
            testFiles: tstFixed.length ? mergeByPath(s.testFiles, tstFixed) : s.testFiles,
            validation: s.validation ? { ...s.validation, fixingAttempt: 0 } : null,
          };
        });
        break;
      }

      case 'validation-complete':
        setState((s) => ({
          ...s,
          validation: s.validation
            ? {
                ...s.validation,
                passed: event.passed ?? s.validation.passed,
                attemptsUsed: event.attempts_used ?? s.validation.attemptsUsed,
                issues: event.final_issues ?? s.validation.issues,
                fixingAttempt: 0,
              }
            : null,
        }));
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

  const handleSessionCreated = (sessionId: string) => {
    setState((s) => ({
      ...s,
      sessionId,
      step: 'reverse-engineering',
      streamingContent: '',
      progress: 0,
    }));
    connectSSE(sessionId);
  };

  const handleConfirmBrd = async (content: string, feedback?: string) => {
    if (!state.sessionId) return;
    await confirmBrd(state.sessionId, content, feedback);
    setState((s) => ({ ...s, step: 'plan-generation', streamingContent: '', progress: 0 }));
  };

  const handleConfirmPlan = async (content: string, feedback?: string) => {
    if (!state.sessionId) return;
    await confirmPlan(state.sessionId, content, feedback);
    setState((s) => ({ ...s, step: 'code-generation', streamingContent: '', progress: 0 }));
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

  const showStepIndicator =
    state.pattern !== null && state.step !== 'upload';

  return (
    <div className="min-h-screen bg-[#0a0b0f]">
      <Header />

      {showStepIndicator && (
        <StepIndicator
          currentStep={state.step}
          progress={state.progress}
          progressMessage={state.progressMessage}
        />
      )}

      <main>
        {/* Pattern selection */}
        {state.pattern === null && (
          <PatternSelection onSelect={handleSelectPattern} />
        )}

        {/* File upload */}
        {state.pattern !== null && state.step === 'upload' && (
          <FileUpload
            pattern={state.pattern}
            onSessionCreated={handleSessionCreated}
            onBack={handleBack}
          />
        )}

        {/* Processing views */}
        {(state.step === 'reverse-engineering' ||
          state.step === 'brd-generation' ||
          state.step === 'plan-generation' ||
          state.step === 'code-generation' ||
          state.step === 'test-generation') && (
          <ProcessingView
            step={state.step}
            streamingContent={state.streamingContent}
            progress={state.progress}
            progressMessage={state.progressMessage}
            validation={state.validation}
          />
        )}

        {/* BRD review */}
        {state.step === 'brd-review' && state.brd && state.sessionId && (
          <BRDReview sessionId={state.sessionId} brd={state.brd} onConfirm={handleConfirmBrd} />
        )}

        {/* Plan review */}
        {state.step === 'plan-review' && state.plan && state.sessionId && (
          <PlanReview sessionId={state.sessionId} plan={state.plan} onConfirm={handleConfirmPlan} />
        )}

        {/* Complete */}
        {state.step === 'complete' && state.generatedFiles.length > 0 && (
          <CodeOutput
            files={state.generatedFiles}
            testFiles={state.testFiles}
            pattern={patternConfig?.title ?? state.pattern ?? ''}
            validation={state.validation}
            onStartNew={handleStartNew}
          />
        )}

        {/* Error */}
        {state.step === 'error' && (
          <div className="max-w-xl mx-auto px-6 py-20 text-center">
            <div className="w-14 h-14 rounded-full bg-red-500/20 border border-red-500/30 flex items-center justify-center mx-auto mb-4">
              <span className="text-2xl">⚠</span>
            </div>
            <h2 className="text-xl font-bold text-white mb-2">Something went wrong</h2>
            <p className="text-slate-400 text-sm mb-6">{state.error}</p>
            <button
              onClick={handleStartNew}
              className="bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-2.5 rounded-xl text-sm font-medium transition-colors"
            >
              Start Over
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
