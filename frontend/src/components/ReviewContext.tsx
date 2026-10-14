import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { CheckCircle2, X, XCircle } from 'lucide-react'
import { api } from '../services/api'
import type { Finding, ReviewAction } from '../types'
import { EvidencePassport } from './EvidencePassport'
import { DocumentViewer } from './DocumentViewer'
import { OverrideModal } from './OverrideModal'

interface ViewerTarget { documentId: string; page: number; evidenceId?: string }
interface PassportTarget { findingId: string; focusEvidenceId?: string }
interface Toast { id: number; message: string; tone: 'success' | 'error' }

interface ReviewCtx {
  version: number
  refresh: () => void
  openPassport: (findingId: string, focusEvidenceId?: string) => void
  openDocument: (documentId: string, page: number, evidenceId?: string) => void
  act: (finding: Finding, action: ReviewAction) => Promise<void>
  notify: (message: string, tone?: 'success' | 'error') => void
}

const Ctx = createContext<ReviewCtx | null>(null)

export function useReview(): ReviewCtx {
  const value = useContext(Ctx)
  if (!value) throw new Error('useReview must be used inside ReviewProvider')
  return value
}

export function ReviewProvider({ children }: { children: ReactNode }) {
  const [version, setVersion] = useState(0)
  const [passport, setPassport] = useState<PassportTarget | null>(null)
  const [viewer, setViewer] = useState<ViewerTarget | null>(null)
  const [overriding, setOverriding] = useState<Finding | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])

  const refresh = useCallback(() => setVersion((v) => v + 1), [])

  const notify = useCallback((message: string, tone: 'success' | 'error' = 'success') => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, message, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200)
  }, [])

  const submit = useCallback(async (finding: Finding, action: ReviewAction, reason?: string) => {
    try {
      await api.review(finding.id, action, reason, finding.version)
      refresh()
      const done = { accept: 'Finding accepted', override: 'Override recorded', 'request-evidence': 'Evidence request recorded' }[action]
      notify(`${done}: ${finding.criterion}. Logged in the audit trail.`)
    } catch (e) {
      notify((e as Error).message, 'error')
      throw e
    }
  }, [notify, refresh])

  const act = useCallback(async (finding: Finding, action: ReviewAction) => {
    if (action === 'override') { setOverriding(finding); return }
    await submit(finding, action).catch(() => undefined)
  }, [submit])

  const value = useMemo<ReviewCtx>(() => ({
    version, refresh, notify, act,
    openPassport: (findingId, focusEvidenceId) => {
      setPassport({ findingId, focusEvidenceId })
      api.recordOpened(findingId).then(refresh)
    },
    openDocument: (documentId, page, evidenceId) => setViewer({ documentId, page, evidenceId }),
  }), [version, refresh, notify, act])

  return (
    <Ctx.Provider value={value}>
      {children}
      {passport && <EvidencePassport target={passport} onClose={() => setPassport(null)} />}
      {viewer && <DocumentViewer target={viewer} onClose={() => setViewer(null)} />}
      {overriding && (
        <OverrideModal
          finding={overriding}
          onCancel={() => setOverriding(null)}
          onConfirm={(reason) => submit(overriding, 'override', reason)}
        />
      )}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[80] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} role="status" className="pointer-events-auto flex animate-rise items-start gap-2.5 rounded-lg border border-slate-200 bg-white p-3 text-sm shadow-lg">
            {t.tone === 'success'
              ? <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-emerald-600" aria-hidden />
              : <XCircle size={18} className="mt-0.5 shrink-0 text-rose-600" aria-hidden />}
            <span className="flex-1 text-slate-700">{t.message}</span>
            <button aria-label="Dismiss" className="text-slate-400 hover:text-slate-600" onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))}>
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
