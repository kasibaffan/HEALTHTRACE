import { useState } from 'react'
import { ArrowDown, Ban, FileText, Flag, Gavel, ListChecks, Quote, ScrollText, Search, Sigma } from 'lucide-react'
import type { ChainNode, EvidenceChain as Chain } from '../types'
import { NEUTRAL_TONE, STATUS } from '../data/status'
import { SectionLabel } from './ui'
import { useReview } from './ReviewContext'

const KIND_LABEL: Record<ChainNode['kind'], string> = {
  finding: 'Finding', policy: 'Policy criterion', rule: 'Rule', requirement: 'Requirement', fact: 'Extracted fact',
  evidence: 'Evidence', document: 'Source document', search: 'Document search', outcome: 'Outcome',
}

function KindIcon({ kind, size = 16 }: { kind: ChainNode['kind']; size?: number }) {
  const props = { size, 'aria-hidden': true } as const
  switch (kind) {
    case 'policy': return <ScrollText {...props} />
    case 'rule': return <Sigma {...props} />
    case 'requirement': return <ListChecks {...props} />
    case 'fact': return <Flag {...props} />
    case 'evidence': return <Quote {...props} />
    case 'document': return <FileText {...props} />
    case 'search': return <Search {...props} />
    case 'outcome': return <Gavel {...props} />
    default: return <Ban {...props} />
  }
}

function Node({ node, selected, onSelect }: { node: ChainNode; selected: boolean; onSelect: () => void }) {
  const tone = node.tone === 'neutral' ? NEUTRAL_TONE : STATUS[node.tone]
  return (
    <button
      type="button" onClick={onSelect} aria-pressed={selected}
      className={`group w-full rounded-lg border px-3 py-2.5 text-left transition ${tone.soft} ${selected ? `${tone.border} ring-2 ring-offset-1 ring-brand-500/60 shadow-sm` : 'border-slate-200 hover:border-slate-300 hover:shadow-sm'}`}
    >
      <div className={`flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider ${tone.text}`}>
        <KindIcon kind={node.kind} size={13} /> {KIND_LABEL[node.kind]}
      </div>
      <div className="mt-0.5 break-words text-sm font-semibold text-slate-900">{node.title}</div>
      {node.subtitle && <div className="mt-0.5 line-clamp-2 break-words text-xs text-slate-600">{node.subtitle}</div>}
    </button>
  )
}

const Arrow = () => (
  <div className="flex justify-center py-1 text-slate-400" aria-hidden><ArrowDown size={16} /></div>
)

export function EvidenceChain({ data, initialSelected }: { data: Chain; initialSelected?: string }) {
  const { openDocument } = useReview()
  const shared = data.chain.filter((n) => !n.lane && n.kind !== 'outcome')
  const lanes = (['A', 'B'] as const).map((l) => data.chain.filter((n) => n.lane === l))
  const outcome = data.chain.find((n) => n.kind === 'outcome' && data.finding.status !== 'missing')
  const tail = data.finding.status === 'missing' ? data.chain.filter((n) => n.kind === 'outcome') : []
  const hasLanes = lanes[0].length > 0

  const firstEvidence = data.chain.find((n) => n.kind === 'evidence')?.id
  const [selectedId, setSelectedId] = useState<string | undefined>(initialSelected ?? firstEvidence ?? data.chain[0]?.id)
  const selected = data.chain.find((n) => n.id === selectedId)

  const sequence = [...shared.filter((n) => data.finding.status !== 'missing' || n.kind !== 'outcome'), ...tail]

  return (
    <section aria-label="Visual evidence chain">
      <SectionLabel>Evidence chain</SectionLabel>
      <p className="mb-3 text-xs text-slate-500">Each node is real data behind this finding. Select a node to inspect it.</p>
      <div>
        {sequence.map((n, i) => (
          <div key={n.id}>
            {i > 0 && <Arrow />}
            <Node node={n} selected={selectedId === n.id} onSelect={() => setSelectedId(n.id)} />
          </div>
        ))}
        {hasLanes && (
          <>
            <Arrow />
            <div className="grid grid-cols-2 gap-3">
              {lanes.map((nodes, idx) => (
                <div key={idx}>
                  <div className="mb-1.5 text-center text-[11px] font-semibold uppercase tracking-wider text-rose-700">{data.laneLabels[idx === 0 ? 'A' : 'B']}</div>
                  {nodes.map((n, i) => (
                    <div key={n.id}>
                      {i > 0 && <Arrow />}
                      <Node node={n} selected={selectedId === n.id} onSelect={() => setSelectedId(n.id)} />
                    </div>
                  ))}
                </div>
              ))}
            </div>
            {outcome && (<><Arrow /><Node node={outcome} selected={selectedId === outcome.id} onSelect={() => setSelectedId(outcome.id)} /></>)}
          </>
        )}
      </div>

      {selected && (
        <div className="mt-4 rounded-lg border border-slate-200 bg-white" aria-live="polite">
          <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Node details - {KIND_LABEL[selected.kind]}</div>
            {selected.documentId && selected.page && (
              <button className="text-xs font-medium text-brand-700 hover:underline" onClick={() => openDocument(selected.documentId!, selected.page!, selected.evidenceId ?? undefined)}>
                Open page {selected.page}
              </button>
            )}
          </div>
          <dl className="divide-y divide-slate-100">
            {Object.entries(selected.metadata).map(([k, v]) => (
              <div key={k} className="grid grid-cols-[7.5rem_1fr] gap-3 px-3 py-2 text-xs">
                <dt className="font-medium text-slate-500">{k}</dt>
                <dd className="break-words text-slate-800">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  )
}
