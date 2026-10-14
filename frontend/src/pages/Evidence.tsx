import { useState } from 'react'
import { BadgeCheck, Search, SearchX, TriangleAlert } from 'lucide-react'
import { api, CASE_ID } from '../services/api'
import { useAsync } from '../hooks/useAsync'
import { EmptyState, ErrorState, LoadingBlock, PageHeader } from '../components/ui'
import { useReview } from '../components/ReviewContext'

export function EvidencePage() {
  const { version, openPassport, openDocument } = useReview()
  const { data, error, loading, reload } = useAsync(() => api.evidence(CASE_ID), [version])
  const [query, setQuery] = useState('')
  const [type, setType] = useState('All')

  const types = ['All', ...Array.from(new Set((data ?? []).map((e) => e.evidenceType)))]
  const rows = (data ?? []).filter((e) =>
    (type === 'All' || e.evidenceType === type) &&
    `${e.id} ${e.factSummary ?? ''} ${e.documentName} ${e.text}`.toLowerCase().includes(query.toLowerCase()))

  return (
    <div>
      <PageHeader eyebrow="Evidence explorer" title="Evidence" description="Every quote the system relied on for case HT-10482. Select an evidence ID to open its Evidence Passport." />
      <div className="card">
        <div className="flex flex-wrap gap-3 border-b border-slate-200 p-3">
          <label className="relative block min-w-[220px] flex-1 sm:max-w-sm">
            <span className="sr-only">Search evidence</span>
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" aria-hidden />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search evidence ID, fact, document, or text"
              className="w-full rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30" />
          </label>
          <label>
            <span className="sr-only">Evidence type</span>
            <select value={type} onChange={(e) => setType(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30">
              {types.map((t) => <option key={t}>{t}</option>)}
            </select>
          </label>
        </div>
        {loading && !data && <LoadingBlock label="Analyzing evidence..." rows={6} />}
        {error && !data && <ErrorState message={`Unable to retrieve evidence. ${error}`} onRetry={reload} />}
        {data && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px]">
              <thead className="border-b border-slate-200 bg-slate-50/70">
                <tr><th className="th">Evidence ID</th><th className="th">Fact / Excerpt</th><th className="th">Document</th><th className="th">Page</th><th className="th">Type</th><th className="th">Verified</th><th className="th">Used by</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((e) => {
                  const open = () => (e.findingIds[0] ? openPassport(e.findingIds[0], e.id) : openDocument(e.documentId, e.page, e.id))
                  return (
                    <tr key={e.id} className="transition hover:bg-slate-50">
                      <td className="td"><button className="font-mono text-[13px] font-semibold text-brand-700 hover:underline" onClick={open}>{e.id}</button></td>
                      <td className="td max-w-xs">
                        <div className="font-medium text-slate-900">{e.factSummary ?? e.evidenceType}</div>
                        <div className="line-clamp-2 text-xs text-slate-500">"{e.text}"</div>
                      </td>
                      <td className="td text-slate-700">{e.documentName}</td>
                      <td className="td tabular-nums text-slate-700">{e.page}</td>
                      <td className="td text-slate-700">{e.evidenceType}</td>
                      <td className="td">
                        {e.verified
                          ? <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700"><BadgeCheck size={14} aria-hidden /> YES</span>
                          : <span className="inline-flex items-center gap-1 text-xs font-semibold text-amber-700"><TriangleAlert size={14} aria-hidden /> NO</span>}
                      </td>
                      <td className="td">
                        <div className="flex flex-wrap gap-1">
                          {e.usedBy.length ? e.usedBy.map((u) => (
                            <span key={u} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-700">{u.startsWith('PR-') ? `Policy Rule ${u}` : u}</span>
                          )) : <span className="text-xs text-slate-400">Not used</span>}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {rows.length === 0 && <EmptyState icon={<SearchX size={20} />} title="No evidence found" body="No evidence matches your search or filter." />}
          </div>
        )}
      </div>
    </div>
  )
}
