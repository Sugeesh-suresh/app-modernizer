import { useState } from 'react';
import { ArrowRight, CheckCircle2, Loader2, Sparkles, FileSearch, Camera } from 'lucide-react';
import type { CompanionRecommendation, ScreenshotsOffer } from '../types';

interface Props {
  primaryLabel: string;
  recommendations: CompanionRecommendation[];
  onConfirm: (selected: string[], screenshots: boolean) => Promise<void>;
  /** stack-discovery: there is no primary migration these sit alongside, and
   * nothing is being migrated at all — only reverse engineered. The copy has to
   * say that, or the screen promises migrations this run will never perform. */
  discovery?: boolean;
  /** stack-discovery: the UI screenshots option — null when the repository has no UI
   * or the option is switched off (UI_SCREENSHOTS=off). */
  screenshotsOffer?: ScreenshotsOffer | null;
}

export function CompanionSelection({
  primaryLabel,
  recommendations,
  onConfirm,
  discovery = false,
  screenshotsOffer = null,
}: Props) {
  const [screenshots, setScreenshots] = useState<boolean>(
    () => !!screenshotsOffer?.available && screenshotsOffer.default,
  );
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(recommendations.map((r) => r.pattern)),
  );
  const [confirming, setConfirming] = useState(false);

  const toggle = (pattern: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(pattern)) next.delete(pattern);
      else next.add(pattern);
      return next;
    });
  };

  // Screenshots render the UI stacks below; with all of them unchecked there is nothing to render.
  const uiStackKept = !!screenshotsOffer?.stacks.some((p) => selected.has(p));
  const screenshotsChosen = screenshots && !!screenshotsOffer?.available && uiStackKept;

  const handleConfirm = async () => {
    setConfirming(true);
    try {
      await onConfirm(Array.from(selected), screenshotsChosen);
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
            <h2 className="text-xl font-bold text-slate-900">
              {discovery ? 'Technology Stacks Detected' : 'Additional Migrations Detected'}
            </h2>
            <p className="text-sm text-slate-600">
              {discovery
                ? 'Each stack you keep checked will be reverse engineered into its own section of the document'
                : `Alongside ${primaryLabel}, this repository also depends on the following`}
            </p>
          </div>
        </div>
        <p className="text-xs text-slate-500">
          {discovery ? (
            <>
              Found by a deterministic scan of the repository's build files, descriptors and source,
              then confirmed by an agent that read them — every stack below lists the evidence that
              put it there. Uncheck anything you don't want documented. The repository is only read;
              this run produces a description of what it contains.
            </>
          ) : (
            <>
              Detected deterministically by scanning the uploaded repository's build files and source
              for library/driver signatures — not an AI guess. Leave any of these unchecked to
              migrate {primaryLabel} on its own; you can always run them separately later.
            </>
          )}
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
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <FileSearch size={14} className="text-slate-500" />
                  <span className="text-sm font-semibold text-slate-900">{rec.label}</span>
                  {discovery && rec.kind && (
                    <span className="text-[10px] uppercase tracking-wide font-semibold text-slate-600 bg-slate-900/5 border border-slate-900/10 rounded px-1.5 py-0.5">
                      {rec.kind}
                    </span>
                  )}
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

      {screenshotsOffer && (
        <div className="glass rounded-2xl p-5 mb-8">
          <label
            className={`flex items-start gap-3 ${screenshotsOffer.available && uiStackKept ? 'cursor-pointer' : 'cursor-not-allowed opacity-60'}`}
          >
            <input
              type="checkbox"
              checked={screenshotsChosen}
              disabled={!screenshotsOffer.available || !uiStackKept}
              onChange={(e) => setScreenshots(e.target.checked)}
              className="mt-0.5 w-4 h-4 accent-violet-600 cursor-pointer disabled:cursor-not-allowed"
            />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <Camera size={14} className="text-slate-500" />
                <span className="text-sm font-semibold text-slate-900">Capture UI screenshots</span>
              </div>
              <p className="mt-1 text-xs text-slate-600">
                Renders each page from the repository's own templates with generated sample data — in
                its default state and the states its conditions allow (empty lists, messages, roles) —
                as a separate <strong>UI Screens</strong> document. No model is used and nothing leaves
                the server.
              </p>
              {screenshotsOffer.available && !uiStackKept && (
                <p className="mt-1 text-xs text-amber-700">Keep a UI stack checked to capture its screens.</p>
              )}
              {screenshotsOffer.reason && (
                <p className={`mt-1 text-xs ${screenshotsOffer.available ? 'text-slate-500' : 'text-amber-700'}`}>
                  {screenshotsOffer.reason}
                </p>
              )}
            </div>
          </label>
        </div>
      )}

      <button
        onClick={handleConfirm}
        disabled={confirming}
        className="w-full flex items-center justify-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:bg-slate-900/5 disabled:text-slate-500 text-white font-semibold px-6 py-3.5 rounded-xl transition-colors text-sm shadow-lg shadow-violet-500/25 cursor-pointer disabled:cursor-not-allowed"
      >
        {confirming ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
        {confirming
          ? 'Starting…'
          : discovery
            ? `Reverse engineer ${selected.size} ${selected.size === 1 ? 'stack' : 'stacks'}`
            : 'Continue'}
        {!confirming && <ArrowRight size={16} />}
      </button>
    </div>
  );
}
