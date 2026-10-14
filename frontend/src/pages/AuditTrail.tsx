import { Bot, Cpu, History, RefreshCw, ShieldCheck, User } from 'lucide-react'
import { api, CASE_ID } from '../services/api'
import { useAsync } from '../hooks/useAsync'
import { formatDateTime } from '../data/status'
import { EmptyState, ErrorState, LoadingBlock, PageHeader } from '../components/ui'
import { useReview } from '../components/ReviewContext'

function Actor({ name }: { name: string }) {
  const kind = name === 'HealthTrace AI' ? 'ai' : name === 'Rules Engine' ? 'rules' : name === 'System' ? 'system' : 'human'
  const style = {
    ai: 'bg-sky-50 text-sky-800 ring-sky-200', rules: 'bg-slate-100 text-slate-700 ring-slate-200',
    system: 'bg-slate-100 text-slate-700 ring-slate-200', human: 'bg-indigo-50 text-indigo-800 ring-indigo-200',
  }[kind]
  const Icon = kind === 'ai' ? Bot : kind === 'human' ? User : Cpu
  return <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}><Icon size={12} aria-hidden /> {name}</span>
}

export function AuditTrail() {
  const { version } = useReview()
  const { data, error, loading, reload } = useAsync(() => api.audit(CASE_ID), [version])

  return (
    <div>
      <PageHeader eyebrow="Accountability" title="Audit Trail" description="Every AI step, rule evaluation, and human action for case HT-10482, newest first."
        actions={<button className="btn-secondary" onClick={reload}><RefreshCw size={14} aria-hidden /> Refresh</button>} />
      {data && (
        <div className="mb-4 flex items-start gap-3 rounded-lg border border-indigo-200 bg-indigo-50/60 px-4 py-3 text-sm text-indigo-950">
          <ShieldCheck size={18} className="mt-0.5 shrink-0 text-indigo-600" aria-hidden />
          <p><b>{data.filter((e) => /^(Accepted|Overrode|Requested)/.test(e.action)).length} reviewer decisions</b> and {data.length} events are shown for this case. Machine steps and reviewer decisions are logged separately, so every outcome shows who or what produced it.</p>
        </div>
      )}
      <div className="card">
        {loading && !data && <LoadingBlock label="Loading audit trail..." rows={6} />}
        {error && !data && <ErrorState message={`Failed to load the audit trail. ${error}`} onRetry={reload} />}
        {data && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px]">
              <thead className="border-b border-slate-200 bg-slate-50/70">
                <tr><th className="th">Time</th><th className="th">Actor</th><th className="th">Action</th><th className="th">Finding</th><th className="th">Reason</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.map((e) => (
                  <tr key={e.id} className="transition hover:bg-slate-50">
                    <td className="td whitespace-nowrap tabular-nums text-slate-600">{formatDateTime(e.timestamp)}</td>
                    <td className="td"><Actor name={e.actor} /></td>
                    <td className="td font-medium text-slate-900">{e.action}</td>
                    <td className="td text-slate-700">{e.target}</td>
                    <td className="td text-slate-600">{e.reason ?? <span className="text-slate-300">-</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.length === 0 && <EmptyState icon={<History size={20} />} title="No audit events yet" body="Every AI extraction, rule evaluation, and reviewer action will be recorded here." />}
          </div>
        )}
      </div>
    </div>
  )
}
