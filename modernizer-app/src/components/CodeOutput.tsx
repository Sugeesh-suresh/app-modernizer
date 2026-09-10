import { useState } from 'react';
import {
  Code2, Copy, CheckCheck, FolderTree, PartyPopper, FileArchive, FileText,
  ChevronDown, ChevronUp, GitCompare, PlusCircle, MinusCircle, PencilLine,
  Search, Sparkles,
} from 'lucide-react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { GeneratedFile, ChangedFile } from '../types';
import { codeZipDownloadUrl } from '../api';

interface Props {
  sessionId: string;
  files: GeneratedFile[];
  changedFiles: ChangedFile[];
  pattern: string;
  /** code_reviewer_agent's independent findings (runs after the build loop) */
  codeReview?: string;
  /** reporter_agent's closing summary */
  report?: string;
  /** skill_curator_agent's summary of skill-library refinements (runs last) */
  skillCuratorSummary?: string;
  onStartNew: () => void;
}

const PROSE_CLS = `px-5 pb-5 max-h-[40vh] overflow-y-auto prose prose-invert prose-sm max-w-none
  prose-headings:text-slate-900 prose-headings:font-semibold
  prose-h1:text-xl prose-h2:text-lg prose-h3:text-base
  prose-p:text-slate-700 prose-li:text-slate-700
  prose-strong:text-slate-900 prose-code:text-red-700 prose-code:bg-slate-900/10 prose-code:px-1 prose-code:rounded
  prose-a:text-red-600 prose-hr:border-slate-900/10
  prose-table:text-slate-700 prose-th:text-slate-800 prose-td:border-slate-900/10 prose-th:border-slate-900/15`;

