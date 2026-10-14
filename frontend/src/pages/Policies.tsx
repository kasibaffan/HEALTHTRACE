import { useState } from 'react'
import { ScrollText } from 'lucide-react'
import { api, CASE_ID } from '../services/api'
import { useAsync } from '../hooks/useAsync'
import { EmptyState, ErrorState, LoadingBlock, PageHeader, SectionLabel, StatusBadge } from '../components/ui'
import { useReview } from '../components/ReviewContext'

export function Policies() {
  const { version, openPassport, openDocument } = useReview()
  const policy = useAsync(() => api.policy(), [])
  const findings = useAsync(() => api.findings(CASE_ID), [version])
  const rules = useAsync(() => api.rules(), [version])
  const evidence = useAsync(() => api.evidence(CASE_ID), [version])
  const [selected, setSelected] = useState('PR-002')

  const err = (policy.error && !policy.data ? policy.error : null) ?? (findings.error && !findings.data ? findings.error : null)
  if (err) return <ErrorState message={`Failed to load policy review. ${err}`} onRetry={() => { policy.reload(); findings.reload() }} />
  if (!policy.data || !findings.data) return <div className="card"><LoadingBlock label="Loading policy..." rows={5} /></div>

  const p = policy.data
  if (p.criteria.length === 0) return <div><PageHeader eyebrow="Policy library" title={`${p.name} ${p.version}`} description={p.description} /><div className="card"><EmptyState icon={<ScrollText size={20} />} title="No criteria in this policy" body="This policy does not contain any configured rules." /></div></div>
  const crit = p.criteria.find((c) => c.id === selected) ?? p.criteria[0]
  const finding = findings.data.find((f) => f.criterionId === crit.id)
  const rule = rules.data?.find((r) => r.id === crit.ruleId)
  const evById = new Map((evidence.data ?? []).map((e) => [e.id, e]))
  const policyEv = crit.sourceEvidenceId ? evById.get(crit.sourceEvidenceId) : undefined
  const supporting = (finding?.evidenceIds ?? []).map((id) => evById.get(id)).filter((e) => !!e)

  return (
    <div>
      <PageHeader eyebrow="Policy library" title={`${p.name} ${p.version}`} description={`${p.description ? `${p.description} ` : ''}Select a criterion to see its requirement, rule, evidence, and current status.`} />
      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <section className="card overflow-hidden" aria-label="Policy criteria">
          <ul className="divide-y divide-slate-100">
            {p.criteria.map((c) => {
              const f = findings.data!.find((x) => x.criterionId === c.id)
              const active = c.id === crit.id
              return (
                <li key={c.id}>
                  <button onClick={() => setSelected(c.id)} aria-current={active} className={`w-full px-4 py-3.5 text-left transition ${active ? 'bg-brand-50/70 shadow-[inset_3px_0_0_0] shadow-brand-500' : 'hover:bg-slate-50'}`}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs font-semibold text-slate-500">{c.id}</span>
                      {f && <StatusBadge status={f.status} />}
                    </div>
                    <div className="mt-1 text-sm font-medium text-slate-900">{c.title.replace('>=', '≥')}</div>
                  </button>
                </li>
              )
            })}
          </ul>
        </section>

        <section className="card p-5 sm:p-6" aria-live="polite">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-700"><ScrollText size={20} aria-hidden /></span>
              <div>
                <div className="font-mono text-xs font-semibold text-slate-500">{crit.id}</div>
                <h2 className="text-lg font-semibold text-slate-900">{crit.title.replace('>=', '≥')}</h2>
              </div>
            </div>
            {finding && <StatusBadge status={finding.status} />}
          </div>

          <div className="mt-6 space-y-6">
            <div>
              <SectionLabel>Requirement</SectionLabel>
              <p className="text-sm leading-relaxed text-slate-900">{crit.requirement}</p>
              {(crit.sourceDocumentName || policyEv) && <div className="mt-1.5 text-xs text-slate-600">
                Source: {policyEv ? <button className="font-medium text-brand-700 hover:underline" onClick={() => openDocument(policyEv.documentId, policyEv.page, policyEv.id)}>{policyEv.documentName}, page {policyEv.page}</button> : <span>{crit.sourceDocumentName}{crit.sourcePage ? `, page ${crit.sourcePage}` : ''}</span>}
              </div>}
              {crit.sourceText && <blockquote className="mt-2 border-l-2 border-slate-300 pl-3 text-xs leading-relaxed text-slate-600">{crit.sourceText}</blockquote>}
            </div>
            <div>
              <SectionLabel>Rule</SectionLabel>
              <code className="rounded bg-slate-100 px-2 py-1 font-mono text-[13px]">{rule?.expression ?? (rules.loading ? 'Loading rule...' : 'Rule unavailable')}</code>
              {rules.error && <div role="alert" className="mt-2 text-xs text-rose-700">Rule details failed to load. <button className="font-semibold underline" onClick={rules.reload}>Retry</button></div>}
              {rule && <div className="mt-1.5 text-xs text-slate-500">{rule.evaluation && rule.result !== null ? <>Last evaluation: {rule.evaluation} = <b>{String(rule.result).toUpperCase()}</b></> : 'Rule evaluation is not available from the policy API.'}</div>}
            </div>
            <div>
              <SectionLabel>Evidence</SectionLabel>
              {evidence.error && !evidence.data ? <div role="alert" className="text-sm text-rose-700">Unable to load case evidence. <button className="font-semibold underline" onClick={evidence.reload}>Retry</button></div> : supporting.length === 0 ? (
                <div className="rounded-lg border border-dashed border-amber-300 bg-amber-50/60 px-3 py-2.5 text-sm text-amber-900">No supporting evidence found in the submitted documents.</div>
              ) : (
                <ul className="space-y-2">
                  {supporting.map((e) => e && (
                    <li key={e.id} className="rounded-lg border border-slate-200 p-3">
                      <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
                        <span><span className="font-mono font-semibold text-slate-700">{e.id}</span> - {e.documentName}, page {e.page}</span>
                        <span className={e.verified ? 'font-semibold text-emerald-700' : 'font-semibold text-amber-700'}>{e.verified ? 'Verified' : 'Not verified'}</span>
                      </div>
                      <div className="mt-1 text-sm italic text-slate-700">"{e.text}"</div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <SectionLabel>Current status</SectionLabel>
              {finding ? (
                <div className="flex flex-wrap items-center gap-3">
                  <StatusBadge status={finding.status} />
                  {finding.review && <span className="text-xs text-slate-600">Reviewer: {finding.review.action.replace('-', ' ')}</span>}
                  <button className="btn-primary" onClick={() => openPassport(finding.id)}>Open Evidence Passport</button>
                </div>
              ) : <span className="text-sm text-slate-500">Not evaluated.</span>}
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
