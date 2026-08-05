import { useState } from 'react';
import { CheckCircle2, MessageSquare, GitBranch, Loader2, Pencil, Eye, Download } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { planDownloadUrl } from '../api';

interface Props {
  sessionId: string;
  plan: string;
  onConfirm: (content: string, feedback?: string) => Promise<void>;
}

export function PlanReview({ sessionId, plan, onConfirm }: Props) {
  const [editedContent, setEditedContent] = useState(plan);
  const [editMode, setEditMode] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [showFeedback, setShowFeedback] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const handleConfirm = async () => {
    setConfirming(true);
    await onConfirm(editedContent, feedback || undefined);
  };

  return (
    <div className="max-w-4xl mx-auto px-6 py-10">
      {/* Header */}
      <div className="flex items-start gap-4 mb-6">
        <div className="w-11 h-11 rounded-xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center shrink-0">
          <GitBranch size={20} className="text-emerald-600" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-slate-900">Migration Plan</h2>
          <p className="text-sm text-slate-600 mt-0.5">
            Review and edit the AI-generated plan. Your changes will be used for code generation.
          </p>
        </div>
      </div>

      {/* Plan content */}
      <div className="glass rounded-2xl overflow-hidden mb-6">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-900/10 glass-inset">
          <span className="text-xs font-medium text-slate-600">plan.md</span>
          <div className="flex items-center gap-2">
            <span className="text-xs text-emerald-600 bg-emerald-400/10 border border-emerald-400/20 rounded-full px-2 py-0.5">
              Awaiting Review
            </span>
            <button
              onClick={() => setEditMode((v) => !v)}
              className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900 bg-slate-900/5 hover:bg-slate-900/10 border border-slate-900/10 rounded-lg px-2.5 py-1 transition-colors cursor-pointer"
            >
              {editMode ? <Eye size={12} /> : <Pencil size={12} />}
              {editMode ? 'Preview' : 'Edit'}
            </button>
            <a
              href={planDownloadUrl(sessionId)}
              download
              className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900 bg-slate-900/5 hover:bg-slate-900/10 border border-slate-900/10 rounded-lg px-2.5 py-1 transition-colors cursor-pointer"
            >
              <Download size={12} />
              Download
            </a>
          </div>
        </div>

        {editMode ? (
          <textarea
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            className="w-full h-[60vh] bg-slate-900/[0.03] px-6 py-5 text-sm text-slate-700 font-mono resize-none focus:outline-none focus:ring-1 focus:ring-red-500"
            spellCheck={false}
          />
        ) : (
          <div className="p-6 max-h-[60vh] overflow-y-auto prose prose-invert prose-sm max-w-none
            prose-headings:text-slate-900 prose-headings:font-semibold
            prose-h1:text-2xl prose-h2:text-xl prose-h3:text-base
            prose-p:text-slate-700 prose-li:text-slate-700
            prose-strong:text-slate-900 prose-code:text-red-700 prose-code:bg-slate-900/10 prose-code:px-1 prose-code:rounded
            prose-pre:bg-slate-900/5 prose-pre:border prose-pre:border-slate-900/10
            prose-blockquote:border-l-emerald-500 prose-blockquote:text-slate-600
            prose-a:text-red-600 prose-hr:border-slate-900/10
            prose-table:text-slate-700 prose-th:text-slate-800 prose-td:border-slate-900/10 prose-th:border-slate-900/15">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{editedContent}</ReactMarkdown>
          </div>
        )}
      </div>

      {/* Feedback */}
      {showFeedback ? (
        <div className="mb-4">
          <label className="text-sm font-medium text-slate-700 mb-2 block">
            Feedback / Change Requests (optional)
          </label>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="e.g. 'Skip the reactive REST layer, keep it imperative' or 'Add a rollback phase'"
            rows={4}
            className="w-full glass border border-slate-900/10 rounded-xl px-4 py-3 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:border-red-500 resize-none"
          />
        </div>
      ) : (
        <button
          onClick={() => setShowFeedback(true)}
          className="flex items-center gap-2 text-sm text-slate-600 hover:text-slate-900 mb-4 transition-colors"
        >
          <MessageSquare size={15} />
          Add feedback or change requests
        </button>
      )}

      {/* Action */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleConfirm}
          disabled={confirming}
          className="flex items-center gap-2 bg-red-600 hover:bg-red-500 disabled:bg-slate-900/5 disabled:text-slate-500 text-white font-semibold px-6 py-3 rounded-xl transition-colors text-sm shadow-lg shadow-red-500/25 cursor-pointer disabled:cursor-not-allowed"
        >
          {confirming ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <CheckCircle2 size={16} />
          )}
          {confirming ? 'Confirming…' : 'Confirm Plan & Generate Code'}
        </button>
        <p className="text-xs text-slate-500">
          AI will now generate the migrated codebase
        </p>
      </div>
    </div>
  );
}
