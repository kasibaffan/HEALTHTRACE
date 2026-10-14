import { useEffect, useState } from 'react'
import { useHashRoute } from './hooks/useHashRoute'
import { useBackendStatus } from './hooks/useBackendStatus'
import { Layout } from './components/Layout'
import { ReviewProvider } from './components/ReviewContext'
import { Login } from './pages/Login'
import { api, setUnauthorizedHandler, type AuthSession } from './services/api'
import { Dashboard } from './pages/Dashboard'
import { Cases } from './pages/Cases'
import { CaseReview } from './pages/CaseReview'
import { EvidencePage } from './pages/Evidence'
import { Policies } from './pages/Policies'
import { AuditTrail } from './pages/AuditTrail'

export default function App() {
  const route = useHashRoute()
  const backend = useBackendStatus()
  const [session, setSession] = useState<AuthSession | null>(null)
  const [checkingSession, setCheckingSession] = useState(true)
  useEffect(() => {
    let live = true
    setUnauthorizedHandler(() => { if (live) setSession(null) })
    api.restoreSession().then((s) => { if (live) setSession(s) }).finally(() => { if (live) setCheckingSession(false) })
    return () => { live = false; setUnauthorizedHandler(null) }
  }, [])
  const logout = async () => { try { await api.logout() } finally { setSession(null) } }
  if (checkingSession) return <main className="grid min-h-screen place-items-center text-sm text-slate-500">Checking your session…</main>
  if (!session) return <Login onAuthenticated={setSession} />
  return (
    <ReviewProvider>
      <Layout route={route} session={session} onLogout={logout}>
        {!backend.online && (
          <div role="alert" className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <span><b>Review service unavailable.</b> Check that the backend is running and its database is reachable, then retry.</span>
            <button className="btn-secondary" onClick={backend.check} disabled={backend.checking}>{backend.checking ? 'Checking...' : 'Retry'}</button>
          </div>
        )}
        {route.page === 'dashboard' && <Dashboard />}
        {route.page === 'cases' && <Cases />}
        {route.page === 'case' && route.caseId && <CaseReview key={route.caseId} caseId={route.caseId} />}
        {route.page === 'evidence' && <EvidencePage />}
        {route.page === 'policies' && <Policies />}
        {route.page === 'audit' && <AuditTrail />}
      </Layout>
    </ReviewProvider>
  )
}
