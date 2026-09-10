import { useState } from 'react';
import { ArrowLeft, ArrowRight, Rocket, Layers, FlaskConical, Leaf } from 'lucide-react';
import type { JavaMigrationOptions as Options, MigrationStrategy } from '../types';
import { INCREMENTAL_PHASES, phasesForRun } from '../data/incrementalStages';

interface Props {
  onContinue: (options: Options) => void;
  onBack: () => void;
}

export function JavaMigrationOptions({ onContinue, onBack }: Props) {
  const [strategy, setStrategy] = useState<MigrationStrategy>('bigbang');
  const [junitUpgrade, setJunitUpgrade] = useState(false);
  const [springbootUpgrade, setSpringbootUpgrade] = useState(false);
  // Step id → its position in the run the current options would produce
  const positions = new Map(
    phasesForRun(springbootUpgrade).flatMap((p) => p.steps.map((s) => [s.id, s.stage] as const)),
  );

  return (
    <div className="max-w-2xl mx-auto px-6 py-16">
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900 mb-8 transition-colors"
      >
        <ArrowLeft size={15} />
        Back to patterns
      </button>

      <div className="mb-8">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-amber-500 to-blue-600 flex items-center justify-center text-white font-bold text-[11px] leading-none shrink-0">
            8→25
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate-900">Migration Options</h2>
            <p className="text-sm text-slate-600">Choose your strategy before uploading the repository</p>
          </div>
        </div>
      </div>

      {/* Strategy */}
      <div className="glass rounded-2xl p-5 mb-5">
        <p className="text-xs font-semibold text-slate-600 uppercase tracking-wider mb-3">Migration Strategy</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <button
            onClick={() => setStrategy('bigbang')}
            className={`text-left rounded-xl border p-4 transition-all cursor-pointer ${
              strategy === 'bigbang'
                ? 'border-red-500/50 bg-red-500/5 ring-1 ring-red-500/30'
                : 'border-slate-900/10 hover:border-slate-900/20'
            }`}
          >
            <div className="flex items-center gap-2 mb-1.5">
              <Rocket size={15} className={strategy === 'bigbang' ? 'text-red-600' : 'text-slate-500'} />
              <span className="text-sm font-semibold text-slate-900">Bigbang</span>
            </div>
            <p className="text-xs text-slate-600">
              One pass, straight from Java 8 to Java 25. Faster, but every language/library change lands
              at once.
            </p>
          </button>

          <button
            onClick={() => setStrategy('incremental')}
            className={`text-left rounded-xl border p-4 transition-all cursor-pointer ${
              strategy === 'incremental'
                ? 'border-red-500/50 bg-red-500/5 ring-1 ring-red-500/30'
                : 'border-slate-900/10 hover:border-slate-900/20'
            }`}
          >
            <div className="flex items-center gap-2 mb-1.5">
              <Layers size={15} className={strategy === 'incremental' ? 'text-red-600' : 'text-slate-500'} />
              <span className="text-sm font-semibold text-slate-900">Incremental</span>
            </div>
            <p className="text-xs text-slate-600">
              Up to 8 staged builds across 4 phases — each step is applied, compiled, and fixed before the
              next begins.
            </p>
          </button>
        </div>

        {strategy === 'incremental' && (
          <div className="mt-4 space-y-2">
            {INCREMENTAL_PHASES.map((phase) => {
              const skipped = phase.steps.every((step) => !positions.has(step.id));
              return (
                <div
                  key={phase.phase}
                  className={`rounded-xl border px-3.5 py-2.5 transition-opacity ${
                    skipped ? 'border-dashed border-slate-900/15 opacity-55' : 'border-slate-900/10 bg-slate-900/[0.02]'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-xs font-semibold text-slate-800">
                      Phase {phase.phase} · {phase.title}
                    </span>
                    {skipped && (
                      <span className="text-[10px] text-slate-500 text-right">Enable the Spring Boot upgrade to include</span>
                    )}
                  </div>
                  <ul className="space-y-0.5">
                    {phase.steps.map((step) => {
                      const position = positions.get(step.id);
                      return (
                        <li
                          key={step.id}
                          className={`text-xs flex gap-1.5 ${position ? 'text-slate-600' : 'text-slate-400'}`}
                        >
                          <span className="font-mono text-slate-400 shrink-0 w-4 text-right">
                            {position ? `${position}.` : '–'}
                          </span>
                          <span>
                            {step.title}
                            <span className="text-slate-400"> — {step.detail}</span>
                            {!position && !skipped && (
                              <span className="text-[10px] text-slate-400"> · needs Spring Boot upgrade</span>
                            )}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Toggles */}
      <div className="glass rounded-2xl p-5 mb-8 space-y-4">
        <p className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Additional Upgrades</p>

        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={junitUpgrade}
            onChange={(e) => setJunitUpgrade(e.target.checked)}
            className="mt-0.5 w-4 h-4 accent-red-600 cursor-pointer"
          />
          <div className="flex-1">
            <div className="flex items-center gap-1.5">
              <FlaskConical size={14} className="text-slate-500" />
              <span className="text-sm font-medium text-slate-900">Upgrade JUnit 4 → 5</span>
            </div>
            <p className="text-xs text-slate-600 mt-0.5">
              Migrates test classes to JUnit Jupiter annotations and assertions where JUnit 4 is found.
            </p>
          </div>
        </label>

        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={springbootUpgrade}
            onChange={(e) => setSpringbootUpgrade(e.target.checked)}
            className="mt-0.5 w-4 h-4 accent-red-600 cursor-pointer"
          />
          <div className="flex-1">
            <div className="flex items-center gap-1.5">
              <Leaf size={14} className="text-slate-500" />
              <span className="text-sm font-medium text-slate-900">
                {strategy === 'incremental'
                  ? 'Upgrade Spring Boot (WAR → Boot 4 → executable JAR)'
                  : 'Upgrade Spring Boot (javax → jakarta)'}
              </span>
            </div>
            <p className="text-xs text-slate-600 mt-0.5">
              {strategy === 'incremental'
                ? 'Adds 4 steps: Spring Boot 2.7 (WAR intact) and 3.x (javax.* → jakarta.*) on Java 17 before the Java 25 step, then Spring Boot 4.x and an executable JAR on an embedded container.'
                : 'Bumps Spring Boot to a current 3.x release and migrates javax.* imports to jakarta.* where found.'}
            </p>
          </div>
        </label>
      </div>

      <button
        onClick={() => onContinue({ strategy, junitUpgrade, springbootUpgrade })}
        className="w-full flex items-center justify-center gap-2 bg-red-600 hover:bg-red-500 text-white font-semibold px-6 py-3.5 rounded-xl transition-colors text-sm shadow-lg shadow-red-500/25 cursor-pointer"
      >
        Continue to Upload
        <ArrowRight size={16} />
      </button>
    </div>
  );
}
