import type { FindingStatus, ReviewAction } from '../types'

export interface Tone { label: string; passportLabel: string; badge: string; soft: string; text: string; dot: string; border: string; icon: string }

export const STATUS: Record<FindingStatus, Tone> = {
  match: {
    label: 'MATCH', passportLabel: 'SATISFIED',
    badge: 'bg-emerald-50 text-emerald-800 ring-1 ring-inset ring-emerald-200',
    soft: 'bg-emerald-50', text: 'text-emerald-700', dot: 'bg-emerald-500', border: 'border-emerald-300', icon: 'text-emerald-600',
  },
  missing: {
    label: 'MISSING EVIDENCE', passportLabel: 'MISSING EVIDENCE',
    badge: 'bg-amber-50 text-amber-900 ring-1 ring-inset ring-amber-300',
    soft: 'bg-amber-50', text: 'text-amber-800', dot: 'bg-amber-500', border: 'border-amber-300', icon: 'text-amber-600',
  },
  conflict: {
    label: 'POTENTIAL CONFLICT', passportLabel: 'POTENTIAL CONFLICT',
    badge: 'bg-rose-50 text-rose-800 ring-1 ring-inset ring-rose-200',
    soft: 'bg-rose-50', text: 'text-rose-700', dot: 'bg-rose-500', border: 'border-rose-300', icon: 'text-rose-600',
  },
}

export const NEUTRAL_TONE = {
  soft: 'bg-slate-50', text: 'text-slate-700', border: 'border-slate-300', dot: 'bg-slate-400',
}

export const HUMAN_REVIEW_BADGE = 'bg-indigo-50 text-indigo-800 ring-1 ring-inset ring-indigo-200'

export const ACTION_LABEL: Record<ReviewAction, string> = {
  accept: 'Accepted',
  override: 'Overridden',
  'request-evidence': 'Evidence requested',
}

export function caseStatusBadge(status: string): string {
  if (status === 'Needs Review') return HUMAN_REVIEW_BADGE
  if (status === 'Review Complete') return 'bg-emerald-50 text-emerald-800 ring-1 ring-inset ring-emerald-200'
  if (status === 'Awaiting Evidence') return 'bg-amber-50 text-amber-900 ring-1 ring-inset ring-amber-300'
  if (status === 'Ready for Decision') return 'bg-emerald-50 text-emerald-800 ring-1 ring-inset ring-emerald-200'
  return 'bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-200'
}

export function formatTime(iso: string, withSeconds = false): string {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', ...(withSeconds ? { second: '2-digit' } : {}) })
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  return `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })}, ${formatTime(iso, true)}`
}
