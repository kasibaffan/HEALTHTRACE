import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, ShieldAlert, X } from 'lucide-react'
import { api, CASE_ID } from '../services/api'
import { useAsync } from '../hooks/useAsync'
import { useDialogFocus } from '../hooks/useDialogFocus'
import type { Finding } from '../types'
import { STATUS } from '../data/status'
import { Skeleton, StatusBadge } from './ui'

export function OverrideModal({ finding, onCancel, onConfirm }: {
  finding: Finding
  onCancel: () => void
  onConfirm: (reason: string) => Promise<void>
}) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [failed, setFailed] = useState(false)
  const box = useRef<HTMLTextAreaElement>(null)
  const dialogRef = useDialogFocus<HTMLDivElement>()
  const evidence = useAsync(() => api.evidence(CASE_ID), [])
  const cited = (evidence.data ?? []).filter((e) => finding.evidenceIds.includes(e.id))

  useEffect(() => {
    box.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onCancel() } }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [onCancel])

  useEffect(() => {
    if (!saved) return
    const t = setTimeout(onCancel, 2200)
    return () => clearTimeout(t)
  }, [saved, onCancel])

  const valid = reason.trim().length >= 5

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 p-4 animate-fadeIn" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="override-title" className="max-h-[92vh] w-full max-w-lg animate-rise overflow-y-auto rounded-xl bg-white shadow-2xl focus:outline-none">
        {saved ? (
          <div className="p-8 text-center" role="status">
            <CheckCircle2 size={44} className="mx-auto text-emerald-600" aria-hidden />
            <h2 id="override-title" className="mt-3 text-lg font-semibold text-slate-900">Override recorded</h2>
            <p className="mt-1 text-sm text-slate-600">Your decision on <b>{finding.criterion}</b> was saved and added to the audit trail with your reason and timestamp.</p>
            <div className="mt-5 flex justify-center gap-2">
              <a href="#/audit" className="btn-secondary" onClick={onCancel}>View audit trail</a>
              <button className="btn-primary" onClick={onCancel}>Done</button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-start justify-between border-b border-slate-200 p-5">
              <div className="flex items-start gap-3">
                <div className="rounded-lg bg-indigo-50 p-2 text-indigo-700"><ShieldAlert size={20} aria-hidden /></div>
                <div>
                  <h2 id="override-title" className="text-lg font-semibold text-slate-900">Override Finding</h2>
                  <p className="mt-0.5 text-sm text-slate-600">You are replacing the system's assessment with your own judgment.</p>
                </div>
              </div>
              <button aria-label="Close" className="btn-ghost -mr-2 -mt-1 p-1.5" onClick={onCancel}><X size={18} /></button>
            </div>
            <form
              className="p-5"
              onSubmit={async (e) => {
                e.preventDefault()
                if (!valid || busy) return
                setBusy(true); setFailed(false)
                try { await onConfirm(reason.trim()); setSaved(true) } catch { setFailed(true) } finally { setBusy(false) }
              }}
            >
              <div className={`mb-4 rounded-lg border p-3 ${STATUS[finding.status].soft} ${STATUS[finding.status].border}`}>
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="eyebrow">Current AI assessment - {finding.criterionId}</div>
                    <div className="truncate text-sm font-semibold text-slate-900">{finding.criterion}</div>
                  </div>
                  <StatusBadge status={finding.status} />
                </div>
                <p className="mt-2 text-xs leading-relaxed text-slate-700">{finding.explanation}</p>
                <div className="mt-2 space-y-1.5">
                  {evidence.loading && !evidence.data && <Skeleton className="h-9" />}
                  {cited.map((e) => (
                    <div key={e.id} className="rounded border border-white/70 bg-white/80 px-2.5 py-1.5 text-xs">
                      <span className="font-mono font-semibold text-slate-600">{e.id}</span> - {e.documentName}, p.{e.page}
                      <div className="italic text-slate-700">"{e.text}"</div>
                    </div>
                  ))}
                  {!evidence.loading && cited.length === 0 && <div className="text-xs font-medium text-slate-700">No supporting evidence was found for this criterion.</div>}
                </div>
              </div>
              <label htmlFor="override-reason" className="mb-1.5 block text-sm font-medium text-slate-800">Reason <span className="text-rose-600">*</span></label>
              <textarea
                id="override-reason" ref={box} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} aria-required="true"
                placeholder="e.g. External documentation received."
                className="w-full resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
              />
              <p className="mt-2 text-xs text-slate-500">Recorded permanently in the audit trail with your name, the action, this reason, and a timestamp.</p>
              {failed && <p role="alert" className="mt-2 text-sm font-medium text-rose-700">Failed to save reviewer decision. Please try again.</p>}
              <div className="mt-5 flex justify-end gap-2">
                <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>
                <button type="submit" className="btn bg-indigo-600 text-white hover:bg-indigo-700" disabled={!valid || busy}>
                  {busy ? 'Saving reviewer decision...' : 'Confirm Override'}
                </button>
              </div>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
