import { useState } from 'react';
import {
  ArrowRight, CheckCircle2, Loader2, Sparkles, FileSearch, Camera, FileText, Network, ClipboardList,
  Wrench, Braces, Bug, Layers, MousePointerClick,
} from 'lucide-react';
import type { CompanionRecommendation, DiscoveryDocument, ScreenshotsOffer, StrategyOption, UiPagesOffer } from '../types';

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
    id: 'setup', label: 'Setup & Deployment Guide', icon: Wrench,
    detail: 'How to build and run the application locally and deploy it to other environments: prerequisites, configuration, services, database, commands — every step citing the file it comes from.',
  },
  {
    id: 'openapi', label: 'OpenAPI 3.0 Specification', icon: Braces,
    detail: 'Every HTTP endpoint with its parameters, request and response schemas, validation and errors, as openapi.yaml / openapi.json — ready for Swagger UI / Editor or Postman. Computed from the code, no model.',
  },
  {
    id: 'tech_debt', label: 'Tech Debt & Dead Code', icon: Bug,
    detail: 'Code nothing reaches, unused tables and endpoints, risky patterns and debt markers, each with where it is and how sure the finding is — a separate list for human review.',
  },
  {
    id: 'ui_pages', label: 'UI Pages: Elements, Interactions & Backend Traces', icon: MousePointerClick,
    detail: 'Page by page, in route order: every HTML element, every interactive element with what its action does and its purpose, and the trace of each to the backend — Ajax or other HTTP call, endpoint URL, handler, request and response.',
  },
  {
    id: 'ui_screens', label: 'UI Screens', icon: Camera,
    detail: 'A screenshot of each page, in the same page order as UI Pages: Thymeleaf pages rendered with generated sample data in each state their conditions allow; JSP and HTML pages as static previews of their source. No model is used and nothing leaves the server.',
  },
];

interface Props {
  primaryLabel: string;
  recommendations: CompanionRecommendation[];
  /** `documents`, `strategy`: stack-discovery only — the documents to generate and how to reverse engineer. */
  onConfirm: (selected: string[], documents?: DiscoveryDocument[], strategy?: string) => Promise<void>;
  /** stack-discovery: there is no primary migration these sit alongside, and
   * nothing is being migrated at all — only reverse engineered. The copy has to
   * say that, or the screen promises migrations this run will never perform. */
  discovery?: boolean;
  /** stack-discovery: the UI screenshots option — null when the repository has no UI
   * or the option is switched off (UI_SCREENSHOTS=off). */
  screenshotsOffer?: ScreenshotsOffer | null;
  /** stack-discovery: the reverse-engineering strategies offered, the recommended one first. */
  strategies?: StrategyOption[];
  /** stack-discovery: the UI Pages option — null when the repository has no UI. */
  uiPagesOffer?: UiPagesOffer | null;
}

