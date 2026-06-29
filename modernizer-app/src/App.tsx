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
import type { PatternId, WorkflowState, WorkflowStep, SSEEvent } from './types';

const INITIAL_STATE: WorkflowState = {
  sessionId: null,
  pattern: null,
  step: 'upload',
  brd: '',
  technicalSpec: '',
  plan: '',
  generatedFiles: [],
  streamingContent: '',
  validationContent: '',
  progress: 0,
  progressMessage: '',
  codeSubStep: 'generating',
  validationIteration: 0,
  validationResult: null,
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
            validationContent: '',
            progress: 0,
            progressMessage: '',
            codeSubStep: 'generating',
            validationIteration: 0,
            validationResult: null,
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

      // ── Quarkus validation loop events ──────────────────────────────────

      case 'validation-agent-start':
        setState((s) => ({
          ...s,
          codeSubStep: 'validating',
          validationContent: '',
          validationIteration: event.iteration ?? s.validationIteration + 1,
          progressMessage: `Validating — iteration ${event.iteration ?? s.validationIteration + 1} / 4…`,
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
          progressMessage: `Fixing errors — iteration ${event.iteration ?? s.validationIteration} / 4…`,
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
          progressMessage: event.passed
            ? `Build validated — ${event.iterations ?? s.validationIteration} iteration(s)`
            : `Completed ${event.iterations ?? s.validationIteration} iteration(s) — issues remain`,
        }));
        break;

      // ── End validation loop events ───────────────────────────────────────

      case 'brd-ready':
        setState((s) => ({
          ...s,
          brd: event.brd ?? s.streamingContent,
          technicalSpec: event.technical_spec ?? '',
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

  const handleConfirmBrd = async (brdContent: string, techSpecContent: string, feedback?: string) => {
    if (!state.sessionId) return;
    await confirmBrd(state.sessionId, brdContent, techSpecContent, feedback);
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
  const showStepIndicator = state.pattern !== null && state.step !== 'upload';

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
        {state.pattern === null && (
          <PatternSelection onSelect={handleSelectPattern} />
        )}

        {state.pattern !== null && state.step === 'upload' && (
          <FileUpload
            pattern={state.pattern}
            onSessionCreated={handleSessionCreated}
            onBack={handleBack}
          />
        )}

        {(state.step === 'reverse-engineering' ||
          state.step === 'brd-generation' ||
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
          />
        )}

        {state.step === 'brd-review' && state.brd && state.sessionId && (
          <BRDReview
            sessionId={state.sessionId}
            brd={state.brd}
            technicalSpec={state.technicalSpec}
            onConfirm={handleConfirmBrd}
          />
        )}

        {state.step === 'plan-review' && state.plan && state.sessionId && (
          <PlanReview sessionId={state.sessionId} plan={state.plan} onConfirm={handleConfirmPlan} />
        )}

        {state.step === 'complete' && state.generatedFiles.length > 0 && (
          <CodeOutput
            sessionId={state.sessionId ?? ''}
            files={state.generatedFiles}
            pattern={patternConfig?.title ?? state.pattern ?? ''}
            onStartNew={handleStartNew}
          />
        )}

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
