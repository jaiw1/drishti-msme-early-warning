import { ShieldCheck } from 'lucide-react'
import Empty from '../components/states/Empty'
import ScreenHelp from '../components/ScreenHelp'
import SessionBar from '../components/SessionBar'
import { useAuth } from '../auth/AuthContext'

/**
 * Administration. The screen itself is L10's later work (users, batch runs, the audit log
 * and its chain verification); what exists today is the guarded route, so <RequireRole/> is
 * exercised by the real app and not only by its tests.
 */
export default function Admin() {
  const { fullName } = useAuth()
  return (
    <div className="min-h-screen bg-slate-50">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-6 py-3.5">
        <div className="grid h-9 w-9 place-items-center rounded-lg bg-idbi-green text-white" aria-hidden="true">
          <ShieldCheck size={18} />
        </div>
        <div>
          <h1 className="text-lg font-extrabold text-slate-900">Administration</h1>
          <p className="text-xs text-slate-400">Users and roles, batch runs, and the append-only audit log</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <ScreenHelp screen="admin" />
          <SessionBar />
        </div>
      </header>
      <main id="main-content" className="p-6">
        <Empty
          icon={ShieldCheck}
          title="Administration is not built yet"
          hint={`Signed in as ${fullName || 'an administrator'}. The users, batch and audit screens arrive with the backend wiring; this route exists so the administrator-only guard is exercised in the running app.`}
        />
      </main>
    </div>
  )
}
