import { useState } from 'react';
import { ArrowRight, CheckCircle2, Loader2, Sparkles, FileSearch } from 'lucide-react';
import type { CompanionRecommendation, PatternId } from '../types';

interface Props {
  primaryLabel: string;
  recommendations: CompanionRecommendation[];
  onConfirm: (selected: PatternId[]) => Promise<void>;
}

export function CompanionSelection({ primaryLabel, recommendations, onConfirm }: Props) {
  const [selected, setSelected] = useState<Set<PatternId>>(
    () => new Set(recommendations.map((r) => r.pattern)),
  );
  const [confirming, setConfirming] = useState(false);

  const toggle = (pattern: PatternId) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(pattern)) next.delete(pattern);
      else next.add(pattern);
      return next;
    });
  };

  const handleConfirm = async () => {
    setConfirming(true);
    try {
      await onConfirm(Array.from(selected));
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto px-6 py-16">
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center text-white shrink-0">
            <Sparkles size={20} />
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate-900">Additional Migrations Detected</h2>
            <p className="text-sm text-slate-600">
              Alongside {primaryLabel}, this repository also depends on the following
            </p>
          </div>
        </div>
        <p className="text-xs text-slate-500">
          Detected deterministically by scanning the uploaded repository's build files and source
          for library/driver signatures — not an AI guess. Leave any of these unchecked to migrate
          {' '}{primaryLabel} on its own; you can always run them separately later.
        </p>
      </div>

      <div className="glass rounded-2xl p-5 mb-8 space-y-4">
        {recommendations.map((rec) => {
          const checked = selected.has(rec.pattern);
          return (
            <label
              key={rec.pattern}
              className="flex items-start gap-3 cursor-pointer rounded-xl border border-slate-900/10 hover:border-slate-900/20 p-3.5 transition-colors"
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggle(rec.pattern)}
                className="mt-0.5 w-4 h-4 accent-violet-600 cursor-pointer"
              />
              <div className="flex-1">
                <div className="flex items-center gap-1.5">
                  <FileSearch size={14} className="text-slate-500" />
                  <span className="text-sm font-semibold text-slate-900">{rec.label}</span>
                </div>
                <ul className="mt-1.5 space-y-0.5">
                  {rec.evidence.map((e, i) => (
                    <li key={i} className="text-xs text-slate-600 font-mono truncate">
                      {e}
                    </li>
                  ))}
                </ul>
              </div>
            </label>
          );
        })}
      </div>

      <button
        onClick={handleConfirm}
        disabled={confirming}
        className="w-full flex items-center justify-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:bg-slate-900/5 disabled:text-slate-500 text-white font-semibold px-6 py-3.5 rounded-xl transition-colors text-sm shadow-lg shadow-violet-500/25 cursor-pointer disabled:cursor-not-allowed"
      >
        {confirming ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
        {confirming ? 'Starting…' : 'Continue'}
        {!confirming && <ArrowRight size={16} />}
      </button>
    </div>
  );
}
