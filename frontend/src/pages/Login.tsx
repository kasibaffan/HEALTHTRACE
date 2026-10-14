import { useState, type FormEvent } from 'react'
import { Activity, Loader2 } from 'lucide-react'
import { api, type AuthSession } from '../services/api'

export function Login({ onAuthenticated }: { onAuthenticated: (session: AuthSession) => void }) {
  const [registering, setRegistering] = useState(false)
  const [fullName, setFullName] = useState('')
  const [organization, setOrganization] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(''); setBusy(true)
    try {
      const session = registering
        ? await api.register(fullName, email, password, confirmPassword, organization)
        : await api.login(email, password)
      onAuthenticated(session)
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }

  return <main className="grid min-h-screen place-items-center bg-slate-50 px-4 py-10">
    <section className="card w-full max-w-md p-6 sm:p-8">
      <div className="mb-6 flex items-center gap-3"><span className="grid h-11 w-11 place-items-center rounded-xl bg-brand-600 text-white"><Activity size={22} /></span><div><h1 className="text-lg font-bold text-slate-900">HEALTHTRACE AI</h1><p className="text-sm text-slate-500">Evidence Intelligence Platform</p></div></div>
      <h2 className="text-xl font-semibold text-slate-900">{registering ? 'Create your workspace' : 'Sign in'}</h2>
      <p className="mt-1 text-sm text-slate-600">{registering ? 'Create an account to access your organization workspace.' : 'Sign in to continue to your review workspace.'}</p>
      <form className="mt-6 space-y-4" onSubmit={submit}>
        {registering && <>
          <label className="block text-sm font-medium text-slate-700">Full name<input required minLength={2} maxLength={120} autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" /></label>
          <label className="block text-sm font-medium text-slate-700">Workspace name <span className="font-normal text-slate-400">(optional)</span><input maxLength={120} value={organization} onChange={(e) => setOrganization(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" /></label>
        </>}
        <label className="block text-sm font-medium text-slate-700">Email<input required type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" /></label>
        <label className="block text-sm font-medium text-slate-700">Password<input required type="password" minLength={registering ? 10 : 1} maxLength={128} autoComplete={registering ? 'new-password' : 'current-password'} value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" /></label>
        {registering && <label className="block text-sm font-medium text-slate-700">Confirm password<input required type="password" minLength={10} maxLength={128} autoComplete="new-password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" /></label>}
        {error && <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</div>}
        <button disabled={busy} className="btn-primary flex w-full items-center justify-center gap-2 py-2.5">{busy && <Loader2 size={16} className="animate-spin" />}{busy ? 'Please wait…' : registering ? 'Create account' : 'Sign in'}</button>
      </form>
      <p className="mt-5 text-center text-sm text-slate-600">{registering ? 'Already have an account?' : 'New to HealthTrace?'} <button className="font-semibold text-brand-700 hover:underline" onClick={() => { setRegistering(!registering); setError('') }}>{registering ? 'Sign in' : 'Create a workspace'}</button></p>
      <p className="mt-5 border-t border-slate-100 pt-4 text-xs leading-relaxed text-slate-500">Use only synthetic demo information. Account creation creates a new owner workspace in the current database.</p>
    </section>
  </main>
}
