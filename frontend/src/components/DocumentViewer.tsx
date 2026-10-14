import { Fragment, useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, FileText, Highlighter, X } from 'lucide-react'
import { api } from '../services/api'
import { useAsync } from '../hooks/useAsync'
import { useDialogFocus } from '../hooks/useDialogFocus'
import type { DocumentFile, Evidence } from '../types'
import { ErrorState, LoadingBlock } from './ui'

function Line({ text, evidence, focusId }: { text: string; evidence: Evidence[]; focusId?: string }) {
  const hit = evidence.find((e) => text.includes(e.text))
  if (!hit) return <p className="leading-7 text-slate-800">{text}</p>
  const focused = hit.id === focusId
  const start = text.indexOf(hit.text)
  const before = text.slice(0, start)
  const after = text.slice(start + hit.text.length)
  const idx = hit.highlight ? hit.text.toLowerCase().indexOf(hit.highlight.toLowerCase()) : -1
  const parts = idx >= 0
    ? [hit.text.slice(0, idx), hit.text.slice(idx, idx + hit.highlight!.length), hit.text.slice(idx + hit.highlight!.length)]
    : [hit.text, '', '']

  return (
    <div className="leading-7 text-slate-800">
      {before}
      <span className={`rounded px-1 py-0.5 ${focused ? 'bg-amber-100 ring-1 ring-amber-300' : 'bg-slate-100 ring-1 ring-slate-200'}`}>
        {parts[0]}
        {parts[1] && <mark className={`rounded px-0.5 font-semibold ${focused ? 'bg-amber-300 text-amber-950' : 'bg-slate-300 text-slate-900'}`}>[ {parts[1].toUpperCase()} ]</mark>}
        {parts[2]}
      </span>
      {after}
      {focused && (
        <div className="mt-1.5 flex items-center gap-1.5 text-xs font-semibold text-amber-800">
          <Highlighter size={14} aria-hidden /> {hit.id} - This is the evidence supporting the finding.
        </div>
      )}
    </div>
  )
}

export function DocumentViewer({ target, onClose }: { target: { documentId: string; page: number; evidenceId?: string }; onClose: () => void }) {
  const dialogRef = useDialogFocus<HTMLDivElement>()
  const [docId, setDocId] = useState(target.documentId)
  const [page, setPage] = useState(target.page)
  const context = useAsync(() => api.documentContext(docId), [docId])

  useEffect(() => { setDocId(target.documentId); setPage(target.page) }, [target.documentId, target.page])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [onClose])

  const list: DocumentFile[] = context.data?.documents ?? []
  const doc = list.find((d) => d.id === docId)
  const content = doc?.content.find((p) => p.number === page)
  const pageEvidence = (context.data?.evidence ?? []).filter((e) => e.documentId === docId && e.page === page)
  const focus = pageEvidence.find((e) => e.id === target.evidenceId)

  const selectDoc = (d: DocumentFile) => { setDocId(d.id); setPage(1) }

  return (
    <div className="fixed inset-0 z-[65] flex items-center justify-center bg-slate-900/60 p-3 animate-fadeIn sm:p-6" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="viewer-title" className="focus:outline-none flex h-full max-h-[860px] w-full max-w-5xl animate-rise flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <FileText size={20} className="shrink-0 text-slate-500" aria-hidden />
            <div className="min-w-0">
              <h2 id="viewer-title" className="truncate text-base font-semibold text-slate-900">{doc?.name ?? 'Document'}</h2>
              <div className="text-xs text-slate-500">Page {page}{doc ? ` of ${doc.pages}` : ''} - Synthetic demo document</div>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button className="btn-ghost p-2" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft size={18} /></button>
            <button className="btn-ghost p-2" aria-label="Next page" disabled={!doc || page >= doc.pages} onClick={() => setPage((p) => p + 1)}><ChevronRight size={18} /></button>
            <button className="btn-ghost p-2" aria-label="Close document viewer" onClick={onClose}><X size={18} /></button>
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          <nav aria-label="Case documents" className="hidden w-56 shrink-0 overflow-y-auto border-r border-slate-200 bg-slate-50 p-3 md:block">
            <div className="eyebrow mb-2 px-1">Case documents</div>
            {list.map((d) => (
              <button key={d.id} onClick={() => selectDoc(d)} aria-current={d.id === docId}
                className={`mb-1 w-full rounded-lg px-2.5 py-2 text-left text-sm transition ${d.id === docId ? 'bg-white font-semibold text-brand-700 shadow-card ring-1 ring-slate-200' : 'text-slate-600 hover:bg-white'}`}>
                <div className="truncate">{d.name}</div>
                <div className="text-[11px] font-normal text-slate-500">{d.type} - {d.pages} {d.pages === 1 ? 'page' : 'pages'}</div>
              </button>
            ))}
          </nav>

          <div className="min-w-0 flex-1 overflow-y-auto bg-slate-200/70 p-4 sm:p-8">
            {context.loading && !context.data && <LoadingBlock label="Loading document..." rows={5} />}
            {context.error && !context.data && <ErrorState message={`Document unavailable. ${context.error}`} onRetry={context.reload} />}
            {content && (
              <article className="mx-auto min-h-[28rem] max-w-2xl rounded-sm bg-white px-8 py-10 shadow-lg sm:px-12" aria-label={`${doc?.name} page ${page}`}>
                {focus && (
                  <div className="mb-6 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                    <span className="font-semibold">Evidence highlighted.</span> Showing the exact passage cited for this finding.
                  </div>
                )}
                <div className="mb-1 font-mono text-[10px] uppercase tracking-widest text-slate-400">{doc?.name} - p.{page}</div>
                <h3 className="mb-5 border-b border-slate-200 pb-3 text-xl font-semibold text-slate-900">{content.heading}</h3>
                <div className="space-y-3 text-[15px]">
                  {content.lines.map((line, i) => (
                    <Fragment key={i}><Line text={line} evidence={pageEvidence} focusId={target.evidenceId} /></Fragment>
                  ))}
                </div>
                <div className="mt-12 border-t border-slate-100 pt-3 text-center text-[10px] uppercase tracking-widest text-slate-400">
                  Page {page} - Synthetic document for demonstration only
                </div>
              </article>
            )}
            {doc && !content && <p className="py-16 text-center text-sm text-slate-500">This page is not available in the demo.</p>}
          </div>
        </div>
      </div>
    </div>
  )
}