function CollapsiblePanel({
  title, icon, content, defaultOpen,
}: { title: string; icon: React.ReactNode; content: string; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="glass rounded-2xl mb-6 overflow-hidden">
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-center justify-between px-5 py-3 text-left">
        <div className="flex items-center gap-2">
          {icon}
          <span className="text-sm font-semibold text-slate-900">{title}</span>
        </div>
        {open ? <ChevronUp size={15} className="text-slate-500" /> : <ChevronDown size={15} className="text-slate-500" />}
      </button>
      {open && (
        <div className={PROSE_CLS}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}

const STATUS_ICON: Record<ChangedFile['status'], React.ReactNode> = {
  added: <PlusCircle size={12} className="text-emerald-600" />,
  modified: <PencilLine size={12} className="text-amber-600" />,
  deleted: <MinusCircle size={12} className="text-red-600" />,
};

function DiffView({ diff }: { diff: string }) {
  const lines = diff.split('\n');
  return (
    <div className="flex-1 overflow-auto bg-[#1e1e1e] font-mono text-[11px] leading-relaxed">
      {lines.map((line, i) => {
        let cls = 'text-slate-300';
        if (line.startsWith('+++') || line.startsWith('---')) cls = 'text-slate-500';
        else if (line.startsWith('@@')) cls = 'text-cyan-400 bg-cyan-500/10';
        else if (line.startsWith('+')) cls = 'text-emerald-300 bg-emerald-500/10';
        else if (line.startsWith('-')) cls = 'text-red-300 bg-red-500/10';
        return (
          <div key={i} className={`px-4 whitespace-pre-wrap ${cls}`}>
            {line || ' '}
          </div>
        );
      })}
    </div>
  );
}

const LANG_MAP: Record<string, string> = {
  java: 'java',
  go: 'go',
  xml: 'xml',
  properties: 'properties',
  yaml: 'yaml',
  yml: 'yaml',
  json: 'json',
  kt: 'kotlin',
  gradle: 'groovy',
  mod: 'go',
  txt: 'text',
  cs: 'csharp',
  csproj: 'xml',
  sln: 'text',
  config: 'xml',
  razor: 'markup',
  cshtml: 'markup',
};

function normaliseLanguage(lang: string): string {
  return LANG_MAP[lang.toLowerCase()] ?? lang.toLowerCase();
}

export function CodeOutput({
  sessionId, files, changedFiles, pattern, codeReview, report, skillCuratorSummary, onStartNew,
}: Props) {
  const [panel, setPanel] = useState<'files' | 'changes'>(changedFiles.length > 0 ? 'changes' : 'files');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [selectedChangeIndex, setSelectedChangeIndex] = useState(0);
  const [copied, setCopied] = useState(false);

  const selected = files[selectedIndex];
  const selectedChange = changedFiles[selectedChangeIndex];

  const handleCopy = async () => {
    await navigator.clipboard.writeText(selected?.content ?? '');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="max-w-7xl mx-auto px-6 py-10">
      {/* Success header */}
      <div className="glass bg-gradient-to-r from-emerald-500/10 to-red-500/10 border border-emerald-500/20 rounded-2xl p-6 mb-6 flex items-start gap-4">
        <div className="w-11 h-11 rounded-xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center shrink-0">
          <PartyPopper size={20} className="text-emerald-600" />
        </div>
        <div className="flex-1">
          <h2 className="text-xl font-bold text-slate-900 mb-1">Migration is complete</h2>
          <p className="text-sm text-slate-600">
            {changedFiles.length} file{changedFiles.length !== 1 ? 's' : ''} changed out of {files.length} total for{' '}
            <span className="text-slate-900 font-medium">{pattern}</span> migration.
            Review the changes below and download when ready.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <a
            href={codeZipDownloadUrl(sessionId)}
            download
            className="flex items-center gap-2 bg-slate-900/5 hover:bg-slate-900/10 border border-slate-900/10 text-slate-700 px-4 py-2 rounded-lg text-sm transition-colors"
          >
            <FileArchive size={14} />
            Download ZIP
          </a>
          <button
            onClick={onStartNew}
            className="flex items-center gap-2 bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            New Migration
          </button>
        </div>
      </div>

      {/* code_reviewer_agent's independent findings -- runs after the build loop */}
      {codeReview && (
        <CollapsiblePanel
          title="Code Review Findings"
          icon={<Search size={15} className="text-slate-600" />}
          content={codeReview}
          defaultOpen={false}
        />
      )}

      {/* reporter_agent's closing summary */}
      {report && (
        <CollapsiblePanel
          title="Migration Report"
          icon={<FileText size={15} className="text-slate-600" />}
          content={report}
          defaultOpen={true}
        />
      )}

      {/* skill_curator_agent's summary -- the last thing the pipeline does */}
      {skillCuratorSummary && (
        <CollapsiblePanel
          title="Skill Library Updates"
          icon={<Sparkles size={15} className="text-violet-600" />}
          content={skillCuratorSummary}
          defaultOpen={false}
        />
      )}

      {/* Panel toggle */}
      <div className="flex gap-1 mb-4">
        <button
          onClick={() => setPanel('changes')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            panel === 'changes' ? 'bg-red-600 text-white' : 'bg-slate-900/5 text-slate-600 hover:text-slate-900'
          }`}
        >
          <GitCompare size={14} />
          Changed Files ({changedFiles.length})
        </button>
        <button
          onClick={() => setPanel('files')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            panel === 'files' ? 'bg-red-600 text-white' : 'bg-slate-900/5 text-slate-600 hover:text-slate-900'
          }`}
        >
          <FolderTree size={14} />
          All Output Files ({files.length})
        </button>
      </div>

      <div className="flex gap-4 h-[65vh]">
        {/* File / change list */}
        <div className="w-64 shrink-0 glass rounded-2xl overflow-hidden flex flex-col">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-900/10 glass-inset">
            {panel === 'changes' ? <GitCompare size={14} className="text-slate-500" /> : <FolderTree size={14} className="text-slate-500" />}
            <span className="text-xs font-medium text-slate-600">{panel === 'changes' ? 'Changed Files' : 'Output Files'}</span>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {panel === 'changes' && changedFiles.length === 0 && (
              <p className="text-xs text-slate-500 px-2 py-4 text-center">No files were changed.</p>
            )}
            {(panel === 'changes' ? changedFiles : files).map((f, i) => {
              const parts = f.path.split('/');
              const name = parts.pop() ?? f.path;
              const dir = parts.join('/');
              const isSelected = panel === 'changes' ? i === selectedChangeIndex : i === selectedIndex;
              return (
                <button
                  key={i}
                  onClick={() => (panel === 'changes' ? setSelectedChangeIndex(i) : setSelectedIndex(i))}
                  className={`w-full text-left px-3 py-2 rounded-lg transition-colors mb-0.5 ${
                    isSelected ? 'bg-red-500/20 border border-red-500/30' : 'hover:bg-slate-900/5'
                  }`}
                >
                  {dir && (
                    <p className="text-[10px] text-slate-600 truncate mb-0.5">{dir}/</p>
                  )}
                  <div className="flex items-center gap-2">
                    {panel === 'changes'
                      ? STATUS_ICON[(f as ChangedFile).status]
                      : <Code2 size={12} className={isSelected ? 'text-red-600' : 'text-slate-500'} />}
                    <span className={`text-xs font-medium truncate ${isSelected ? 'text-red-700' : 'text-slate-700'}`}>
                      {name}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Viewer: diff for Changed Files, syntax-highlighted source for All Output Files */}
        <div className="flex-1 glass rounded-2xl overflow-hidden flex flex-col">
          {panel === 'changes' ? (
            selectedChange ? (
              <>
                <div className="flex items-center justify-between px-4 py-3 border-b border-slate-900/10 glass-inset shrink-0">
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-slate-700 font-mono">{selectedChange.path}</span>
                    <span className="text-[10px] text-slate-500 bg-slate-900/10 rounded px-1.5 py-0.5 flex items-center gap-1">
                      {STATUS_ICON[selectedChange.status]}
                      {selectedChange.status}
                    </span>
                  </div>
                </div>
                <DiffView diff={selectedChange.diff} />
              </>
            ) : (
              <div className="flex items-center justify-center h-full text-slate-600 text-sm">
                Select a changed file to view its diff
              </div>
            )
          ) : selected ? (
            <>
              <div className="flex items-center justify-between px-4 py-3 border-b border-slate-900/10 glass-inset shrink-0">
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-700 font-mono">{selected.path}</span>
                  <span className="text-[10px] text-slate-500 bg-slate-900/10 rounded px-1.5 py-0.5">
                    {normaliseLanguage(selected.language)}
                  </span>
                </div>
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900 transition-colors"
                >
                  {copied ? (
                    <><CheckCheck size={13} className="text-emerald-600" /><span className="text-emerald-600">Copied</span></>
                  ) : (
                    <><Copy size={13} />Copy</>
                  )}
                </button>
              </div>
              <div className="flex-1 overflow-auto bg-[#1e1e1e]">
                <SyntaxHighlighter
                  language={normaliseLanguage(selected.language)}
                  style={vscDarkPlus}
                  customStyle={{
                    margin: 0,
                    borderRadius: 0,
                    background: 'transparent',
                    fontSize: '12px',
                    lineHeight: '1.6',
                    padding: '20px',
                    minHeight: '100%',
                  }}
                  showLineNumbers
                  lineNumberStyle={{ color: '#6b7280', minWidth: '3em', paddingRight: '1em' }}
                >
                  {selected.content}
                </SyntaxHighlighter>
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center h-full text-slate-600 text-sm">
              Select a file to view
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
