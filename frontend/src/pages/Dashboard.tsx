import { useState } from 'react'
import { ArrowRight, Bot, FileWarning, GitCompareArrows, History, Loader2, PlayCircle, UserCheck, Users } from 'lucide-react'
import { api, CASE_ID } from '../services/api'
import { useAsync } from '../hooks/useAsync'
import { navigate } from '../hooks/useHashRoute'
import { GOLDEN_PATH, PIPELINE } from '../data/demo'
import { caseStatusBadge, formatTime } from '../data/status'
import { EmptyState, ErrorState, LoadingBlock, Skeleton } from '../components/ui'
import { useReview } from '../components/ReviewContext'
import type { CaseSummary } from '../types'

function Metric({ label, value, icon: Icon, tone }: { label: string; value: number; icon: typeof Users; tone: string }) {
  return (
    <div className="card p-4 transition hover:shadow-md">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-600">{label}</span>
        <span className={`grid h-8 w-8 place-items-center rounded-lg ${tone}`}><Icon size={17} aria-hidden /></span>
      </div>
      <div className="mt-3 text-3xl font-semibold tabular-nums tracking-tight text-slate-900">{value}</div>
    </div>
  )
}

export function CaseRows({ cases }: { cases: CaseSummary[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px]">
        <thead className="border-b border-slate-200 bg-slate-50/70">
          <tr><th className="th">Case</th><th className="th">Patient</th><th className="th">Condition</th><th className="th">Status</th><th className="th" /></tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {cases.length === 0 ? <tr><td colSpan={5} className="px-4 py-8 text-center text-sm text-slate-500">No cases are available in this workspace yet.</td></tr> : cases.map((c) => (
            <tr key={c.id} className="transition hover:bg-slate-50">
              <td className="td font-mono text-[13px] font-semibold text-slate-900">{c.caseNumber}</td>
              <td className="td font-medium text-slate-900">{c.patient}</td>
              <td className="td text-slate-600">{c.condition}</td>
              <td className="td"><span className={`whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${caseStatusBadge(c.status)}`}>{c.status}</span></td>
              <td className="td text-right">
                {c.openable
                  ? <a href={`#/cases/${c.id}`} className="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline" onClick={(e) => e.stopPropagation()}>Open <ArrowRight size={14} aria-hidden /></a>
                  : <span className="text-xs text-slate-400">Summary only</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Dashboard() {
  const { version, refresh, notify } = useReview()
  const { data, error, loading, reload } = useAsync(() => api.dashboard(), [version])
  const [loadingDemo, setLoadingDemo] = useState(false)

  const loadDemo = async () => {
    setLoadingDemo(true)
    try {
      const demo = await api.loadDemo()
      refresh()
      notify(`Demo case ${demo.caseNumber} opened.`)
      navigate(`/cases/${demo.id}`)
    } catch (e) {
      notify((e as Error).message, 'error')
    } finally {
      setLoadingDemo(false)
    }
  }

  return (
    <div>
      <section className="card mb-6 overflow-hidden">
        <div className="grid gap-6 bg-gradient-to-br from-slate-900 to-brand-900 p-6 text-white sm:p-8 lg:grid-cols-[1fr_auto] lg:items-center">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-widest text-brand-100/80">Evidence Intelligence Platform for healthcare review</div>
            <h1 className="mt-2 max-w-2xl text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">
              Don't just give the healthcare review result. <span className="text-brand-100">Show exactly why.</span>
            </h1>
            <p className="mt-3 max-w-xl text-sm leading-relaxed text-slate-300">
              HealthTrace doesn't ask the reviewer to trust the AI. It gives the reviewer the evidence to verify it: every finding traces from policy criterion to rule, fact, and the exact text in the source document. AI assists. The reviewer decides.
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row lg:flex-col">
            <button onClick={loadDemo} disabled={loadingDemo} className="btn bg-white px-5 py-3 text-base font-semibold text-slate-900 shadow hover:bg-brand-50">
              {loadingDemo ? <Loader2 size={18} className="animate-spin" aria-hidden /> : <PlayCircle size={18} aria-hidden />} Load Demo Case
            </button>
            <a href={`#/cases/${CASE_ID}`} className="btn border border-white/25 px-5 py-3 text-white hover:bg-white/10">Open HT-10482 <ArrowRight size={16} aria-hidden /></a>
          </div>
        </div>
        <ol className="grid divide-y divide-slate-200 border-t border-slate-200 bg-slate-50 sm:grid-cols-5 sm:divide-x sm:divide-y-0" aria-label="How HealthTrace works">
          {PIPELINE.map((p, i) => (
            <li key={p.step} className="px-5 py-3">
              <div className={`flex items-center gap-1.5 text-sm font-semibold ${p.step === 'Review' ? 'text-indigo-700' : 'text-slate-900'}`}>
                <span className="text-xs tabular-nums text-slate-400">{i + 1}</span> {p.step}
              </div>
              <div className="mt-0.5 text-xs leading-snug text-slate-500">{p.detail}</div>
            </li>
          ))}
        </ol>
      </section>

      {loading && !data && (
        <div role="status" aria-live="polite">
          <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-5">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-24" />)}</div>
          <Skeleton className="h-56" />
          <span className="sr-only">Loading dashboard</span>
        </div>
      )}
      {error && !data && <ErrorState message={error} onRetry={reload} />}
      {data && (
        <>
          <section aria-label="Key metrics" className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Metric label="Active Cases" value={data.activeCases} icon={Users} tone="bg-slate-100 text-slate-700" />
            <Metric label="Needs Review" value={data.needsReview} icon={UserCheck} tone="bg-indigo-50 text-indigo-700" />
            <Metric label="Missing Evidence" value={data.missingEvidence} icon={FileWarning} tone="bg-amber-50 text-amber-700" />
            <Metric label="Conflicts" value={data.conflicts} icon={GitCompareArrows} tone="bg-rose-50 text-rose-700" />
            <Metric label="Human Reviews Today" value={data.humanReviewsToday} icon={Bot} tone="bg-emerald-50 text-emerald-700" />
          </section>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
            <section className="card min-w-0">
              <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
                <h2 className="text-base font-semibold text-slate-900">Recent Cases</h2>
                <a href="#/cases" className="text-sm font-medium text-brand-700 hover:underline">View all</a>
              </div>
              <CaseRows cases={data.recentCases} />
            </section>

            <div className="space-y-6">
            <ActivityFeed />
            <section className="card p-5" aria-label="Guided demo">
              <div className="eyebrow mb-1 text-brand-700">Guided demo</div>
              <h2 className="mb-4 text-base font-semibold text-slate-900">Where to start</h2>
              <ol className="space-y-3">
                {GOLDEN_PATH.map((s, i) => (
                  <li key={s.title} className="flex gap-3">
                    <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand-50 text-[11px] font-semibold text-brand-700">{i + 1}</span>
                    <div><div className="text-sm font-medium text-slate-900">{s.title}</div><div className="text-xs leading-relaxed text-slate-600">{s.body}</div></div>
                  </li>
                ))}
              </ol>
            </section>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function ActivityFeed() {
  const { version } = useReview()
  const { data, error, loading, reload } = useAsync(() => api.audit(CASE_ID), [version])
  const items = (data ?? []).slice(0, 5)
  return (
    <section className="card" aria-labelledby="activity-title">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h2 id="activity-title" className="text-base font-semibold text-slate-900">Review Activity</h2>
        <a href="#/audit" className="text-sm font-medium text-brand-700 hover:underline">Audit trail</a>
      </div>
      {loading && !data && <LoadingBlock label="Loading activity..." rows={3} />}
      {error && !data && <div className="p-4 text-sm text-slate-600">Unable to load activity. <button className="font-medium text-brand-700 hover:underline" onClick={reload}>Retry</button></div>}
      {data && items.length === 0 && <EmptyState icon={<History size={20} />} title="No audit events yet" body="Activity appears here as evidence is extracted and reviewers act." />}
      {items.length > 0 && (
        <ol className="divide-y divide-slate-100">
          {items.map((e) => (
            <li key={e.id} className="flex gap-3 px-4 py-3">
              <span className="w-16 shrink-0 pt-0.5 text-xs tabular-nums text-slate-500">{formatTime(e.timestamp)}</span>
              <div className="min-w-0">
                <div className="text-sm font-medium text-slate-900">{e.action}</div>
                <div className="truncate text-xs text-slate-500" title={e.target}>{e.actor} - {e.target}</div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
