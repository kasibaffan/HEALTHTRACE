import { useEffect, useRef, useState } from 'react'
import { ChevronRight, ClipboardCheck, FileText, HelpCircle, Sparkles, Upload } from 'lucide-react'
import { api } from '../services/api'
import { useAsync } from '../hooks/useAsync'
import { CaseReviewSkeleton, ComplexityBar, EmptyState, ErrorState, HumanReviewBadge, SectionLabel, StatusBadge, StatusIcon } from '../components/ui'
import { ReviewActions, ReviewRecordNote } from '../components/ReviewActions'
import { DocumentClassification } from '../components/DocumentClassification'
import { useReview } from '../components/ReviewContext'
import { STATUS } from '../data/status'
import type { Finding } from '../types'

function FindingRow({ finding }: { finding: Finding }) {
  const { openPassport } = useReview()
  return (
    <li className={`p-4 transition hover:bg-slate-50/60 sm:p-5`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full ${STATUS[finding.status].soft}`}><StatusIcon status={finding.status} /></span>
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{finding.criterionId}</div>
            <div className="text-base font-semibold text-slate-900">{finding.criterion}</div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <StatusBadge status={finding.status} />
              {finding.status !== 'match' && !finding.review && <HumanReviewBadge label="NEEDS HUMAN REVIEW" />}
            </div>
          </div>
        </div>
        <button className="btn-secondary border-brand-500/40 text-brand-700 hover:bg-brand-50" onClick={() => openPassport(finding.id)} aria-label={`Why? Open Evidence Passport for ${finding.criterion}`}>
          <HelpCircle size={15} aria-hidden /> WHY?
        </button>
      </div>
      <p className="mt-3 pl-11 text-sm leading-relaxed text-slate-600">{finding.explanation}</p>
      <div className="mt-3 space-y-2.5 pl-11">
        <ReviewRecordNote finding={finding} />
        <ReviewActions finding={finding} size="sm" />
      </div>
    </li>
  )
}

export function CaseReview({ caseId }: { caseId: string }) {
  const { version, openDocument, openPassport, refresh, notify } = useReview()
  const detail = useAsync(() => api.caseDetail(caseId), [caseId, version])
  const findings = useAsync(() => api.findings(caseId), [caseId, version])
  const timeline = useAsync(() => api.timeline(caseId), [caseId, version])
  const evidence = useAsync(() => api.evidence(caseId), [caseId, version])
  const fileInput = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const processingDocuments = detail.data?.documents.some((d) => d.status === 'UPLOADED' || d.status === 'PROCESSING') ?? false

  useEffect(() => {
    if (!processingDocuments || detail.loading) return
    const timer = window.setTimeout(detail.reload, 1500)
    return () => window.clearTimeout(timer)
  }, [caseId, detail.loading, detail.reload, processingDocuments])

  const upload = async (file?: File) => {
    if (!file) return
    const allowedExtensions = /\.(pdf|docx|txt|png|jpe?g)$/i
    if (!allowedExtensions.test(file.name)) {
      notify('Unsupported file type. Choose a PDF, DOCX, TXT, PNG, or JPG file.', 'error')
      if (fileInput.current) fileInput.current.value = ''
      return
    }
    if (file.size === 0) {
      notify('The selected file is empty.', 'error')
      if (fileInput.current) fileInput.current.value = ''
      return
    }
    setUploading(true)
    try {
      await api.upload(file, caseId)
      refresh()
      notify(`${file.name} uploaded. Document processing has started.`)
    } catch (e) {
      notify((e as Error).message, 'error')
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const err = detail.error ?? findings.error
  if (err && !detail.data) return <ErrorState message={`Failed to load case. ${err}`} onRetry={() => { detail.reload(); findings.reload() }} />
  if (!detail.data || !findings.data) return <CaseReviewSkeleton />

  const c = detail.data
  const list = findings.data
  const needsReview = c.status === 'Needs Review'
  const evById = new Map((evidence.data ?? []).map((e) => [e.id, e]))

  return (
    <div>
      <nav aria-label="Breadcrumb" className="mb-3 flex items-center gap-1 text-sm text-slate-500">
        <a href="#/cases" className="hover:text-slate-900">Cases</a><ChevronRight size={14} aria-hidden /><span className="font-medium text-slate-900">{c.id}</span>
      </nav>

      <section className="card mb-6 overflow-hidden">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 sm:px-6">
          <div>
            <div className="eyebrow text-brand-700">HealthTrace AI</div>
        <h1 className="mt-0.5 text-2xl font-semibold tracking-tight text-slate-900">Case #{c.caseNumber}</h1>
            <div className="mt-0.5 text-sm text-slate-500">{c.policyName}{c.payer ? ` - ${c.payer}` : ''}</div>
          </div>
          <div className="flex flex-col items-start gap-2 sm:items-end">
            {needsReview
              ? <HumanReviewBadge label="NEEDS HUMAN REVIEW" />
              : <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-emerald-800 ring-1 ring-inset ring-emerald-200">{c.status}</span>}
            <div className="flex items-center gap-2 text-xs text-slate-500">Review complexity <ComplexityBar value={c.complexity} /></div>
          </div>
        </div>
        <dl className="grid gap-x-6 gap-y-4 px-5 py-4 sm:grid-cols-2 sm:px-6 lg:grid-cols-4">
          {[['Patient', c.patient], ['Condition', c.condition], ['Requested procedure', c.procedure], ['Member ID', c.memberId]].map(([k, v]) => (
            <div key={k}><dt className="eyebrow">{k}</dt><dd className="mt-0.5 text-sm font-medium text-slate-900">{v}</dd></div>
          ))}
        </dl>
        <div className="flex items-start gap-3 border-t border-slate-200 bg-slate-50 px-5 py-3 text-sm text-slate-700 sm:px-6">
          <Sparkles size={16} className="mt-0.5 shrink-0 text-brand-600" aria-hidden />
          <p><span className="font-semibold text-slate-900">AI-assisted summary (for context, not a decision): </span>{c.summary}</p>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-6">
          <section className="card" aria-labelledby="policy-review">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5">
              <h2 id="policy-review" className="text-base font-semibold text-slate-900">Policy Review</h2>
              <span className="text-xs text-slate-500">{list.filter((f) => f.review).length} of {list.length} reviewed</span>
            </div>
            {list.length === 0
              ? <EmptyState icon={<ClipboardCheck size={20} />} title="No findings yet" body="Findings appear once documents have been analysed against the policy." />
              : <ul className="divide-y divide-slate-100">{list.map((f) => <FindingRow key={f.id} finding={f} />)}</ul>}
          </section>

          <section className="card" aria-labelledby="timeline">
            <div className="border-b border-slate-200 px-5 py-3.5">
              <h2 id="timeline" className="text-base font-semibold text-slate-900">Case Timeline</h2>
              <p className="text-xs text-slate-500">Every event is linked to its source evidence.</p>
            </div>
            <ol className="px-5 py-4">
              {(timeline.data ?? []).map((t, i, arr) => {
                const ev = evById.get(t.evidenceId)
                return (
                  <li key={t.id} className="relative flex gap-4 pb-5 last:pb-0">
                    {i < arr.length - 1 && <span className="absolute left-[7px] top-4 h-full w-px bg-slate-200" aria-hidden />}
                    <span className="relative mt-1 h-[15px] w-[15px] shrink-0 rounded-full border-2 border-brand-500 bg-white" aria-hidden />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-x-3">
                        <span className="w-14 text-sm font-semibold tabular-nums text-slate-900">{t.date}</span>
                        <span className="text-sm font-medium text-slate-900">{t.label}</span>
                      </div>
                      <div className="text-xs text-slate-600">{t.detail}</div>
                      {ev && (
                        <button className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline"
                          onClick={() => ev.findingIds[0] ? openPassport(ev.findingIds[0], ev.id) : openDocument(ev.documentId, ev.page, ev.id)}>
                          <FileText size={12} aria-hidden /> {ev.id} - {ev.documentName}, p.{ev.page}
                        </button>
                      )}
                    </div>
                  </li>
                )
              })}
            </ol>
          </section>
        </div>

        <aside className="space-y-6">
          <ReviewSummary findings={list} />
          <section className="card" aria-labelledby="documents">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3.5">
              <h2 id="documents" className="text-base font-semibold text-slate-900">Documents</h2>
              <button className="btn-secondary px-2.5 py-1.5 text-xs" onClick={() => fileInput.current?.click()} disabled={uploading}>
                <Upload size={13} aria-hidden /> {uploading ? 'Uploading...' : 'Upload'}
              </button>
              <input ref={fileInput} type="file" accept="application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/png,image/jpeg" className="hidden" onChange={(e) => upload(e.target.files?.[0])} aria-label="Upload document" />
            </div>
            {detail.error && <div role="alert" className="mx-4 mt-3 flex items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">Document status may be out of date. <button className="font-semibold underline" onClick={detail.reload}>Retry</button></div>}
            <ul className="divide-y divide-slate-100">
              {c.documents.map((d) => (
                <li key={d.id}>
                  <button className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:hover:bg-white" onClick={() => openDocument(d.id, 1)} disabled={!!d.status && d.status !== 'PROCESSED'} aria-label={`${d.name}${d.status && d.status !== 'PROCESSED' ? `, ${d.status.toLowerCase().replace('_', ' ')}` : ', open document'}`}>
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-600"><FileText size={17} aria-hidden /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-slate-900">{d.name}</span>
                    <span className="block text-xs text-slate-500">{d.type} - {d.pages} {d.pages === 1 ? 'page' : 'pages'}</span>
                    {d.status && <span className={`mt-1 inline-flex items-center gap-1.5 text-xs font-medium ${d.status === 'FAILED' ? 'text-rose-700' : d.status === 'PROCESSED' ? 'text-emerald-700' : 'text-amber-800'}`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${d.status === 'FAILED' ? 'bg-rose-500' : d.status === 'PROCESSED' ? 'bg-emerald-500' : 'animate-pulse bg-amber-500'}`} />
                      {d.status === 'UPLOADED' ? 'Queued for processing' : d.status === 'PROCESSING' ? `Processing${typeof d.progress === 'number' ? ` · ${d.progress}%` : ''}` : d.status === 'PROCESSED' ? 'Processed' : 'Processing failed'}
                    </span>}
                    {d.status === 'PROCESSING' && typeof d.progress === 'number' && <span className="mt-1 block h-1 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-label={`Processing ${d.name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={d.progress}><span className="block h-full rounded-full bg-brand-600 transition-all" style={{ width: `${Math.max(0, Math.min(100, d.progress))}%` }} /></span>}
                    {d.status === 'FAILED' && d.error && <span className="mt-1 block text-xs text-rose-700">{d.error}</span>}
                    </span>
                    <ChevronRight size={15} className="text-slate-400" aria-hidden />
                  </button>
                  <DocumentClassification doc={d} onChanged={detail.reload} />
                </li>
              ))}
            </ul>
          </section>

          <section className="card p-4">
            <SectionLabel>Human-in-the-loop</SectionLabel>
            <p className="text-sm leading-relaxed text-slate-600">
              HealthTrace never approves or denies a request. Every action you take is recorded with your name, the action, your reason, and a timestamp.
            </p>
            <a href="#/audit" className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline">View audit trail <ChevronRight size={14} aria-hidden /></a>
          </section>
        </aside>
      </div>
    </div>
  )
}

