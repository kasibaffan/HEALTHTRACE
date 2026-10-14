import { useState } from 'react'
import { Check, FilePlus2, PenLine, UserCheck } from 'lucide-react'
import type { Finding, ReviewAction } from '../types'
import { ACTION_LABEL, formatDateTime } from '../data/status'
import { useReview } from './ReviewContext'

export function ReviewRecordNote({ finding }: { finding: Finding }) {
  const r = finding.review
  if (!r) return null
  return (
    <div className="flex items-start gap-2 rounded-lg border border-indigo-200 bg-indigo-50/70 px-3 py-2 text-xs text-indigo-900">
      <UserCheck size={14} className="mt-0.5 shrink-0" aria-hidden />
      <div>
        <span className="font-semibold">{ACTION_LABEL[r.action]}</span> by {r.reviewer} at {formatDateTime(r.timestamp)}
        {r.reason && <div className="mt-0.5 text-indigo-800/90">Reason: {r.reason}</div>}
      </div>
    </div>
  )
}

export function ReviewActions({ finding, size = 'md' }: { finding: Finding; size?: 'sm' | 'md' }) {
  const { act } = useReview()
  const [busy, setBusy] = useState<ReviewAction | null>(null)
  const pad = size === 'sm' ? 'px-2.5 py-1.5 text-xs' : 'px-3 py-2 text-sm'

  const run = async (action: ReviewAction) => {
    setBusy(action)
    try { await act(finding, action) } finally { setBusy(null) }
  }
  const current = finding.review?.action

  return (
    <div className="flex flex-wrap gap-2" aria-busy={busy !== null} role="group" aria-label={`Review actions for ${finding.criterion}`}>
      <button onClick={() => run('accept')} disabled={busy !== null}
        className={`btn ${pad} ${current === 'accept' ? 'bg-emerald-600 text-white' : 'border border-emerald-300 bg-white text-emerald-800 hover:bg-emerald-50'}`}>
        <Check size={14} aria-hidden /> {busy === 'accept' ? 'Saving...' : current === 'accept' ? 'Accepted' : 'Accept'}
      </button>
      <button onClick={() => run('override')} disabled={busy !== null}
        className={`btn ${pad} border border-slate-300 bg-white text-slate-700 hover:bg-slate-50`}>
        <PenLine size={14} aria-hidden /> Override
      </button>
      <button onClick={() => run('request-evidence')} disabled={busy !== null}
        className={`btn ${pad} ${current === 'request-evidence' ? 'bg-amber-500 text-white' : 'border border-amber-300 bg-white text-amber-900 hover:bg-amber-50'}`}>
        <FilePlus2 size={14} aria-hidden /> {busy === 'request-evidence' ? 'Saving...' : current === 'request-evidence' ? 'Requested' : 'Request Evidence'}
      </button>
    </div>
  )
}
