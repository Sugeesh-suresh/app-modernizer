import { Cpu, Zap } from 'lucide-react';

export function Header() {
  return (
    <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center gap-3">
        <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 shadow-lg shadow-indigo-500/30">
          <Cpu size={18} className="text-white" />
        </div>
        <div>
          <h1 className="text-base font-semibold text-white leading-none">App Modernizer</h1>
          <p className="text-xs text-slate-500 mt-0.5">Agentic code migration powered by Gemini</p>
        </div>
        <div className="ml-auto flex items-center gap-1.5 text-xs text-emerald-400 bg-emerald-400/10 border border-emerald-400/20 rounded-full px-3 py-1">
          <Zap size={11} />
          AI Agent Active
        </div>
      </div>
    </header>
  );
}
