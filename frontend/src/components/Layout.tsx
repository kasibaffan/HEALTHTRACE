import { useEffect, useState, type ReactNode } from 'react'
import { Activity, ClipboardList, FileSearch, History, LayoutDashboard, Menu, ScrollText, X } from 'lucide-react'
import type { Route } from '../hooks/useHashRoute'
import { useDialogFocus } from '../hooks/useDialogFocus'
import type { AuthSession } from '../services/api'

const NAV = [
  { id: 'dashboard', label: 'Dashboard', href: '#/', icon: LayoutDashboard },
  { id: 'cases', label: 'Cases', href: '#/cases', icon: ClipboardList },
  { id: 'evidence', label: 'Evidence', href: '#/evidence', icon: FileSearch },
  { id: 'policies', label: 'Policies', href: '#/policies', icon: ScrollText },
  { id: 'audit', label: 'Audit Trail', href: '#/audit', icon: History },
] as const

function Brand() {
  return (
    <a href="#/" className="flex items-center gap-2.5 px-1">
      <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-500 text-white"><Activity size={20} aria-hidden /></span>
      <span>
        <span className="block text-[15px] font-bold leading-tight tracking-wide text-white">HEALTHTRACE <span className="text-brand-500">AI</span></span>
        <span className="block text-[11px] leading-tight text-slate-400">Evidence Intelligence Platform</span>
      </span>
    </a>
  )
}

function Nav({ route, onNavigate }: { route: Route; onNavigate?: () => void }) {
  const active = route.page === 'case' ? 'cases' : route.page
  return (
    <nav aria-label="Primary" className="mt-8 space-y-1">
      {NAV.map(({ id, label, href, icon: Icon }) => (
        <a key={id} href={href} onClick={onNavigate} aria-current={active === id ? 'page' : undefined}
          className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${active === id ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}>
          <Icon size={18} aria-hidden /> {label}
        </a>
      ))}
    </nav>
  )
}

function Sidebar({ route, onNavigate }: { route: Route; onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col bg-slate-900 px-4 py-5">
      <Brand />
      <Nav route={route} onNavigate={onNavigate} />
      <div className="mt-auto rounded-lg border border-white/10 bg-white/5 p-3 text-xs leading-relaxed text-slate-300">
        <div className="mb-1 font-semibold text-white">Verify, don't trust.</div>
        HealthTrace doesn't ask the reviewer to trust the AI. It gives the reviewer the evidence to verify it.
      </div>
    </div>
  )
}

function MobileNavigation({ route, onClose }: { route: Route; onClose: () => void }) {
  const dialogRef = useDialogFocus<HTMLDivElement>()

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div ref={dialogRef} tabIndex={-1} className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
      <div className="absolute inset-0 bg-slate-900/50" onClick={onClose} />
      <div className="absolute inset-y-0 left-0 w-64 animate-slideIn"><Sidebar route={route} onNavigate={onClose} /></div>
    </div>
  )
}

export function Layout({ route, children, session, onLogout }: { route: Route; children: ReactNode; session: AuthSession; onLogout: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="min-h-screen lg:pl-64">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded focus:bg-white focus:px-3 focus:py-2">Skip to content</a>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block"><Sidebar route={route} /></aside>

      {open && <MobileNavigation route={route} onClose={() => setOpen(false)} />}

      <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur sm:px-6">
        <div className="flex items-center gap-2">
          <button className="btn-ghost p-2 lg:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}>{open ? <X size={18} /> : <Menu size={18} />}</button>
          <span className="hidden items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-200 sm:inline-flex">
            SYNTHETIC DEMO DATA - NO REAL PATIENT INFORMATION
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right leading-tight">
            <div className="text-sm font-medium text-slate-900">{session.user.fullName}</div>
            <div className="text-[11px] text-slate-500">{session.role.replace(/_/g, ' ')}</div>
          </div>
          <div className="grid h-9 w-9 place-items-center rounded-full bg-brand-100 text-sm font-semibold text-brand-700" aria-hidden>{session.user.fullName.split(/\s+/).map((n) => n[0]).slice(0, 2).join('').toUpperCase()}</div>
          <button className="btn-secondary px-2.5 py-1.5 text-xs" onClick={onLogout}>Sign out</button>
        </div>
      </header>

      <main id="main" className="mx-auto max-w-[1280px] px-4 py-6 sm:px-6 lg:py-8">{children}</main>
    </div>
  )
}
