import { useEffect, useMemo, useRef, useState } from 'react';
import { Upload, FolderOpen, FileCode2, X, ArrowLeft, Loader2, Palette, FileText, ImagePlus } from 'lucide-react';
import type { PatternId, JavaMigrationOptions } from '../types';
import { PATTERNS } from '../data/patterns';
import { uploadRepository } from '../api';

// UX designs — the limits mirror modernizer-backend/agents/shared/ux_designs.py.
const UX_PATTERNS: PatternId[] = ['jsp-to-react-bff'];
const UX_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.pdf'];
const UX_MAX_FILES = 10;
const UX_MAX_FILE_BYTES = 5 * 1024 * 1024;
const UX_MAX_TOTAL_BYTES = 15 * 1024 * 1024;

/** Why this set of UX design files can't be uploaded, or null if it can. */
function uxProblem(files: File[]): string | null {
  if (files.length > UX_MAX_FILES) return `Attach at most ${UX_MAX_FILES} UX design files.`;
  for (const f of files) {
    const name = f.name.toLowerCase();
    if (!UX_EXTENSIONS.some((ext) => name.endsWith(ext))) {
      return `"${f.name}" isn't a supported design file — use PNG, JPG, WebP, GIF or PDF.`;
    }
    if (f.size === 0) return `"${f.name}" is empty.`;
    if (f.size > UX_MAX_FILE_BYTES) return `"${f.name}" is larger than 5 MB.`;
  }
  if (files.reduce((sum, f) => sum + f.size, 0) > UX_MAX_TOTAL_BYTES) {
    return 'UX design files can add up to 15 MB at most.';
  }
  return null;
}

interface Props {
  pattern: PatternId;
  options?: JavaMigrationOptions | null;
  onSessionCreated: (sessionId: string) => void;
  onBack: () => void;
}