function ReviewSummary({ findings }: { findings: Finding[] }) {
  const { openPassport } = useReview()
  const count = (s: Finding['status']) => findings.filter((f) => f.status === s).length
  const reviewed = findings.filter((f) => f.review).length
  const pending = findings.filter((f) => !f.review && f.status !== 'match')
  const pct = findings.length ? Math.round((reviewed / findings.length) * 100) : 0
  return (
    <section className="card p-4" aria-labelledby="summary-title">
      <h2 id="summary-title" className="text-base font-semibold text-slate-900">Review Summary</h2>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        {(['match', 'missing', 'conflict'] as const).map((s) => (
          <div key={s} className={`rounded-lg px-2 py-2.5 ${STATUS[s].soft}`}>
            <div className={`text-2xl font-semibold tabular-nums ${STATUS[s].text}`}>{count(s)}</div>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-600">{s === 'match' ? 'Match' : s === 'missing' ? 'Missing' : 'Conflict'}</div>
          </div>
        ))}
      </div>
      <div className="mt-4">
        <div className="mb-1 flex justify-between text-xs text-slate-600"><span>Human review progress</span><span className="tabular-nums">{reviewed} of {findings.length}</span></div>
        <div className="h-2 overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Human review progress">
          <div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>
      <div className="mt-4">
        <SectionLabel>Awaiting reviewer</SectionLabel>
        {pending.length === 0
          ? <p className="text-sm text-slate-500">No open items. Every flagged finding has a recorded reviewer action.</p>
          : <ul className="space-y-1.5">{pending.map((f) => (
              <li key={f.id}>
                <button onClick={() => openPassport(f.id)} className="flex w-full items-center gap-2 rounded-lg border border-slate-200 px-2.5 py-2 text-left text-sm transition hover:bg-slate-50">
                  <StatusIcon status={f.status} size={15} /><span className="min-w-0 flex-1 truncate">{f.criterion}</span><ChevronRight size={14} className="text-slate-400" aria-hidden />
                </button>
              </li>))}</ul>}
      </div>
    </section>
  )
}
