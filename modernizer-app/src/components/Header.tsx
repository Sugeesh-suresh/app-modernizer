import { Cpu, Zap } from 'lucide-react';

export function Header() {
  return (
    <header className="glass-strong border-b border-slate-900/10 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center gap-3">
        <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-gradient-to-br from-red-500 to-red-800 shadow-lg shadow-red-500/30">
          <Cpu size={18} className="text-white" />
        </div>
        <div>
          <h1 className="text-base font-semibold text-slate-900 leading-none">Stella Modernizer</h1>
          <p className="text-xs text-slate-500 mt-0.5">Agentic code migration platform</p>
        </div>
        <div className="ml-auto flex items-center gap-1.5 text-xs text-emerald-600 bg-emerald-400/10 border border-emerald-400/20 rounded-full px-3 py-1">
          <Zap size={11} />
          AI Agent Active
        </div>
      </div>
    </header>
  );
}
