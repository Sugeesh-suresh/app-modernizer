import { ArrowRight } from 'lucide-react';
import { PATTERNS } from '../data/patterns';
import type { PatternId } from '../types';

interface Props {
  onSelect: (id: PatternId) => void;
}

export function PatternSelection({ onSelect }: Props) {
  return (
    <div className="max-w-7xl mx-auto px-6 py-16">
      {/* Hero */}
      <div className="text-center mb-14">
        <div className="inline-flex items-center gap-2 text-xs font-medium text-red-600 bg-red-400/10 border border-red-400/20 rounded-full px-3 py-1.5 mb-6">
          <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
          Powered by AI
        </div>
        <h2 className="text-4xl font-bold text-slate-900 mb-4 tracking-tight">
          Choose a Modernization Pattern
        </h2>
        <p className="text-slate-600 text-lg max-w-2xl mx-auto">
          Select your migration path. Our AI agent will reverse-engineer your codebase,
          generate a BRD and migration plan, then produce the target code — with you in control at every step.
        </p>
      </div>

      {/* Pattern Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {PATTERNS.map((pattern) => (
          <button
            key={pattern.id}
            onClick={() => onSelect(pattern.id)}
            className={`
              group relative text-left rounded-2xl glass
              hover:border-red-400/40 hover:bg-slate-900/[0.03]
              transition-all duration-300 overflow-hidden cursor-pointer
              focus:outline-none focus:ring-2 focus:ring-red-500/50
            `}
          >
            {/* Gradient overlay */}
            <div className={`absolute inset-0 bg-gradient-to-br ${pattern.gradient} opacity-0 group-hover:opacity-100 transition-opacity duration-300`} />

            <div className="relative p-5 flex items-center justify-between gap-3">
              <h3 className="text-base font-semibold text-slate-900 group-hover:text-red-700 transition-colors">
                {pattern.title}
              </h3>

              <div
                aria-hidden="true"
                className="flex items-center justify-center w-9 h-9 rounded-full bg-slate-900 text-white shrink-0 transition-all duration-300 group-hover:bg-red-600 group-hover:scale-105"
              >
                <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* How it works */}
      <div className="mt-16 glass rounded-2xl p-8">
        <h3 className="text-sm font-semibold text-slate-700 mb-6 text-center uppercase tracking-wider">
          How the agentic workflow works
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          {[
            { step: '01', label: 'Upload Repo', desc: 'Upload your project as a ZIP file' },
            { step: '02', label: 'Reverse Engineer', desc: 'AI analyses architecture & business logic' },
            { step: '03', label: 'Review BRD & Plan', desc: 'Confirm requirements and migration plan' },
            { step: '04', label: 'Generate Code', desc: 'AI produces the fully migrated codebase' },
          ].map((item, i) => (
            <div key={i} className="text-center">
              <div className="w-10 h-10 rounded-full bg-red-500/20 border border-red-500/30 flex items-center justify-center text-xs font-bold text-red-600 mx-auto mb-3">
                {item.step}
              </div>
              <p className="text-sm font-medium text-slate-900 mb-1">{item.label}</p>
              <p className="text-xs text-slate-500">{item.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
