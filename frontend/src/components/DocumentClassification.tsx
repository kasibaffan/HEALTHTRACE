import { useRef, useState } from 'react'
import { Bot, UserCheck } from 'lucide-react'
import { api } from '../services/api'
import { DOCUMENT_TYPES, documentTypeName } from '../data/documentTypes'
import type { DocumentFile, StructuredFields } from '../types'

function ExtractedFields({ docId }: { docId: string }) {
  const [data, setData] = useState<StructuredFields | null>(null)
  const [error, setError] = useState<string | null>(null)
  const requested = useRef(false)
  const load = () => { if (requested.current) return; requested.current = true; api.structuredFields(docId).then(setData).catch((e: Error) => { requested.current = false; setError(e.message || 'Could not load extracted fields.') }) }
  return (
    <details className="mt-2" onToggle={(e) => { if ((e.currentTarget as HTMLDetailsElement).open) load() }}>
      <summary className="cursor-pointer font-semibold text-brand-700">Extracted dates and results (rule-based)</summary>
      {error && <p role="alert" className="mt-1 text-rose-700">{error}</p>}
      {data && (
        <div className="mt-1 space-y-1">
          <ul>{data.dates.map((d, i) => <li key={`d${i}`}>p.{d.page}: {d.text}{d.ambiguous ? ' (day/month order ambiguous)' : ''}</li>)}
            {data.labResults.map((l, i) => <li key={`l${i}`}>p.{l.page}: {l.testName} {l.value} {l.unit}{l.flag ? ` (${l.flag.toUpperCase()})` : ''}</li>)}</ul>
          {!data.dates.length && !data.labResults.length && <p>No dates or lab results matched.</p>}
          <p className="text-[11px] text-slate-500">{data.notice}</p>
        </div>
      )}
    </details>
  )
}

/**
 * Shows the ML document-type SUGGESTION for a processed document and lets a reviewer confirm or correct it.
 * The suggestion comes from a model trained on synthetic data: it is never presented as verified, and its score is not shown as a percentage.
 */
export function DocumentClassification({ doc, onChanged }: { doc: DocumentFile; onChanged: () => void }) {
  const c = doc.classification
  const [editing, setEditing] = useState(false)
  const [choice, setChoice] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!c || doc.status !== 'PROCESSED') return null

  const run = async (action: () => Promise<unknown>, after?: () => void) => {
    setBusy(true); setError(null)
    try { await action(); after?.(); onChanged() }
    catch (e) { setError((e as Error).message || 'The request failed. Please retry.') }
    finally { setBusy(false) }
  }

  const failed = c.status === 'UNAVAILABLE' || c.status === 'ERROR'
  const startEdit = () => { setChoice(c.reviewedLabel ?? c.label ?? 'OTHER'); setEditing(true); setError(null) }

  return (
    <div className="border-t border-slate-100 bg-slate-50/60 px-4 py-2.5 text-xs text-slate-600" data-testid="document-classification">
      {c.status === 'CLASSIFIED' && (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Bot size={13} aria-hidden className="shrink-0 text-slate-400" />
          <span>Model suggestion: <strong className="font-semibold text-slate-800">{documentTypeName(c.label)}</strong></span>
          <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-600">Not verified</span>
          {c.lowConfidence && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-900">Low model score: check carefully</span>}
        </p>
      )}
      {c.reviewedLabel && (
        <p className="mt-1 flex flex-wrap items-center gap-x-2">
          <UserCheck size={13} aria-hidden className="shrink-0 text-emerald-600" />
          <span>Reviewer type: <strong className="font-semibold text-slate-800">{documentTypeName(c.reviewedLabel)}</strong>{c.reviewedBy ? ` (${c.reviewedBy.fullName})` : ''}</span>
        </p>
      )}
      {c.status === 'NO_TEXT' && <p>No readable text was found, so no document type was suggested. Choose one manually if needed.</p>}
      {c.status === 'NOT_RUN' && <p>No document type suggestion has been generated for this document.</p>}
      {c.status === 'DISABLED' && <p>Document type suggestions are turned off.</p>}
      {failed && <p role="status">Document type suggestion is unavailable right now. The document was still processed.</p>}
      {error && <p role="alert" className="mt-1 text-rose-700">{error}</p>}

      <ExtractedFields docId={doc.id} />
      {editing ? (
        <form className="mt-2 flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); run(() => api.reviewClassification(doc.id, choice), () => setEditing(false)) }}>
          <label className="flex items-center gap-2">
            <span className="font-medium text-slate-700">Document type</span>
            <select className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs" value={choice} onChange={(e) => setChoice(e.target.value)} disabled={busy}>
              {DOCUMENT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.name}</option>)}
            </select>
          </label>
          <button type="submit" className="btn-secondary px-2.5 py-1 text-xs" disabled={busy}>{busy ? 'Saving...' : 'Save'}</button>
          <button type="button" className="px-2 py-1 text-xs text-slate-600 underline" onClick={() => setEditing(false)} disabled={busy}>Cancel</button>
        </form>
      ) : (
        <div className="mt-1.5 flex flex-wrap gap-3">
          <button type="button" className="font-semibold text-brand-700 underline" onClick={startEdit} aria-label={`Review document type for ${doc.name}`}>
            {c.reviewedLabel ? 'Change reviewed type' : 'Confirm or correct type'}
          </button>
          {c.reviewedLabel && <button type="button" className="text-slate-600 underline" disabled={busy} onClick={() => run(() => api.reviewClassification(doc.id, null))}>Clear reviewer type</button>}
          {(failed || c.status === 'NOT_RUN') && <button type="button" className="font-semibold text-brand-700 underline" disabled={busy} onClick={() => run(() => api.retryClassification(doc.id))}>{busy ? 'Retrying...' : 'Retry suggestion'}</button>}
        </div>
      )}
    </div>
  )
}
