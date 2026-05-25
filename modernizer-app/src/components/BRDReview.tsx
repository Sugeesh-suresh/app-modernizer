import { useRef, useState } from 'react';
import {
  CheckCircle2, MessageSquare, FileText, Loader2,
  Pencil, Eye, Download, Paperclip, X, AlertCircle,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { brdDownloadUrl, uploadContextFiles } from '../api';

interface Props {
  sessionId: string;
  brd: string;
  onConfirm: (content: string, feedback?: string) => Promise<void>;
}

type FileStatus = 'pending' | 'uploading' | 'done' | 'error';

interface ContextFile {
  id: string;
  file: File;
  status: FileStatus;
  error?: string;
}

const ACCEPTED = '.pdf,.docx,.doc,.json,.txt,.md,.yaml,.yml,.xml,.csv,.toml,.properties';

export function BRDReview({ sessionId, brd, onConfirm }: Props) {
  const [editedContent, setEditedContent] = useState(brd);
  const [editMode, setEditMode] = useState(false);
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
      status: 'pending',
    }));

    setContextFiles((prev) => [...prev, ...newEntries]);

    // Upload each file immediately
    for (const entry of newEntries) {
      setContextFiles((prev) =>
        prev.map((cf) => cf.id === entry.id ? { ...cf, status: 'uploading' } : cf),
      );
      try {
        await uploadContextFiles(sessionId, [entry.file]);
        setContextFiles((prev) =>
          prev.map((cf) => cf.id === entry.id ? { ...cf, status: 'done' } : cf),
        );
      } catch (err) {
        setContextFiles((prev) =>
          prev.map((cf) =>
            cf.id === entry.id
              ? { ...cf, status: 'error', error: err instanceof Error ? err.message : 'Upload failed' }
              : cf,
          ),
        );
      }
    }

    // Reset file input so the same file can be re-selected after removal
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const removeFile = (id: string) => {
    setContextFiles((prev) => prev.filter((cf) => cf.id !== id));
  };

  const handleConfirm = async () => {
    setConfirming(true);
    await onConfirm(editedContent, feedback || undefined);
  };

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const statusIcon = (cf: ContextFile) => {
    if (cf.status === 'uploading') return <Loader2 size={13} className="animate-spin text-blue-400" />;
    if (cf.status === 'done') return <CheckCircle2 size={13} className="text-emerald-400" />;
    if (cf.status === 'error') return <AlertCircle size={13} className="text-red-400" />;
    return <Loader2 size={13} className="text-slate-500" />;
  };

  return (
    <div className="max-w-4xl mx-auto px-6 py-10">
      {/* Header */}
      <div className="flex items-start gap-4 mb-6">
        <div className="w-11 h-11 rounded-xl bg-blue-500/20 border border-blue-500/30 flex items-center justify-center shrink-0">
          <FileText size={20} className="text-blue-400" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-white">Business Requirements Document</h2>
          <p className="text-sm text-slate-400 mt-0.5">
            Review and edit the AI-generated BRD. Upload additional context files to enrich the migration plan.
          </p>
        </div>
      </div>

      {/* BRD content */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden mb-6">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800 bg-slate-950/50">
          <span className="text-xs font-medium text-slate-400">BRD.md</span>
          <div className="flex items-center gap-2">
            <span className="text-xs text-blue-400 bg-blue-400/10 border border-blue-400/20 rounded-full px-2 py-0.5">
              Awaiting Review
            </span>
            <button
              onClick={() => setEditMode((v) => !v)}
              className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg px-2.5 py-1 transition-colors"
            >
              {editMode ? <Eye size={12} /> : <Pencil size={12} />}
              {editMode ? 'Preview' : 'Edit'}
            </button>
            <a
              href={brdDownloadUrl(sessionId)}
              download
              className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg px-2.5 py-1 transition-colors"
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
            className="w-full h-[60vh] bg-slate-900 px-6 py-5 text-sm text-slate-300 font-mono resize-none focus:outline-none focus:ring-1 focus:ring-indigo-500"
            spellCheck={false}
          />
        ) : (
          <div className="p-6 max-h-[60vh] overflow-y-auto prose prose-invert prose-sm max-w-none
            prose-headings:text-white prose-headings:font-semibold
            prose-h1:text-2xl prose-h2:text-xl prose-h3:text-base
            prose-p:text-slate-300 prose-li:text-slate-300
            prose-strong:text-white prose-code:text-indigo-300 prose-code:bg-slate-800 prose-code:px-1 prose-code:rounded
            prose-pre:bg-slate-800 prose-pre:border prose-pre:border-slate-700
            prose-blockquote:border-l-indigo-500 prose-blockquote:text-slate-400
            prose-a:text-indigo-400 prose-hr:border-slate-700
            prose-table:text-slate-300 prose-th:text-slate-200 prose-td:border-slate-700 prose-th:border-slate-600">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{editedContent}</ReactMarkdown>
          </div>
        )}
      </div>

      {/* Additional context files */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden mb-6">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800 bg-slate-950/50">
          <div>
            <span className="text-xs font-medium text-slate-300">Additional Context Files</span>
            <p className="text-xs text-slate-500 mt-0.5">
              PDF, Word, JSON, YAML, TXT — merged into the migration plan
            </p>
          </div>
          <button
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg px-2.5 py-1.5 transition-colors"
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
            className="w-full flex flex-col items-center gap-2 py-8 text-slate-600 hover:text-slate-400 transition-colors"
          >
            <Paperclip size={22} />
            <span className="text-xs">Click to add architecture docs, API specs, or any reference files</span>
          </button>
        ) : (
          <ul className="divide-y divide-slate-800">
            {contextFiles.map((cf) => (
              <li key={cf.id} className="flex items-center gap-3 px-5 py-3">
                {statusIcon(cf)}
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-slate-300 truncate">{cf.file.name}</p>
                  {cf.status === 'error' && (
                    <p className="text-xs text-red-400 mt-0.5">{cf.error}</p>
                  )}
                </div>
                <span className="text-xs text-slate-600 shrink-0">{formatBytes(cf.file.size)}</span>
                <span className={`text-xs shrink-0 ${
                  cf.status === 'done' ? 'text-emerald-400' :
                  cf.status === 'error' ? 'text-red-400' :
                  cf.status === 'uploading' ? 'text-blue-400' : 'text-slate-500'
                }`}>
                  {cf.status === 'done' ? 'Uploaded' :
                   cf.status === 'error' ? 'Failed' :
                   cf.status === 'uploading' ? 'Uploading…' : 'Pending'}
                </span>
                {cf.status !== 'uploading' && (
                  <button
                    onClick={() => removeFile(cf.id)}
                    className="text-slate-600 hover:text-slate-300 transition-colors shrink-0"
                  >
                    <X size={13} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Feedback toggle */}
      {showFeedback ? (
        <div className="mb-4">
          <label className="text-sm font-medium text-slate-300 mb-2 block">
            Feedback / Change Requests (optional)
          </label>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="e.g. 'Add a section on GDPR compliance requirements' or 'Remove the mobile app scope'"
            rows={4}
            className="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-300 placeholder-slate-600 focus:outline-none focus:border-indigo-500 resize-none"
          />
        </div>
      ) : (
        <button
          onClick={() => setShowFeedback(true)}
          className="flex items-center gap-2 text-sm text-slate-400 hover:text-white mb-4 transition-colors"
        >
          <MessageSquare size={15} />
          Add feedback or change requests
        </button>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleConfirm}
          disabled={confirming || contextFiles.some((cf) => cf.status === 'uploading')}
          className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-500 text-white font-semibold px-6 py-3 rounded-xl transition-colors text-sm shadow-lg shadow-emerald-500/20 cursor-pointer disabled:cursor-not-allowed"
        >
          {confirming ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <CheckCircle2 size={16} />
          )}
          {confirming ? 'Confirming…' : 'Confirm BRD & Generate Plan'}
        </button>
        <p className="text-xs text-slate-500">
          {contextFiles.some((cf) => cf.status === 'uploading')
            ? 'Waiting for uploads to finish…'
            : 'This will trigger plan generation using Gemini AI'}
        </p>
      </div>
    </div>
  );
}
