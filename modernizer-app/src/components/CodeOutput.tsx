import { useState } from 'react';
import { Code2, Copy, CheckCheck, Download, FolderTree, PartyPopper, TestTube2, CheckCircle2, AlertTriangle } from 'lucide-react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { GeneratedFile, ValidationState } from '../types';

interface Props {
  files: GeneratedFile[];
  testFiles: GeneratedFile[];
  pattern: string;
  validation: ValidationState | null;
  onStartNew: () => void;
}

type Tab = 'source' | 'tests';

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
};

function normaliseLanguage(lang: string): string {
  return LANG_MAP[lang.toLowerCase()] ?? lang.toLowerCase();
}

export function CodeOutput({ files, testFiles, pattern, validation, onStartNew }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('source');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [copied, setCopied] = useState(false);

  const displayedFiles = activeTab === 'tests' ? testFiles : files;
  const selected = displayedFiles[selectedIndex];

  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab);
    setSelectedIndex(0);
    setCopied(false);
  };

  const handleCopy = async () => {
    await navigator.clipboard.writeText(selected?.content ?? '');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadAll = () => {
    const allFiles = [...files, ...testFiles];
    allFiles.forEach((f) => {
      const blob = new Blob([f.content], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = f.path.split('/').pop() ?? 'file.txt';
      a.click();
      URL.revokeObjectURL(url);
    });
  };

  return (
    <div className="max-w-7xl mx-auto px-6 py-10">
      {/* Success header */}
      <div className="bg-gradient-to-r from-emerald-500/10 to-indigo-500/10 border border-emerald-500/20 rounded-2xl p-6 mb-6 flex items-start gap-4">
        <div className="w-11 h-11 rounded-xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center shrink-0">
          <PartyPopper size={20} className="text-emerald-400" />
        </div>
        <div className="flex-1">
          <h2 className="text-xl font-bold text-white mb-1">Migration Complete!</h2>
          <p className="text-sm text-slate-400">
            {files.length} source file{files.length !== 1 ? 's' : ''} and {testFiles.length} test file{testFiles.length !== 1 ? 's' : ''} generated for <span className="text-white font-medium">{pattern}</span> migration.
            Review the output below and download when ready.
          </p>
          {validation && (
            <div className={`inline-flex items-center gap-1.5 mt-2 px-2.5 py-1 rounded-full text-xs font-medium ${
              validation.passed
                ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20'
                : 'bg-amber-500/15 text-amber-400 border border-amber-500/20'
            }`}>
              {validation.passed
                ? <CheckCircle2 size={11} />
                : <AlertTriangle size={11} />
              }
              {validation.passed
                ? `Tests validated in ${validation.attemptsUsed} attempt${validation.attemptsUsed !== 1 ? 's' : ''}`
                : `Best-effort result — ${validation.issues.length} issue${validation.issues.length !== 1 ? 's' : ''} after ${validation.attemptsUsed}/${validation.maxAttempts} attempts`
              }
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={handleDownloadAll}
            className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 px-4 py-2 rounded-lg text-sm transition-colors"
          >
            <Download size={14} />
            Download All
          </button>
          <button
            onClick={onStartNew}
            className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            New Migration
          </button>
        </div>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 mb-4">
        <button
          onClick={() => handleTabChange('source')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === 'source'
              ? 'bg-indigo-600 text-white'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          <Code2 size={14} />
          Source Files
          <span className="text-xs opacity-70">({files.length})</span>
        </button>
        <button
          onClick={() => handleTabChange('tests')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === 'tests'
              ? 'bg-rose-600 text-white'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          <TestTube2 size={14} />
          Test Files
          <span className="text-xs opacity-70">({testFiles.length})</span>
        </button>
      </div>

      <div className="flex gap-4 h-[65vh]">
        {/* File tree */}
        <div className="w-64 shrink-0 bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden flex flex-col">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800 bg-slate-950/50">
            <FolderTree size={14} className="text-slate-500" />
            <span className="text-xs font-medium text-slate-400">
              {activeTab === 'tests' ? 'Test Files' : 'Output Files'}
            </span>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {displayedFiles.map((f, i) => {
              const parts = f.path.split('/');
              const name = parts.pop() ?? f.path;
              const dir = parts.join('/');
              return (
                <button
                  key={i}
                  onClick={() => setSelectedIndex(i)}
                  className={`w-full text-left px-3 py-2 rounded-lg transition-colors mb-0.5 group ${
                    i === selectedIndex
                      ? activeTab === 'tests'
                        ? 'bg-rose-500/20 border border-rose-500/30'
                        : 'bg-indigo-500/20 border border-indigo-500/30'
                      : 'hover:bg-slate-800'
                  }`}
                >
                  {dir && (
                    <p className="text-[10px] text-slate-600 truncate mb-0.5">{dir}/</p>
                  )}
                  <div className="flex items-center gap-2">
                    {activeTab === 'tests'
                      ? <TestTube2 size={12} className={i === selectedIndex ? 'text-rose-400' : 'text-slate-500'} />
                      : <Code2 size={12} className={i === selectedIndex ? 'text-indigo-400' : 'text-slate-500'} />
                    }
                    <span className={`text-xs font-medium truncate ${
                      i === selectedIndex
                        ? activeTab === 'tests' ? 'text-rose-300' : 'text-indigo-300'
                        : 'text-slate-300'
                    }`}>
                      {name}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Code viewer */}
        <div className="flex-1 bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden flex flex-col">
          {selected ? (
            <>
              <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-950/50 shrink-0">
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-300 font-mono">{selected.path}</span>
                  <span className="text-[10px] text-slate-500 bg-slate-800 rounded px-1.5 py-0.5">
                    {normaliseLanguage(selected.language)}
                  </span>
                </div>
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors"
                >
                  {copied ? (
                    <><CheckCheck size={13} className="text-emerald-400" /><span className="text-emerald-400">Copied</span></>
                  ) : (
                    <><Copy size={13} />Copy</>
                  )}
                </button>
              </div>
              <div className="flex-1 overflow-auto">
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
                  lineNumberStyle={{ color: '#374151', minWidth: '3em', paddingRight: '1em' }}
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
