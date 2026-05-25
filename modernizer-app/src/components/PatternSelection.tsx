import { ArrowRight, CheckCircle2, ChevronRight } from 'lucide-react';
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
        <div className="inline-flex items-center gap-2 text-xs font-medium text-indigo-400 bg-indigo-400/10 border border-indigo-400/20 rounded-full px-3 py-1.5 mb-6">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
          Powered by Gemini AI
        </div>
        <h2 className="text-4xl font-bold text-white mb-4 tracking-tight">
          Choose a Modernization Pattern
        </h2>
        <p className="text-slate-400 text-lg max-w-2xl mx-auto">
          Select your migration path. Our AI agent will reverse-engineer your codebase,
          generate a BRD and migration plan, then produce the target code — with you in control at every step.
        </p>
      </div>

      {/* Pattern Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {PATTERNS.map((pattern) => (
          <button
            key={pattern.id}
            onClick={() => onSelect(pattern.id)}
            className={`
              group relative text-left rounded-2xl border border-slate-800 bg-slate-900
              hover:border-indigo-500/50 hover:bg-slate-800/80
              transition-all duration-300 overflow-hidden cursor-pointer
              focus:outline-none focus:ring-2 focus:ring-indigo-500/50
            `}
          >
            {/* Gradient overlay */}
            <div className={`absolute inset-0 bg-gradient-to-br ${pattern.gradient} opacity-0 group-hover:opacity-100 transition-opacity duration-300`} />

            <div className="relative p-6">
              {/* Icon */}
              <div className={`w-12 h-12 rounded-xl ${pattern.iconBg} flex items-center justify-center mb-5 shadow-lg`}>
                <span className="text-white font-bold text-lg">
                  {pattern.from.charAt(0)}→{pattern.to.charAt(0)}
                </span>
              </div>

              {/* Badges */}
              <div className="flex items-center gap-2 mb-4">
                <span className={`text-xs font-medium border rounded-full px-2.5 py-0.5 ${pattern.fromBadge}`}>
                  {pattern.from}
                </span>
                <ArrowRight size={14} className="text-slate-500" />
                <span className={`text-xs font-medium border rounded-full px-2.5 py-0.5 ${pattern.toBadge}`}>
                  {pattern.to}
                </span>
              </div>

              {/* Title & description */}
              <h3 className="text-lg font-semibold text-white mb-2 group-hover:text-indigo-300 transition-colors">
                {pattern.title}
              </h3>
              <p className="text-sm text-slate-400 leading-relaxed mb-5">
                {pattern.description}
              </p>

              {/* Benefits */}
              <ul className="space-y-1.5 mb-6">
                {pattern.benefits.map((b) => (
                  <li key={b} className="flex items-start gap-2 text-xs text-slate-400">
                    <CheckCircle2 size={13} className="text-emerald-400 mt-0.5 shrink-0" />
                    {b}
                  </li>
                ))}
              </ul>

              {/* CTA */}
              <div className="flex items-center gap-1.5 text-sm font-medium text-indigo-400 group-hover:text-indigo-300">
                Start migration
                <ChevronRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* How it works */}
      <div className="mt-16 border border-slate-800 rounded-2xl bg-slate-900/50 p-8">
        <h3 className="text-sm font-semibold text-slate-300 mb-6 text-center uppercase tracking-wider">
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
              <div className="w-10 h-10 rounded-full bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center text-xs font-bold text-indigo-400 mx-auto mb-3">
                {item.step}
              </div>
              <p className="text-sm font-medium text-white mb-1">{item.label}</p>
              <p className="text-xs text-slate-500">{item.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