export function FileUpload({ pattern, options, onSessionCreated, onBack }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const uxRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uxDragging, setUxDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uxFiles, setUxFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const config = PATTERNS.find((p) => p.id === pattern)!;
  const supportsUx = UX_PATTERNS.includes(pattern);

  // Thumbnail URLs for image designs; released whenever the list changes or the screen unmounts.
  const uxPreviews = useMemo(
    () => uxFiles.map((f) => (f.type.startsWith('image/') ? URL.createObjectURL(f) : null)),
    [uxFiles],
  );
  useEffect(() => () => uxPreviews.forEach((url) => url && URL.revokeObjectURL(url)), [uxPreviews]);

  const handleFile = (f: File) => {
    setError(null);
    if (!f.name.endsWith('.zip') && !f.name.match(/\.(java|gradle|kts|xml|properties|yaml|yml|json|sql|pks|pkb|ddl|plsql|bwp|process|substvar|conf|config|jsp|jspf|jspx|tag|tld)$/)) {
      setError('Please upload a .zip archive of your project or a single source file.');
      return;
    }
    setFile(f);
  };

  const addUxFiles = (incoming: File[]) => {
    if (incoming.length === 0) return;
    const next = [...uxFiles, ...incoming];
    const problem = uxProblem(next);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    setUxFiles(next);
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

  const onUxDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setUxDragging(false);
    addUxFiles(Array.from(e.dataTransfer.files));
  };

  const onUxInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    addUxFiles(Array.from(e.target.files ?? []));
    e.target.value = ''; // so picking the same file again still fires onChange
  };

  const handleStart = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const { session_id } = await uploadRepository(pattern, file, options, supportsUx ? uxFiles : []);
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
        className="flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900 mb-8 transition-colors"
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
            <h2 className="text-xl font-bold text-slate-900">{config.title}</h2>
            <p className="text-sm text-slate-600">Upload your repository to begin</p>
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
          ${dragging ? 'border-red-500 bg-red-500/10' : 'border-slate-900/15 hover:border-slate-900/25 glass'}
          ${!file ? 'cursor-pointer' : ''}
        `}
      >
        <input
          ref={fileRef}
          type="file"
          accept=".zip,.java,.gradle,.kts,.xml,.properties,.yaml,.yml,.json,.sql,.pks,.pkb,.ddl,.plsql,.bwp,.process,.substvar,.conf,.config,.jsp,.jspf,.jspx,.tag,.tld"
          className="hidden"
          onChange={onInputChange}
        />

        {file ? (
          <div className="flex items-center justify-between bg-slate-900/5 border border-slate-900/10 rounded-xl px-4 py-3">
            <div className="flex items-center gap-3">
              <FileCode2 size={20} className="text-red-600" />
              <div className="text-left">
                <p className="text-sm font-medium text-slate-900">{file.name}</p>
                <p className="text-xs text-slate-600">{(file.size / 1024).toFixed(1)} KB</p>
              </div>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); setFile(null); }}
              className="text-slate-500 hover:text-red-600 transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        ) : (
          <>
            <div className="w-14 h-14 rounded-2xl bg-slate-900/5 border border-slate-900/10 flex items-center justify-center mx-auto mb-4">
              <Upload size={24} className="text-slate-600" />
            </div>
            <p className="text-slate-900 font-medium mb-1">Drop your project here</p>
            <p className="text-sm text-slate-600 mb-4">
              Upload a <span className="text-slate-900 font-medium">.zip</span> archive of your repository
            </p>
            <div className="flex items-center justify-center gap-3">
              <button
                onClick={(e) => { e.stopPropagation(); fileRef.current?.click(); }}
                className="flex items-center gap-2 text-sm bg-slate-900/5 hover:bg-slate-900/10 border border-slate-900/10 text-slate-700 px-4 py-2 rounded-lg transition-colors cursor-pointer"
              >
                <FolderOpen size={15} />
                Browse files
              </button>
            </div>
            <p className="text-xs text-slate-600 mt-4">
              Supported: .zip (recommended), .java, .xml, .gradle, .sql, .bwp, .substvar, .properties
            </p>
          </>
        )}
      </div>

      {/* UX designs (JSP → React only) */}
      {supportsUx && (
        <div
          onDragOver={(e) => { e.preventDefault(); setUxDragging(true); }}
          onDragLeave={() => setUxDragging(false)}
          onDrop={onUxDrop}
          className={`mt-5 rounded-2xl border p-5 transition-colors ${
            uxDragging ? 'border-red-500 bg-red-500/10' : 'border-slate-900/10 glass'
          }`}
        >
          <div className="flex items-start justify-between gap-3 mb-3">
            <div>
              <p className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
                <Palette size={15} className="text-slate-500" />
                UX designs
                <span className="text-xs font-normal text-slate-500">(optional)</span>
              </p>
              <p className="text-xs text-slate-600 mt-1">
                Add mockups or design exports and the React UI will be built to match them — layout, components,
                colours and typography. The JSP source still defines the data and behaviour.
              </p>
            </div>
            <button
              onClick={() => uxRef.current?.click()}
              disabled={uxFiles.length >= UX_MAX_FILES}
              className="shrink-0 flex items-center gap-1.5 text-xs bg-slate-900/5 hover:bg-slate-900/10 border border-slate-900/10 text-slate-700 px-3 py-1.5 rounded-lg transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <ImagePlus size={13} />
              Add designs
            </button>
          </div>
          <input
            ref={uxRef}
            type="file"
            multiple
            accept={UX_EXTENSIONS.join(',')}
            className="hidden"
            onChange={onUxInputChange}
          />

          {uxFiles.length > 0 ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {uxFiles.map((f, i) => (
                <div
                  key={`${f.name}-${f.size}-${i}`}
                  className="relative rounded-xl border border-slate-900/10 bg-white/60 overflow-hidden"
                >
                  {uxPreviews[i] ? (
                    <img src={uxPreviews[i]!} alt={f.name} className="w-full h-24 object-cover bg-slate-900/5" />
                  ) : (
                    <div className="w-full h-24 flex flex-col items-center justify-center gap-1 bg-slate-900/5 text-slate-500">
                      <FileText size={22} />
                      <span className="text-[10px] font-semibold uppercase">PDF</span>
                    </div>
                  )}
                  <p className="text-[11px] text-slate-700 truncate px-2 py-1.5" title={f.name}>{f.name}</p>
                  <button
                    onClick={() => setUxFiles(uxFiles.filter((_, j) => j !== i))}
                    aria-label={`Remove ${f.name}`}
                    className="absolute top-1.5 right-1.5 w-6 h-6 rounded-full bg-white/90 border border-slate-900/10 flex items-center justify-center text-slate-600 hover:text-red-600 transition-colors cursor-pointer"
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500">
              Drop files here · PNG, JPG, WebP, GIF or PDF · up to {UX_MAX_FILES} files, 5 MB each
            </p>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mt-4 text-sm text-red-600 bg-red-400/10 border border-red-400/20 rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {/* Info box */}
      <div className="mt-6 glass rounded-xl p-4">
        <p className="text-xs font-semibold text-slate-600 uppercase tracking-wider mb-2">What happens next</p>
        <ol className="space-y-1.5">
          {[
            'A deterministic scan builds a dependency graph & migration groups',
            'AI reverse-engineers your codebase — BRD, tech spec & test inventory',
            'You review, edit, or ask the planner to refine the BRD and plan',
            'Migration agents apply the plan, then build/fix in a loop until it compiles',
          ].map((s, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-slate-600">
              <span className="w-4 h-4 rounded-full bg-red-500/20 text-red-600 text-[10px] flex items-center justify-center shrink-0 mt-0.5">
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
            ? 'bg-red-600 hover:bg-red-500 text-white shadow-lg shadow-red-500/25 cursor-pointer'
            : 'bg-slate-900/5 text-slate-500 cursor-not-allowed'
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
