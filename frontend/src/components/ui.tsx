import type { ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, GitCompareArrows, Loader2, RefreshCw, UserCheck } from 'lucide-react'
import type { FindingStatus } from '../types'
import { HUMAN_REVIEW_BADGE, STATUS } from '../data/status'

export function StatusIcon({ status, size = 18 }: { status: FindingStatus; size?: number }) {
  const cls = STATUS[status].icon
  if (status === 'match') return <CheckCircle2 size={size} className={cls} aria-hidden />
  if (status === 'missing') return <AlertTriangle size={size} className={cls} aria-hidden />
  return <GitCompareArrows size={size} className={cls} aria-hidden />
}

export function StatusBadge({ status, label }: { status: FindingStatus; label?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-semibold tracking-wide ${STATUS[status].badge}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${STATUS[status].dot}`} />
      {label ?? STATUS[status].label}
    </span>
  )
}

export function HumanReviewBadge({ label = 'HUMAN REVIEW' }: { label?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-semibold tracking-wide ${HUMAN_REVIEW_BADGE}`}>
      <UserCheck size={12} aria-hidden />
      {label}
    </span>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500">
      <Loader2 size={18} className="animate-spin" aria-hidden /> {label}...
    </div>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-slate-200/80 ${className}`} aria-hidden />
}

export function LoadingBlock({ label, rows = 4 }: { label: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3 p-5">
      <span className="sr-only">{label}</span>
      <div className="text-sm font-medium text-slate-500">{label}</div>
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className={`h-9 ${i % 2 ? 'w-4/5' : 'w-full'}`} />)}
    </div>
  )
}

export function CaseReviewSkeleton() {
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">Loading case</span>
      <Skeleton className="mb-3 h-4 w-40" />
      <div className="card mb-6 space-y-4 p-6">
        <Skeleton className="h-4 w-28" /><Skeleton className="h-8 w-64" />
        <div className="grid gap-4 sm:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10" />)}</div>
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="card space-y-4 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-24" />)}</div>
        <div className="card space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>
      </div>
      <div className="mt-4 text-center text-sm text-slate-500">Loading case...</div>
    </div>
  )
}

export function EmptyState({ icon, title, body }: { icon: ReactNode; title: string; body?: string }) {
  return (
    <div className="flex flex-col items-center px-4 py-12 text-center">
      <div className="mb-3 grid h-11 w-11 place-items-center rounded-full bg-slate-100 text-slate-500">{icon}</div>
      <div className="text-sm font-semibold text-slate-900">{title}</div>
      {body && <p className="mt-1 max-w-sm text-sm text-slate-500">{body}</p>}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="card mx-auto my-10 max-w-lg p-6 text-center">
      <AlertTriangle className="mx-auto text-amber-500" size={28} aria-hidden />
      <h3 className="mt-3 text-base font-semibold text-slate-900">Something went wrong</h3>
      <p className="mt-1 text-sm text-slate-600">{message}</p>
      {onRetry && (
        <button className="btn-secondary mt-4" onClick={onRetry}>
          <RefreshCw size={14} aria-hidden /> Try again
        </button>
      )}
    </div>
  )
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <div className="eyebrow mb-1 text-brand-700">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-slate-600">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="eyebrow mb-1.5">{children}</div>
}

export function ComplexityBar({ value }: { value: number }) {
  const tone = value >= 75 ? 'bg-rose-500' : value >= 50 ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div className="flex items-center gap-2" title={`Review complexity ${value}%`}>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${value}%` }} />
      </div>
      <span className="text-sm font-medium tabular-nums text-slate-700">{value}%</span>
    </div>
  )
}
