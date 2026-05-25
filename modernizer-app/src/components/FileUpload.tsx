import { useRef, useState } from 'react';
import { Upload, FolderOpen, FileCode2, X, ArrowLeft, Loader2 } from 'lucide-react';
import type { PatternId } from '../types';
import { PATTERNS } from '../data/patterns';
import { uploadRepository } from '../api';

interface Props {
  pattern: PatternId;
  onSessionCreated: (sessionId: string) => void;
  onBack: () => void;
}

export function FileUpload({ pattern, onSessionCreated, onBack }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const config = PATTERNS.find((p) => p.id === pattern)!;

  const handleFile = (f: File) => {
    setError(null);
    if (!f.name.endsWith('.zip') && !f.name.match(/\.(java|go|mod|gradle|xml|properties|yaml|yml|bwp|process|substvar|xsd|wsdl|xslt|xsl)$/)) {
      setError('Please upload a .zip archive of your project or a single source file.');
      return;
    }
    setFile(f);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) handleFile(dropped);
  };

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) handleFile(selected);
  };

  const handleStart = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const { session_id } = await uploadRepository(pattern, file);
      onSessionCreated(session_id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Upload failed. Please try again.');
      setUploading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto px-6 py-16">
      {/* Back */}
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-white mb-8 transition-colors"
      >
        <ArrowLeft size={15} />
        Back to patterns
      </button>

      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-3">
          <div className={`w-10 h-10 rounded-xl ${config.iconBg} flex items-center justify-center text-white font-bold text-sm`}>
            {config.from.charAt(0)}→{config.to.charAt(0)}
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">{config.title}</h2>
            <p className="text-sm text-slate-400">Upload your repository to begin</p>
          </div>
        </div>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => !file && fileRef.current?.click()}
        className={`
          relative border-2 border-dashed rounded-2xl p-10 text-center transition-all duration-200
          ${dragging ? 'border-indigo-500 bg-indigo-500/10' : 'border-slate-700 hover:border-slate-600 bg-slate-900'}
          ${!file ? 'cursor-pointer' : ''}
        `}
      >
        <input
          ref={fileRef}
          type="file"
          accept=".zip,.java,.go,.mod,.xml,.gradle,.properties,.yaml,.yml,.bwp,.process,.substvar,.xsd,.wsdl,.xslt,.xsl"
          className="hidden"
          onChange={onInputChange}
        />

        {file ? (
          <div className="flex items-center justify-between bg-slate-800 rounded-xl px-4 py-3">
            <div className="flex items-center gap-3">
              <FileCode2 size={20} className="text-indigo-400" />
              <div className="text-left">
                <p className="text-sm font-medium text-white">{file.name}</p>
                <p className="text-xs text-slate-400">{(file.size / 1024).toFixed(1)} KB</p>
              </div>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); setFile(null); }}
              className="text-slate-500 hover:text-red-400 transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        ) : (
          <>
            <div className="w-14 h-14 rounded-2xl bg-slate-800 border border-slate-700 flex items-center justify-center mx-auto mb-4">
              <Upload size={24} className="text-slate-400" />
            </div>
            <p className="text-white font-medium mb-1">Drop your project here</p>
            <p className="text-sm text-slate-400 mb-4">
              Upload a <span className="text-white font-medium">.zip</span> archive of your repository
            </p>
            <div className="flex items-center justify-center gap-3">
              <button
                onClick={(e) => { e.stopPropagation(); fileRef.current?.click(); }}
                className="flex items-center gap-2 text-sm bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 px-4 py-2 rounded-lg transition-colors"
              >
                <FolderOpen size={15} />
                Browse files
              </button>
            </div>
            <p className="text-xs text-slate-600 mt-4">
              Supported: .zip (recommended), .java, .go, .xml, .gradle, .bwp, .substvar, .xsd, .wsdl
            </p>
          </>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mt-4 text-sm text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {/* Info box */}
      <div className="mt-6 bg-slate-900 border border-slate-800 rounded-xl p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">What happens next</p>
        <ol className="space-y-1.5">
          {['AI reverse-engineers your codebase', 'You review and confirm the BRD', 'You review and confirm the migration plan', 'AI generates the fully migrated code'].map((s, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-slate-400">
              <span className="w-4 h-4 rounded-full bg-indigo-500/20 text-indigo-400 text-[10px] flex items-center justify-center shrink-0 mt-0.5">
                {i + 1}
              </span>
              {s}
            </li>
          ))}
        </ol>
      </div>

      {/* Start button */}
      <button
        disabled={!file || uploading}
        onClick={handleStart}
        className={`
          mt-6 w-full flex items-center justify-center gap-2 rounded-xl py-3.5 text-sm font-semibold transition-all
          ${file && !uploading
            ? 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-500/25 cursor-pointer'
            : 'bg-slate-800 text-slate-500 cursor-not-allowed'
          }
        `}
      >
        {uploading ? (
          <>
            <Loader2 size={16} className="animate-spin" />
            Uploading…
          </>
        ) : (
          <>
            Start Modernization
            <ArrowLeft size={16} className="rotate-180" />
          </>
        )}
      </button>
    </div>
  );
}