export function CompanionSelection({
  primaryLabel,
  recommendations,
  onConfirm,
  discovery = false,
  screenshotsOffer = null,
  strategies = [],
  uiPagesOffer = null,
}: Props) {
  const [strategy, setStrategy] = useState<string>(
    () => strategies.find((o) => o.recommended)?.id ?? strategies.find((o) => o.available)?.id ?? '',
  );
  const [documents, setDocuments] = useState<Set<DiscoveryDocument>>(() => new Set<DiscoveryDocument>([
    'brd', 'technical_spec', 'test_inventory', 'setup', 'openapi', 'tech_debt', 'ui_pages',
    ...(screenshotsOffer?.available && screenshotsOffer.default ? ['ui_screens' as const] : []),
  ]));
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(recommendations.map((r) => r.pattern)),
  );
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState('');

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
  const pagesPossible = !!uiPagesOffer?.available
    && (uiPagesOffer.stacks.length === 0 || uiPagesOffer.stacks.some((p) => selected.has(p)));
  const chosen = DOCUMENTS.map((d) => d.id).filter((d) => documents.has(d)
    && (d !== 'ui_screens' || screensPossible) && (d !== 'ui_pages' || pagesPossible));
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
    setError('');
    try {
      await onConfirm(Array.from(selected), discovery ? chosen : undefined,
        discovery && strategy ? strategy : undefined);
    } catch (err) {
      // e.g. a strategy no longer available once a stack was unchecked
      setError(err instanceof Error ? err.message : 'Could not start the run');
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
                ? 'Choose the stacks to document, how to reverse engineer them, and the deliverables to produce'
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

      {discovery && strategies.length > 0 && (
        <div className="glass rounded-2xl p-5 mb-8">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
            <Layers size={14} className="text-slate-500" />
            Reverse-engineering strategy
          </h3>
          <p className="mt-0.5 mb-4 text-xs text-slate-600">
            How the code is read before anything is written — chosen for this repository from the layers
            found. Whatever no pass reaches is listed for review as dead code. Recommendations are made for
            all the stacks; unchecking a stack can change which strategies apply.
          </p>
          <div className="space-y-3" role="radiogroup" aria-label="Reverse-engineering strategy">
            {strategies.map((o) => (
              <label
                key={o.id}
                className={`flex items-start gap-3 rounded-xl border p-3.5 transition-colors ${
                  strategy === o.id ? 'border-violet-500/60 bg-violet-500/5' : 'border-slate-900/10'
                } ${o.available ? 'cursor-pointer hover:border-slate-900/20' : 'cursor-not-allowed opacity-60'}`}
              >
                <input
                  type="radio"
                  name="re-strategy"
                  checked={strategy === o.id}
                  disabled={!o.available}
                  onChange={() => setStrategy(o.id)}
                  aria-label={o.name}
                  className="mt-0.5 w-4 h-4 accent-violet-600 cursor-pointer disabled:cursor-not-allowed"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-sm font-semibold text-slate-900">{o.name}</span>
                    {o.recommended && (
                      <span className="text-[10px] uppercase tracking-wide font-semibold text-violet-700 bg-violet-500/10 border border-violet-500/20 rounded px-1.5 py-0.5">
                        Recommended
                      </span>
                    )}
                  </div>
                  {o.pass_labels.length > 0 && (
                    <ol className="mt-1 flex flex-wrap gap-1 text-[11px] text-slate-600">
                      {o.pass_labels.map((l, i) => (
                        <li key={l} className="bg-slate-900/5 border border-slate-900/10 rounded px-1.5 py-0.5">{i + 1}. {l}</li>
                      ))}
                    </ol>
                  )}
                  <p className="mt-1 text-xs text-slate-600">{o.summary}</p>
                  <p className="mt-1 text-xs text-slate-500"><span className="font-medium">Best for:</span> {o.best_for}</p>
                  {o.standards && <p className="mt-0.5 text-xs text-slate-500"><span className="font-medium">Basis:</span> {o.standards}</p>}
                  {o.reasons.map((reason) => (
                    <p key={reason} className={`mt-0.5 text-xs ${o.available ? 'text-slate-500' : 'text-amber-700'}`}>{reason}</p>
                  ))}
                </div>
              </label>
            ))}
          </div>
        </div>
      )}

      {discovery && (
        <div className="glass rounded-2xl p-5 mb-8">
          <h3 className="text-sm font-semibold text-slate-900">Documents to generate</h3>
          <p className="mt-0.5 mb-4 text-xs text-slate-600">
            Only the documents you choose are generated — and only the work they need is run.
          </p>
          <div className="space-y-3">
            {DOCUMENTS.map((doc) => {
              const screens = doc.id === 'ui_screens';
              const uiPages = doc.id === 'ui_pages';
              const enabled = screens ? screensPossible : uiPages ? pagesPossible : true;
              const Icon = doc.icon;
              const note = uiPages
                ? (!uiPagesOffer ? 'Not available: no UI layer was found in this repository.'
                  : !uiPagesOffer.available ? uiPagesOffer.reason
                    : !pagesPossible ? 'Keep a UI stack checked to document its pages.' : '')
                : !screens ? '' : !screenshotsOffer
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

      {error && <p className="mb-3 text-xs text-red-700">{error}</p>}
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
