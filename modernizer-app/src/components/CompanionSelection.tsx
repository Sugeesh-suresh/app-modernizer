import { useState } from 'react';
import { ArrowRight, CheckCircle2, Loader2, Sparkles, FileSearch, Camera, FileText, Network, ClipboardList } from 'lucide-react';
import type { CompanionRecommendation, DiscoveryDocument, ScreenshotsOffer } from '../types';

/** The documents a reverse-engineering run can produce; only the chosen ones are generated. */
const DOCUMENTS: { id: DiscoveryDocument; label: string; detail: string; icon: typeof FileText }[] = [
  {
    id: 'brd', label: 'Business Requirements Document (BRD)', icon: FileText,
    detail: 'Plain business language: actors, capabilities, scenarios and the business rules found in the code, with their use cases, negative scenarios and edge cases.',
  },
  {
    id: 'technical_spec', label: 'Technical Specification', icon: Network,
    detail: 'Architecture diagrams (high and low level), the interface catalog, every endpoint\'s request/response contract, UI-to-backend calls and configuration.',
  },
  {
    id: 'test_inventory', label: 'Test Cases (Existing Test Inventory)', icon: ClipboardList,
    detail: 'Every test file and test in the repository, what the tests cover and what has no test.',
  },
  {
    id: 'ui_screens', label: 'UI Screens', icon: Camera,
    detail: 'Each page rendered from the repository\'s own templates with generated sample data, in its default state and the states its conditions allow. No model is used and nothing leaves the server.',
  },
];

interface Props {
  primaryLabel: string;
  recommendations: CompanionRecommendation[];
  /** `documents`: stack-discovery only — the documents to generate. */
  onConfirm: (selected: string[], documents?: DiscoveryDocument[]) => Promise<void>;
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
  const [documents, setDocuments] = useState<Set<DiscoveryDocument>>(() => new Set<DiscoveryDocument>([
    'brd', 'technical_spec', 'test_inventory',
    ...(screenshotsOffer?.available && screenshotsOffer.default ? ['ui_screens' as const] : []),
  ]));
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
  const screensPossible = !!screenshotsOffer?.available && uiStackKept;
  const chosen = DOCUMENTS.map((d) => d.id).filter((d) => documents.has(d) && (d !== 'ui_screens' || screensPossible));
  const toggleDocument = (id: DiscoveryDocument) => {
    setDocuments((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleConfirm = async () => {
    setConfirming(true);
    try {
      await onConfirm(Array.from(selected), discovery ? chosen : undefined);
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

      {discovery && (
        <div className="glass rounded-2xl p-5 mb-8">
          <h3 className="text-sm font-semibold text-slate-900">Documents to generate</h3>
          <p className="mt-0.5 mb-4 text-xs text-slate-600">
            Only the documents you choose are generated — and only the work they need is run.
          </p>
          <div className="space-y-3">
            {DOCUMENTS.map((doc) => {
              const screens = doc.id === 'ui_screens';
              const enabled = !screens || screensPossible;
              const Icon = doc.icon;
              const note = !screens ? '' : !screenshotsOffer
                ? 'Not available: no UI the pipeline can render was found in this repository.'
                : !screenshotsOffer.available ? screenshotsOffer.reason
                  : !uiStackKept ? 'Keep a UI stack checked to capture its screens.' : screenshotsOffer.reason;
              return (
                <label
                  key={doc.id}
                  className={`flex items-start gap-3 rounded-xl border border-slate-900/10 p-3.5 transition-colors ${enabled ? 'cursor-pointer hover:border-slate-900/20' : 'cursor-not-allowed opacity-60'}`}
                >
                  <input
                    type="checkbox"
                    checked={enabled && documents.has(doc.id)}
                    disabled={!enabled}
                    onChange={() => toggleDocument(doc.id)}
                    aria-label={doc.label}
                    className="mt-0.5 w-4 h-4 accent-violet-600 cursor-pointer disabled:cursor-not-allowed"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <Icon size={14} className="text-slate-500" />
                      <span className="text-sm font-semibold text-slate-900">{doc.label}</span>
                    </div>
                    <p className="mt-1 text-xs text-slate-600">{doc.detail}</p>
                    {note && (
                      <p className={`mt-1 text-xs ${enabled ? 'text-slate-500' : 'text-amber-700'}`}>{note}</p>
                    )}
                  </div>
                </label>
              );
            })}
          </div>
          {chosen.length === 0 && (
            <p className="mt-3 text-xs text-amber-700">Choose at least one document.</p>
          )}
        </div>
      )}

      <button
        onClick={handleConfirm}
        disabled={confirming || (discovery && chosen.length === 0)}
        className="w-full flex items-center justify-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:bg-slate-900/5 disabled:text-slate-500 text-white font-semibold px-6 py-3.5 rounded-xl transition-colors text-sm shadow-lg shadow-violet-500/25 cursor-pointer disabled:cursor-not-allowed"
      >
        {confirming ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
        {confirming
          ? 'Starting…'
          : discovery
            ? `Generate ${chosen.length} ${chosen.length === 1 ? 'document' : 'documents'} for ${selected.size} ${selected.size === 1 ? 'stack' : 'stacks'}`
            : 'Continue'}
        {!confirming && <ArrowRight size={16} />}
      </button>
    </div>
  );
}
