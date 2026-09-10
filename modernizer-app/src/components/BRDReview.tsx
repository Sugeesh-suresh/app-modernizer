import { useRef, useState } from 'react';
import {
  CheckCircle2, MessageSquare, FileText, Loader2, Pencil, Eye,
  Download, Paperclip, X, AlertCircle, Network, Sparkles, ClipboardList,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { brdDownloadUrl, uploadContextFiles } from '../api';

// ── Plain-text diagram renderer ──────────────────────────────────────────────
// Diagrams (class trees, business flows, the dependency graph) arrive as fenced
// ```text blocks and render verbatim in monospace — no diagram library, so
// nothing can fail at render time. Legacy ```mermaid blocks (older sessions, or
// a model slip) are shown as their source instead of being rendered.

const DIAGRAM_LANGS = new Set(['text', 'diagram', 'ascii', 'mermaid']);

function DiagramBlock({ source, legacyMermaid }: { source: string; legacyMermaid: boolean }) {
  return (
    <figure className="not-prose my-4 glass-inset border border-slate-900/10 rounded-lg overflow-hidden">
      {legacyMermaid && (
        <figcaption className="px-3 py-1.5 text-[10px] text-slate-500 border-b border-slate-900/10">
          Mermaid diagram source (diagram rendering is disabled)
        </figcaption>
      )}
      <pre className="m-0 p-4 overflow-x-auto font-mono text-xs leading-relaxed text-slate-800 whitespace-pre">
        {source}
      </pre>
    </figure>
  );
}

// ── Markdown renderer with plain-text diagram support ────────────────────────

const PROSE_CLS = `prose prose-invert prose-sm max-w-none
  prose-headings:text-slate-900 prose-headings:font-semibold
  prose-h1:text-xl prose-h2:text-lg prose-h3:text-base
  prose-p:text-slate-700 prose-li:text-slate-700
  prose-strong:text-slate-900 prose-code:text-red-700 prose-code:bg-slate-900/10
  prose-code:px-1 prose-code:rounded prose-code:text-xs
  prose-pre:bg-slate-900/5 prose-pre:border prose-pre:border-slate-900/10
  prose-blockquote:border-l-red-500 prose-blockquote:text-slate-600
  prose-a:text-red-600 prose-hr:border-slate-900/10
  prose-table:text-slate-700 prose-th:text-slate-800
  prose-td:border-slate-900/10 prose-th:border-slate-900/15`;

function MarkdownWithDiagrams({ content }: { content: string }) {
  return (
    <div className={PROSE_CLS}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre({ node, children }) {
            const code = node?.children[0];
            if (code?.type === 'element' && code.tagName === 'code') {
              const classes = code.properties.className;
              const langClass = Array.isArray(classes)
                ? classes.map(String).find((c) => c.startsWith('language-'))
                : undefined;
              const lang = langClass?.slice('language-'.length) ?? '';
              if (DIAGRAM_LANGS.has(lang)) {
                const source = code.children
                  .map((c) => (c.type === 'text' ? c.value : ''))
                  .join('')
                  .replace(/\n$/, '');
                return <DiagramBlock source={source} legacyMermaid={lang === 'mermaid'} />;
              }
            }
            return <pre>{children}</pre>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

// ── File upload helpers ───────────────────────────────────────────────────────

type FileStatus = 'pending' | 'uploading' | 'done' | 'error';

interface ContextFile {
  id: string;
  file: File;
  status: FileStatus;
  error?: string;
}

const ACCEPTED = '.pdf,.docx,.doc,.json,.txt,.md,.yaml,.yml,.xml,.csv,.toml,.properties,.png,.jpg,.jpeg,.svg';

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  sessionId: string;
  brd: string;
  technicalSpec: string;
  testInventory: string;
  refining: boolean;
  refiningContent: string;
  onConfirm: (brdContent: string, techSpecContent: string, feedback?: string) => Promise<void>;
  onRefine: (feedback: string) => Promise<void>;
}

type ActiveTab = 'brd' | 'techspec' | 'tests';

// ── Component ─────────────────────────────────────────────────────────────────

export function BRDReview({ sessionId, brd, technicalSpec, testInventory, refining, refiningContent, onConfirm, onRefine }: Props) {
  const [activeTab, setActiveTab] = useState<ActiveTab>('brd');
  // Reset the editable drafts whenever freshly (re)generated content arrives —
  // adjusting state during render per https://react.dev/learn/you-might-not-need-an-effect
  const [prevBrd, setPrevBrd] = useState(brd);
  const [prevTechnicalSpec, setPrevTechnicalSpec] = useState(technicalSpec);
  const [brdContent, setBrdContent] = useState(brd);
  const [techSpecContent, setTechSpecContent] = useState(technicalSpec);
  if (brd !== prevBrd || technicalSpec !== prevTechnicalSpec) {
    setPrevBrd(brd);
    setPrevTechnicalSpec(technicalSpec);
    setBrdContent(brd);
    setTechSpecContent(technicalSpec);
  }
  const [brdEditMode, setBrdEditMode] = useState(false);
  const [techEditMode, setTechEditMode] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [showFeedback, setShowFeedback] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [contextFiles, setContextFiles] = useState<ContextFile[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFilesSelected = async (selected: FileList | null) => {
    if (!selected || selected.length === 0) return;
    const newEntries: ContextFile[] = Array.from(selected).map((f) => ({
      id: `${f.name}-${Date.now()}-${Math.random()}`,
      file: f,
      status: 'pending' as FileStatus,
    }));
    setContextFiles((prev) => [...prev, ...newEntries]);
    for (const entry of newEntries) {
      setContextFiles((prev) => prev.map((cf) => cf.id === entry.id ? { ...cf, status: 'uploading' } : cf));
      try {
        await uploadContextFiles(sessionId, [entry.file]);
        setContextFiles((prev) => prev.map((cf) => cf.id === entry.id ? { ...cf, status: 'done' } : cf));
      } catch (err) {
        setContextFiles((prev) => prev.map((cf) =>
          cf.id === entry.id ? { ...cf, status: 'error', error: err instanceof Error ? err.message : 'Upload failed' } : cf,
        ));
      }
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleConfirm = async () => {
    setConfirming(true);
    await onConfirm(brdContent, techSpecContent, feedback || undefined);
  };

  const handleRefine = async () => {
    if (!feedback.trim()) return;
    await onRefine(feedback);
    setFeedback('');
  };

  const formatBytes = (b: number) =>
    b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(1)} MB`;

  const anyUploading = contextFiles.some((cf) => cf.status === 'uploading');

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-start gap-4 mb-6">
        <div className="w-11 h-11 rounded-xl bg-red-500/20 border border-red-500/30 flex items-center justify-center shrink-0">
          <Network size={20} className="text-red-600" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-slate-900">Analysis Review</h2>
          <p className="text-sm text-slate-600 mt-0.5">
            Review and edit the AI-generated BRD and Technical Specification. Upload additional context files
            (Swagger, OpenAPI, design diagrams) to enrich the migration plan.
          </p>
        </div>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 mb-4">
        <button
          onClick={() => setActiveTab('brd')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === 'brd' ? 'bg-blue-600 text-white' : 'bg-slate-900/5 text-slate-600 hover:text-slate-900'
          }`}
        >
          <FileText size={14} />
          Business Requirements Document
        </button>
        <button
          onClick={() => setActiveTab('techspec')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === 'techspec' ? 'bg-violet-600 text-white' : 'bg-slate-900/5 text-slate-600 hover:text-slate-900'
          }`}
        >
          <Network size={14} />
          Technical Specification
          {technicalSpec && <span className="text-xs opacity-70 ml-1">+ Dependency Graph</span>}
        </button>
        <button
          onClick={() => setActiveTab('tests')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === 'tests' ? 'bg-emerald-600 text-white' : 'bg-slate-900/5 text-slate-600 hover:text-slate-900'
          }`}
        >
          <ClipboardList size={14} />
          Existing Test Cases
        </button>
      </div>

      {/* BRD Panel */}
      {activeTab === 'brd' && (
        <div className="glass rounded-2xl overflow-hidden mb-6">
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-900/10 glass-inset">
            <span className="text-xs font-medium text-slate-600">BRD.md</span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-blue-600 bg-blue-400/10 border border-blue-400/20 rounded-full px-2 py-0.5">
                Awaiting Review
              </span>
              <button
                onClick={() => setBrdEditMode((v) => !v)}
                className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900 bg-slate-900/5 hover:bg-slate-900/10 border border-slate-900/10 rounded-lg px-2.5 py-1 transition-colors cursor-pointer"
              >
                {brdEditMode ? <Eye size={12} /> : <Pencil size={12} />}
                {brdEditMode ? 'Preview' : 'Edit'}
              </button>
              <a
                href={brdDownloadUrl(sessionId)}
                download
                className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900 bg-slate-900/5 hover:bg-slate-900/10 border border-slate-900/10 rounded-lg px-2.5 py-1 transition-colors"
              >
                <Download size={12} />
                Download
              </a>
            </div>
          </div>
          {brdEditMode ? (
            <textarea
              value={brdContent}
              onChange={(e) => setBrdContent(e.target.value)}
              className="w-full h-[62vh] bg-slate-900/[0.03] px-6 py-5 text-sm text-slate-700 font-mono resize-none focus:outline-none focus:ring-1 focus:ring-red-500"
              spellCheck={false}
            />
          ) : (
            <div className="p-6 max-h-[62vh] overflow-y-auto">
              <MarkdownWithDiagrams content={brdContent} />
            </div>
          )}
        </div>
      )}

      {/* Technical Specification Panel */}
      {activeTab === 'techspec' && (
        <div className="glass rounded-2xl overflow-hidden mb-6">
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-900/10 glass-inset">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-slate-600">technical-spec.md</span>
              <span className="text-[10px] text-violet-600 bg-violet-400/10 border border-violet-400/20 rounded-full px-2 py-0.5">
                Includes Diagrams
              </span>
            </div>
            <button
              onClick={() => setTechEditMode((v) => !v)}
              className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900 bg-slate-900/5 hover:bg-slate-900/10 border border-slate-900/10 rounded-lg px-2.5 py-1 transition-colors cursor-pointer"
            >
              {techEditMode ? <Eye size={12} /> : <Pencil size={12} />}
              {techEditMode ? 'Preview' : 'Edit'}
            </button>
          </div>
          {techEditMode ? (
            <textarea
              value={techSpecContent}
              onChange={(e) => setTechSpecContent(e.target.value)}
              className="w-full h-[62vh] bg-slate-900/[0.03] px-6 py-5 text-sm text-slate-700 font-mono resize-none focus:outline-none focus:ring-1 focus:ring-violet-500"
              spellCheck={false}
            />
          ) : (
            <div className="p-6 max-h-[62vh] overflow-y-auto">
              {techSpecContent
                ? <MarkdownWithDiagrams content={techSpecContent} />
                : <p className="text-slate-600 text-sm italic">Technical specification not available.</p>
              }
            </div>
          )}
        </div>
      )}

      {/* Existing Test Inventory Panel */}
      {activeTab === 'tests' && (
        <div className="glass rounded-2xl overflow-hidden mb-6">
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-900/10 glass-inset">
            <span className="text-xs font-medium text-slate-600">test-inventory.md</span>
            <span className="text-[10px] text-emerald-600 bg-emerald-400/10 border border-emerald-400/20 rounded-full px-2 py-0.5">
              Read-only
            </span>
          </div>
          <div className="p-6 max-h-[62vh] overflow-y-auto">
            {testInventory
              ? <MarkdownWithDiagrams content={testInventory} />
              : <p className="text-slate-600 text-sm italic">No existing test inventory was generated for this repository.</p>
            }
          </div>
        </div>
      )}

      {/* Additional context files */}
      <div className="glass rounded-2xl overflow-hidden mb-6">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-900/10 glass-inset">
          <div>
            <span className="text-xs font-medium text-slate-700">Additional Context Files</span>
            <p className="text-xs text-slate-500 mt-0.5">
              Swagger / OpenAPI specs, design diagrams, architecture docs, data dictionaries — all merged into the plan
            </p>
          </div>
          <button
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900 bg-slate-900/5 hover:bg-slate-900/10 border border-slate-900/10 rounded-lg px-2.5 py-1.5 transition-colors cursor-pointer"
          >
            <Paperclip size={12} />
            Add files
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED}
            className="hidden"
            onChange={(e) => handleFilesSelected(e.target.files)}
          />
        </div>

        {contextFiles.length === 0 ? (
          <button
            onClick={() => fileInputRef.current?.click()}
            className="w-full flex flex-col items-center gap-2 py-6 text-slate-600 hover:text-slate-600 transition-colors cursor-pointer"
          >
            <Paperclip size={20} />
            <span className="text-xs">Upload Swagger, OpenAPI specs, design diagrams, or reference docs</span>
          </button>
        ) : (
          <ul className="divide-y divide-slate-900/10">
            {contextFiles.map((cf) => (
              <li key={cf.id} className="flex items-center gap-3 px-5 py-2.5">
                {cf.status === 'uploading' && <Loader2 size={13} className="animate-spin text-blue-600 shrink-0" />}
                {cf.status === 'done'      && <CheckCircle2 size={13} className="text-emerald-600 shrink-0" />}
                {cf.status === 'error'     && <AlertCircle size={13} className="text-red-600 shrink-0" />}
                {cf.status === 'pending'   && <Loader2 size={13} className="text-slate-500 shrink-0" />}
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-slate-700 truncate">{cf.file.name}</p>
                  {cf.status === 'error' && <p className="text-xs text-red-600 mt-0.5">{cf.error}</p>}
                </div>
                <span className="text-xs text-slate-600 shrink-0">{formatBytes(cf.file.size)}</span>
                <span className={`text-xs shrink-0 ${
                  cf.status === 'done' ? 'text-emerald-600' : cf.status === 'error' ? 'text-red-600' :
                  cf.status === 'uploading' ? 'text-blue-600' : 'text-slate-500'
                }`}>
                  {cf.status === 'done' ? 'Uploaded' : cf.status === 'error' ? 'Failed' :
                   cf.status === 'uploading' ? 'Uploading…' : 'Pending'}
                </span>
                {cf.status !== 'uploading' && (
                  <button onClick={() => setContextFiles((p) => p.filter((c) => c.id !== cf.id))}
                    className="text-slate-600 hover:text-slate-700 transition-colors shrink-0">
                    <X size={13} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Feedback */}
      {showFeedback ? (
        <div className="mb-4">
          <label className="text-sm font-medium text-slate-700 mb-2 block">Feedback / Change Requests (optional)</label>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="e.g. 'Add GDPR compliance section to BRD' or 'Update the dependency graph to include the auth service'"
            rows={3}
            className="w-full glass border border-slate-900/10 rounded-xl px-4 py-3 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:border-red-500 resize-none"
          />
        </div>
      ) : (
        <button onClick={() => setShowFeedback(true)}
          className="flex items-center gap-2 text-sm text-slate-600 hover:text-slate-900 mb-4 transition-colors">
          <MessageSquare size={15} />
          Add feedback or change requests
        </button>
      )}

      {/* Refining preview */}
      {refining && (
        <div className="glass rounded-2xl overflow-hidden mb-4">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-900/10 glass-inset">
            <span className="flex items-center gap-1.5 text-xs font-medium text-slate-600">
              <Sparkles size={13} className="text-violet-600" />
              Planner is revising the analysis…
            </span>
            <span className="flex items-center gap-1.5 text-xs text-emerald-600">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Streaming
            </span>
          </div>
          <div className="p-4 max-h-64 overflow-y-auto font-mono text-xs text-slate-700 leading-relaxed whitespace-pre-wrap">
            {refiningContent}
            <span className="inline-block w-1.5 h-3.5 bg-red-400 animate-pulse ml-0.5 align-middle" />
          </div>
        </div>
      )}

      {/* Confirm */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={handleConfirm}
          disabled={confirming || refining || anyUploading}
          className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-900/5 disabled:text-slate-500 text-white font-semibold px-6 py-3 rounded-xl transition-colors text-sm shadow-lg shadow-emerald-500/20 cursor-pointer disabled:cursor-not-allowed"
        >
          {confirming ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
          {confirming ? 'Confirming…' : 'Confirm Analysis & Generate Plan'}
        </button>
        <button
          onClick={handleRefine}
          disabled={confirming || refining || anyUploading || !feedback.trim()}
          title={!feedback.trim() ? 'Add feedback above first' : undefined}
          className="flex items-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:bg-slate-900/5 disabled:text-slate-500 text-white font-semibold px-5 py-3 rounded-xl transition-colors text-sm cursor-pointer disabled:cursor-not-allowed"
        >
          {refining ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
          {refining ? 'Refining…' : 'Refine with Planner'}
        </button>
        <p className="text-xs text-slate-500">
          {anyUploading ? 'Waiting for file uploads to finish…' : 'Refine re-runs the planner with your feedback; Confirm advances to plan generation.'}
        </p>
      </div>
    </div>
  );
}
