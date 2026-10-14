import { useEffect, useState } from 'react'
import { ArrowRight, Search, SearchX } from 'lucide-react'
import { api } from '../services/api'
import { useAsync } from '../hooks/useAsync'
import { caseStatusBadge } from '../data/status'
import { ComplexityBar, EmptyState, ErrorState, LoadingBlock, PageHeader } from '../components/ui'
import { useReview } from '../components/ReviewContext'

export function Cases() {
  const { version } = useReview()
  const [page, setPage] = useState(1)
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  useEffect(() => {
    const timer = window.setTimeout(() => { setPage(1); setSearch(query.trim()) }, 250)
    return () => window.clearTimeout(timer)
  }, [query])
  const { data, error, loading, reload } = useAsync(() => api.cases(page, search), [version, page, search])

  const rows = data?.items ?? []
  const pageCount = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1
  const searchPending = query.trim() !== search
  useEffect(() => {
    if (data && data.page === page && !searchPending && page > pageCount) setPage(pageCount)
  }, [data, page, pageCount, searchPending])

  return (
    <div>
      <PageHeader eyebrow="Case management" title="Cases" description="Prior authorization cases awaiting evidence review. Only the demo case includes a full evidence review." />
      <div className="card">
        <div className="border-b border-slate-200 p-3">
          <label className="relative block max-w-sm">
            <span className="sr-only">Search cases</span>
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" aria-hidden />
            <input value={query} onChange={(e) => { setQuery(e.target.value); setPage(1) }} placeholder="Search by case, patient, or condition"
              className="w-full rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30" />
          </label>
        </div>
        {loading && !data && <LoadingBlock label="Loading cases..." rows={5} />}
        {error && !data && <ErrorState message={`Failed to load cases. ${error}`} onRetry={reload} />}
        {error && data && <div role="alert" className="m-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">Could not refresh this case list. Showing the last loaded results. <button className="font-semibold underline" onClick={reload}>Retry</button></div>}
        {data && (loading || searchPending) && <div role="status" aria-live="polite" className="px-4 pt-3 text-xs text-slate-500">Updating case results...</div>}
        {data && (
          <div className="overflow-x-auto" aria-busy={loading}>
            <table className="w-full min-w-[860px]">
              <thead className="border-b border-slate-200 bg-slate-50/70">
                <tr>
                  <th className="th">Case ID</th><th className="th">Patient</th><th className="th">Condition</th><th className="th">Review status</th>
                  <th className="th">Complexity</th><th className="th">Missing evidence</th><th className="th">Conflicts</th><th className="th" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((c) => (
                  <tr key={c.id} className="transition hover:bg-slate-50">
                    <td className="td font-mono text-[13px] font-semibold text-slate-900">{c.caseNumber}</td>
                    <td className="td font-medium text-slate-900">{c.patient}</td>
                    <td className="td text-slate-600">{c.condition}</td>
                    <td className="td"><span className={`whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${caseStatusBadge(c.status)}`}>{c.status}</span></td>
                    <td className="td"><ComplexityBar value={c.complexity} /></td>
                    <td className="td">{c.missingEvidence > 0 ? <span className="font-medium text-amber-800">{c.missingEvidence} Missing</span> : <span className="text-slate-400">None</span>}</td>
                    <td className="td">{c.conflicts > 0 ? <span className="font-medium text-rose-700">{c.conflicts} Conflict{c.conflicts > 1 ? 's' : ''}</span> : <span className="text-slate-400">None</span>}</td>
                    <td className="td text-right">
                      {c.openable
                        ? <a href={`#/cases/${c.id}`} className="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline">Review <ArrowRight size={14} aria-hidden /></a>
                        : <span className="text-xs text-slate-400">Summary only</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && <EmptyState icon={<SearchX size={20} />} title="No cases found" body={query ? `Nothing matches "${query}".` : 'There are no cases yet.'} />}
            {data.total > 0 && <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3 text-sm text-slate-600">
              <span>Showing {(data.page - 1) * data.pageSize + 1}-{Math.min(data.page * data.pageSize, data.total)} of {data.total} cases</span>
              <nav aria-label="Case pages" className="flex items-center gap-2">
                <button className="btn-secondary px-3 py-1.5" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page <= 1 || loading || searchPending}>Previous</button>
                <span aria-live="polite" className="tabular-nums">Page {data.page} of {pageCount}</span>
                <button className="btn-secondary px-3 py-1.5" onClick={() => setPage((current) => Math.min(pageCount, current + 1))} disabled={page >= pageCount || loading || searchPending}>Next</button>
              </nav>
            </div>}
          </div>
        )}
      </div>
    </div>
  )
}
