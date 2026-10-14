import { useEffect, type ReactNode } from 'react'
import { AlertTriangle, BadgeCheck, Check, Copy, ExternalLink, FileSearch, ShieldCheck, X } from 'lucide-react'
import { api } from '../services/api'
import { useAsync } from '../hooks/useAsync'
import { useDialogFocus } from '../hooks/useDialogFocus'
import type { Evidence, EvidenceChain as Chain } from '../types'
import { STATUS } from '../data/status'
import { EvidenceChain } from './EvidenceChain'
import { ReviewActions, ReviewRecordNote } from './ReviewActions'
import { useReview } from './ReviewContext'
import { ErrorState, LoadingBlock, SectionLabel, StatusIcon } from './ui'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div><SectionLabel>{label}</SectionLabel><div className="text-sm text-slate-900">{children}</div></div>
}

const Quote = ({ ev, tone = 'text-slate-800' }: { ev: Evidence; tone?: string }) => (
  <blockquote className={`rounded-lg border-l-4 border-slate-300 bg-slate-50 px-3 py-2.5 text-sm italic leading-relaxed ${tone}`}>
    "{ev.text}"
  </blockquote>
)

function VerifiedTag({ ev }: { ev: Evidence }) {
  return ev.verified
    ? <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700"><BadgeCheck size={14} aria-hidden /> VERIFIED</span>
    : <span className="inline-flex items-center gap-1 text-xs font-semibold text-amber-700"><AlertTriangle size={14} aria-hidden /> NOT VERIFIED</span>
}

function copyText(data: Chain): string {
  const f = data.finding
  if (f.status === 'missing') {
    return [`No supporting evidence found for: ${f.requirement}`, `Documents searched: ${f.searchedDocuments.join(', ')}`, `Expected: ${f.expectedEvidence}`].join('\n')
  }
  return data.evidence.map((e) => `"${e.text}"\n- ${e.documentName}, page ${e.page} (${e.id})`).join('\n\n')
}

export function EvidencePassport({ target, onClose }: { target: { findingId: string; focusEvidenceId?: string }; onClose: () => void }) {
  const { version, openDocument, notify } = useReview()
  const dialogRef = useDialogFocus<HTMLElement>()
  const { data, error, loading, reload } = useAsync(() => api.chain(target.findingId), [target.findingId, version])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const f = data?.finding
  const tone = f ? STATUS[f.status] : null

  const primaryDoc = data && (data.evidence[0] ?? data.reviewedEvidence[0])
  const openSource = () => {
    if (!data) return
    if (primaryDoc) openDocument(primaryDoc.documentId, primaryDoc.page, primaryDoc.id)
    else {
      const n = data.chain[0]
      if (n.documentId && n.page) openDocument(n.documentId, n.page, n.evidenceId ?? undefined)
    }
  }
  const copy = async () => {
    if (!data) return
    try { await navigator.clipboard.writeText(copyText(data)); notify('Evidence copied to clipboard.') }
    catch { notify('Copy is not available in this browser context.', 'error') }
  }

  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-slate-900/40 animate-fadeIn" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="passport-title" className="focus:outline-none flex h-full w-full max-w-[600px] animate-slideIn flex-col bg-white shadow-drawer">
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-brand-50 p-2 text-brand-700"><ShieldCheck size={20} aria-hidden /></div>
            <div>
              <h2 id="passport-title" className="text-lg font-semibold leading-tight text-slate-900">Evidence Passport</h2>
              {f && <div className="text-xs text-slate-500">{f.criterionId} - {f.criterion}</div>}
            </div>
          </div>
          <button aria-label="Close Evidence Passport" className="btn-ghost -mr-2 p-2" onClick={onClose}><X size={18} /></button>
        </header>

        <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
          {loading && !data && <LoadingBlock label="Loading evidence chain..." rows={6} />}
          {error && !data && <ErrorState message={`Unable to retrieve evidence. ${error}`} onRetry={reload} />}
          {data && f && tone && (
            <>
              <div className={`flex items-center gap-2.5 rounded-lg border px-4 py-3 ${tone.soft} ${tone.border}`}>
                <StatusIcon status={f.status} size={22} />
                <div>
                  <div className="eyebrow">Status</div>
                  <div className={`text-base font-bold tracking-wide ${tone.text}`}>
                    {f.status === 'match' ? '✓ ' : '⚠ '}{tone.passportLabel}
                  </div>
                </div>
              </div>

              {f.status === 'match' && <MatchBody data={data} />}
              {f.status === 'missing' && <MissingBody data={data} />}
              {f.status === 'conflict' && <ConflictBody data={data} />}

              <EvidenceChain key={f.id} data={data} initialSelected={target.focusEvidenceId ? `n-${target.focusEvidenceId}` : undefined} />

              <section>
                <SectionLabel>Human review</SectionLabel>
                <p className="mb-2 text-xs text-slate-500">The system assists; the final decision belongs to the reviewer.</p>
                <div className="space-y-2.5">
                  <ReviewRecordNote finding={f} />
                  <ReviewActions finding={f} />
                </div>
              </section>
            </>
          )}
        </div>

        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 bg-slate-50 px-5 py-3">
          <button className="btn-secondary" onClick={openSource} disabled={!data}><ExternalLink size={14} aria-hidden /> {f?.status === 'missing' ? 'Open Policy Source' : 'Open Source Document'}</button>
          <button className="btn-secondary" onClick={copy} disabled={!data}><Copy size={14} aria-hidden /> Copy Evidence</button>
          <button className="btn-primary" onClick={onClose}>Close</button>
        </footer>
      </aside>
    </div>
  )
}

function MatchBody({ data }: { data: Chain }) {
  const { openDocument } = useReview()
  const fact = data.facts[0]
  const ev = data.evidence[0]
  const rule = data.rule
  return (
    <div className="space-y-5">
      <Field label="Policy criterion"><span className="text-base font-medium">{data.criterion.requirement}</span></Field>
      {fact && <Field label="Extracted fact">
        <div className="text-slate-600">{fact.label}</div>
        <div className="text-2xl font-semibold tracking-tight">{typeof fact.value === 'number' ? `${fact.value} ${fact.unit ?? ''}` : fact.value}</div>
        <div className="text-xs text-slate-500">Extraction confidence {Math.round(fact.confidence * 100)}%</div>
      </Field>}
      <Field label="Rule applied"><code className="rounded bg-slate-100 px-2 py-1 font-mono text-[13px]">{rule.expression}</code></Field>
      <Field label="Evaluation">
        <div className="flex items-center gap-3">
          <code className="font-mono text-lg font-semibold">{rule.evaluation}</code>
          <span className={`rounded px-2 py-0.5 text-xs font-bold ${rule.result ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'}`}>{String(rule.result).toUpperCase()}</span>
        </div>
        <div className="mt-1 text-xs text-slate-500">Computed by the deterministic rules engine, not by AI.</div>
      </Field>
      {ev && <>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Source document">
            <button className="inline-flex items-center gap-1.5 font-medium text-brand-700 hover:underline" onClick={() => openDocument(ev.documentId, ev.page, ev.id)}>{ev.documentName}</button>
          </Field>
          <Field label="Page">{ev.page}</Field>
        </div>
        <Field label="Supporting evidence"><Quote ev={ev} /></Field>
        <Field label="Evidence status"><VerifiedTag ev={ev} /></Field>
      </>}
    </div>
  )
}

function MissingBody({ data }: { data: Chain }) {
  const { openDocument } = useReview()
  const f = data.finding
  return (
    <div className="space-y-5">
      <Field label="Policy"><span className="text-base font-medium">{data.criterion.requirement}</span></Field>
      <Field label="Searched documents">
        <ul className="space-y-1.5">
          {f.searchedDocuments.map((d) => (
            <li key={d} className="flex items-center gap-2"><Check size={15} className="text-emerald-600" aria-hidden /> {d}</li>
          ))}
        </ul>
      </Field>
      <Field label="Supporting evidence">
        <div className="rounded-lg border border-dashed border-amber-300 bg-amber-50/60 px-3 py-3 font-semibold text-amber-900">NONE - no supporting evidence was found.</div>
        <p className="mt-1.5 text-xs text-slate-500">No evidence has been inferred, guessed, or fabricated for this requirement.</p>
      </Field>
      {data.reviewedEvidence.length > 0 && (
        <Field label="Reviewed but does not qualify">
          {data.reviewedEvidence.map((e) => (
            <div key={e.id} className="rounded-lg border border-slate-200 bg-white p-3">
              <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
                <span>{e.documentName} - page {e.page}</span>
                <button className="font-medium text-brand-700 hover:underline" onClick={() => openDocument(e.documentId, e.page, e.id)}>View</button>
              </div>
              <div className="mt-1 text-sm italic text-slate-700">"{e.text}"</div>
              {e.note && <div className="mt-1.5 text-xs text-amber-800">{e.note}</div>}
            </div>
          ))}
        </Field>
      )}
      <Field label="Expected evidence"><span className="inline-flex items-center gap-1.5 font-medium"><FileSearch size={16} className="text-slate-500" aria-hidden /> {f.expectedEvidence}</span></Field>
      <Field label="Reviewer action"><span className="font-medium">{f.suggestedAction?.replace(/\.$/, '')}.</span> Request additional documentation from the provider.</Field>
    </div>
  )
}

function ConflictBody({ data }: { data: Chain }) {
  const { openDocument } = useReview()
  const [factA, factB] = data.facts
  const [evA, evB] = data.evidence
  const sources = [
    { label: 'Source A', ev: evA, fact: factA },
    { label: 'Source B', ev: evB, fact: factB },
  ]
  return (
    <div className="space-y-5">
      <Field label="Fact"><span className="text-base font-medium">{factA?.label}</span></Field>
      <div className="grid gap-3 sm:grid-cols-2">
        {sources.map(({ label, ev, fact }) => ev && fact && (
          <div key={label} className="rounded-lg border border-rose-200 bg-rose-50/40 p-3">
            <div className="text-[11px] font-bold uppercase tracking-wider text-rose-700">{label}</div>
            <button className="mt-1 block text-left text-sm font-semibold text-brand-700 hover:underline" onClick={() => openDocument(ev.documentId, ev.page, ev.id)}>{ev.documentName}</button>
            <div className="text-xs text-slate-500">Page {ev.page}</div>
            <div className="mt-2 text-2xl font-semibold tracking-tight">{fact.value} {fact.unit}</div>
            <div className="mt-2 text-sm italic leading-relaxed text-slate-700">"{ev.text}"</div>
            <div className="mt-2"><VerifiedTag ev={ev} /></div>
          </div>
        ))}
      </div>
      <Field label="Status">
        <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2.5 font-semibold text-indigo-900">Requires Human Review</div>
        <p className="mt-1.5 text-xs text-slate-500">HealthTrace does not decide which source is correct. Resolve this by confirming with the clinician, overriding with a reason, or requesting evidence.</p>
      </Field>
      <Field label="Rule applied">
        <code className="rounded bg-slate-100 px-2 py-1 font-mono text-[13px]">{data.rule.expression}</code>
        <div className="mt-1 text-xs text-slate-500">Evaluated {data.rule.evaluation} = {String(data.rule.result).toUpperCase()}</div>
      </Field>
    </div>
  )
}
