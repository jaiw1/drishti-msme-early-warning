// Administration — users, roles, and the audit log.
//
// Two things this screen is careful about:
//
//   * A reset password is shown **once**, on screen, and never written anywhere else. It
//     is handed over out of band; it is not emailed, not logged, and the user it belongs to
//     must change it at first sign-in. The panel says so, and closing it loses the value.
//   * "Verify chain" is not decoration. The audit log is hash-chained: every row carries
//     the hash of the row before it, so a deleted or edited row breaks the chain at a
//     specific id. The button asks the server to recompute the whole chain and reports
//     exactly what came back, including the id of the first bad row.

import { useMemo, useState } from 'react'
import {
  KeyRound, ShieldCheck, ShieldX, TriangleAlert, UserPlus, UserRoundCheck, UserRoundX, Users,
} from 'lucide-react'
import AppShell from '../components/AppShell'
import DataTable from '../components/DataTable'
import Dialog from '../components/Dialog'
import Empty from '../components/states/Empty'
import ErrorState from '../components/states/ErrorState'
import Loading from '../components/states/Loading'
import { useToast } from '../components/Toasts'
import useAsync from '../lib/useAsync'
import { ROLE_LABEL } from '../auth/roles'
import {
  createUser, loadAudit, loadUsers, resetUserPassword, setUserActive, setUserRole, verifyAuditChain,
} from '../domain/drishti'

const ROLES = ['admin', 'manager', 'credit_officer', 'relationship_manager']
const PORTFOLIOS = ['MSME-CC', 'MSME-TL', 'Housing', 'Education', 'Agri', 'Retail-Unsecured', 'LAP', 'Auto']

function CreateUserDialog({ open, onClose, onCreated }) {
  const toast = useToast()
  const [form, setForm] = useState({ username: '', full_name: '', role: 'credit_officer', ein: '', scope: [] })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }))
  const einOk = !form.ein || /^EIN-\d{6}$/.test(form.ein)
  const valid = form.username.trim().length > 0 && einOk

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const body = {
        username: form.username.trim(),
        role: form.role,
        ...(form.full_name.trim() ? { full_name: form.full_name.trim() } : {}),
        ...(form.ein ? { ein: form.ein } : {}),
        ...(form.role === 'credit_officer' && form.scope.length ? { scope: form.scope } : {}),
      }
      const created = await createUser(body)
      onCreated?.(created)
      toast.audited(`User ${body.username} created as ${ROLE_LABEL[body.role]}.`)
      setForm({ username: '', full_name: '', role: 'credit_officer', ein: '', scope: [] })
      onClose()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Create a user"
      description="The new user is given a one-time initial password and must change it at first sign-in."
      testId="create-user-dialog"
      footer={
        <>
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green">Cancel</button>
          <button type="button" onClick={submit} disabled={busy || !valid} className="rounded-lg bg-idbi-green px-4 py-2 text-sm font-semibold text-white transition hover:bg-idbi-greendk focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green focus-visible:ring-offset-2 disabled:opacity-50">
            {busy ? 'Creating…' : 'Create user'}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="u-name" className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Username</label>
          <input id="u-name" value={form.username} onChange={(e) => set('username', e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green" />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="u-full" className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Full name</label>
          <input id="u-full" value={form.full_name} onChange={(e) => set('full_name', e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="u-role" className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Role</label>
            <select id="u-role" value={form.role} onChange={(e) => set('role', e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green">
              {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="u-ein" className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Employee number</label>
            <input id="u-ein" value={form.ein} placeholder="EIN-100123" onChange={(e) => set('ein', e.target.value)}
              aria-invalid={!einOk}
              className="rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green" />
            {!einOk && <p className="text-[11px] text-rag-redtx">Must look like EIN-100123.</p>}
          </div>
        </div>

        {form.role === 'credit_officer' && (
          <fieldset className="rounded-lg border border-slate-200 p-3">
            <legend className="px-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600">Portfolios this officer may see</legend>
            <p className="mb-2 text-[11px] leading-relaxed text-slate-600">
              Leave all unticked to give no scope at all. A credit officer with an empty scope sees an empty watch-list,
              which is the safe default.
            </p>
            <div className="grid grid-cols-2 gap-1.5">
              {PORTFOLIOS.map((p) => (
                <label key={p} className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={form.scope.includes(p)}
                    onChange={(e) => set('scope', e.target.checked ? [...form.scope, p] : form.scope.filter((x) => x !== p))}
                    className="accent-idbi-green"
                  />
                  {p}
                </label>
              ))}
            </div>
          </fieldset>
        )}

        {error && <p className="text-xs text-rag-redtx" role="alert">{error.message}</p>}
      </div>
    </Dialog>
  )
}

function ResetResult({ result, onClose }) {
  return (
    <Dialog
      open={Boolean(result)}
      onClose={onClose}
      title={`Initial password for ${result?.username}`}
      description="This is shown once and stored nowhere else. Hand it over out of band and close this panel."
      size="sm"
      testId="reset-result"
      footer={
        <button type="button" onClick={onClose} className="rounded-lg bg-idbi-green px-4 py-2 text-sm font-semibold text-white transition hover:bg-idbi-greendk focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green focus-visible:ring-offset-2">
          I have handed it over
        </button>
      }
    >
      <p className="select-all break-all rounded-lg border border-slate-300 bg-slate-50 p-3 text-center font-mono text-lg font-bold text-slate-900">
        {result?.initial_password}
      </p>
      <p className="mt-3 text-xs leading-relaxed text-slate-600">
        {result?.note || 'The user must change this at first sign-in; every other session they had has been revoked.'}
      </p>
    </Dialog>
  )
}

function UsersPanel() {
  const toast = useToast()
  const users = useAsync(({ signal }) => loadUsers({ signal }), [])
  const [creating, setCreating] = useState(false)
  const [resetResult, setResetResult] = useState(null)
  const [busyId, setBusyId] = useState(null)

  const run = async (id, fn, onOk) => {
    setBusyId(id)
    try {
      const result = await fn()
      onOk?.(result)
      users.reload()
    } catch (err) {
      toast.error('That administrative action failed.', err?.message)
    } finally {
      setBusyId(null)
    }
  }

  const rows = users.data || []

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 p-4">
        <Users size={16} className="text-idbi-green" aria-hidden="true" />
        <h2 className="flex-1 font-bold text-slate-800">Users and roles</h2>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-1.5 rounded-lg bg-idbi-green px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-idbi-greendk focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green focus-visible:ring-offset-2"
        >
          <UserPlus size={14} aria-hidden="true" /> Create user
        </button>
      </div>

      {users.error ? (
        <div className="p-4"><ErrorState title="Could not load users" error={users.error} onRetry={users.reload} /></div>
      ) : users.loading ? (
        <div className="p-4"><Loading label="Loading users…" /></div>
      ) : rows.length === 0 ? (
        <div className="p-4"><Empty title="No users" hint="Seed the roster with `python -m app.seeds`, or create one above." /></div>
      ) : (
        <div className="overflow-x-auto scroll-thin">
          <DataTable caption={`${rows.length} users, their roles and scope`}>
            <thead className="bg-slate-50 text-xs">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">User</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Role</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Scope</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">State</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold text-slate-600">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.id} className={`border-t border-slate-100 ${u.is_active ? '' : 'bg-slate-50'}`}>
                  <th scope="row" className="px-3 py-2 text-left">
                    <div className="font-semibold text-slate-800">{u.username}</div>
                    <div className="text-xs font-normal text-slate-600">{u.full_name} · {u.ein || 'no EIN'}</div>
                  </th>
                  <td className="px-3 py-2">
                    <label className="sr-only" htmlFor={`role-${u.id}`}>Role for {u.username}</label>
                    <select
                      id={`role-${u.id}`}
                      value={u.role}
                      disabled={busyId === u.id}
                      onChange={(e) => run(u.id, () => setUserRole({ userId: u.id, role: e.target.value, scope: u.scope }),
                        (r) => toast.audited(`${u.username} is now ${ROLE_LABEL[r.role] || r.role}.`))}
                      className="rounded-lg border border-slate-300 px-2 py-1 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green disabled:opacity-50"
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">
                    {u.role === 'credit_officer'
                      ? (u.scope?.length ? u.scope.join(', ') : <span className="text-rag-ambertx">no portfolios — sees nothing</span>)
                      : <span className="text-slate-600">scoped by role, not by portfolio</span>}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    <span className={u.is_active ? 'font-semibold text-rag-greentx' : 'font-semibold text-slate-600'}>
                      {u.is_active ? 'Active' : 'Deactivated'}
                    </span>
                    {u.must_change_password && <div className="text-rag-ambertx">must change password</div>}
                    {u.locked_until && <div className="text-rag-redtx">locked until {new Date(u.locked_until).toLocaleTimeString('en-IN')}</div>}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap justify-end gap-1.5">
                      <button
                        type="button"
                        disabled={busyId === u.id}
                        onClick={() => run(u.id, () => resetUserPassword({ userId: u.id }), (r) => {
                          setResetResult(r)
                          toast.audited(`Password reset for ${u.username}.`)
                        })}
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green disabled:opacity-50"
                      >
                        <KeyRound size={13} aria-hidden="true" /> Reset password
                      </button>
                      <button
                        type="button"
                        disabled={busyId === u.id}
                        onClick={() => run(u.id, () => setUserActive({ userId: u.id, active: !u.is_active }),
                          () => toast.audited(`${u.username} ${u.is_active ? 'deactivated' : 'activated'}.`))}
                        className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green disabled:opacity-50 ${
                          u.is_active
                            ? 'border-red-200 text-rag-redtx hover:bg-red-50'
                            : 'border-green-200 text-rag-greentx hover:bg-green-50'
                        }`}
                      >
                        {u.is_active
                          ? <><UserRoundX size={13} aria-hidden="true" /> Deactivate</>
                          : <><UserRoundCheck size={13} aria-hidden="true" /> Activate</>}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      )}

      <CreateUserDialog open={creating} onClose={() => setCreating(false)} onCreated={users.reload} />
      <ResetResult result={resetResult} onClose={() => setResetResult(null)} />
    </section>
  )
}

/** A number in as few digits as it honestly needs: 0.3437 stays 0.3437, 0.2500 reads 0.25. */
function auditNumber(n) {
  return String(Number(n.toFixed(4)))
}

/**
 * One payload value, in something a reviewer can read.
 *
 * A threshold change arrives as `{before, after}`, and template-stringing that gave
 * `red_thr=[object Object]` — a row that recorded the single most consequential change in
 * the product and showed none of it. A `{before, after}` pair now reads as an arrow, and
 * anything else object-shaped falls back to JSON rather than to a JavaScript noise word.
 */
export function auditValue(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') return Number.isFinite(v) ? auditNumber(v) : String(v)
  if (typeof v !== 'object') return String(v)
  if (!Array.isArray(v) && ('before' in v || 'after' in v)) {
    return `${auditValue(v.before ?? null)} → ${auditValue(v.after ?? null)}`
  }
  return JSON.stringify(v)
}

// The payload keys the platform actually writes (`app/routers/*.py` `payload={…}`), in the
// words a reviewer uses. Anything not listed is still shown — de-underscored and sentence
// cased — so a new audit action never loses its detail waiting for this map to catch up.
const FIELD_LABEL = {
  red_thr: 'Red threshold',
  amber_thr: 'Amber threshold',
  justification: 'Justification',
  threshold_change_id: 'Change id',
  action: 'Action',
  review_outcome: 'Review outcome',
  model_run_id: 'Model run',
  policy_version: 'Policy version',
  has_note: 'Note attached',
  was_generated: 'Had a generated draft',
  length_before: 'Length before',
  length_after: 'Length after',
  username: 'Username',
  full_name: 'Full name',
  role: 'Role',
  from: 'Role before',
  to: 'Role after',
  scope: 'Scope',
  ein: 'EIN',
  sessions_revoked: 'Sessions revoked',
  other_sessions_revoked: 'Other sessions revoked',
  initial_password: 'Initial password',
  locked_until: 'Locked until',
  route: 'Route',
  status: 'Status',
  reason: 'Reason',
  product: 'Product',
  verdict: 'Verdict',
  mode: 'Mode',
  gateway: 'Gateway',
  dry_run: 'Dry run',
}

/** `red_thr` -> "Red threshold"; anything unmapped -> "Sessions revoked"-style prose. */
export function fieldLabel(key) {
  if (FIELD_LABEL[key]) return FIELD_LABEL[key]
  const words = String(key).replace(/_/g, ' ').trim()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : String(key)
}

/**
 * The Detail cell: the first few payload keys, each rendered rather than stringified.
 *
 * Printed as `key=value` this column was the database's vocabulary, not a reviewer's —
 * `red_thr=0.3437 → 0.25 · justification=…` in the one table an auditor reads to find out
 * what a manager did.
 */
export function auditDetail(payload) {
  if (!payload || typeof payload !== 'object') return '—'
  const entries = Object.entries(payload)
  if (entries.length === 0) return '—'
  return entries.slice(0, 4).map(([k, v]) => `${fieldLabel(k)}: ${auditValue(v)}`).join(' · ')
}

function AuditPanel() {
  const [filters, setFilters] = useState({ actor: '', action: '', since: '' })
  const [applied, setApplied] = useState({ limit: 50 })
  const [verify, setVerify] = useState({ state: 'idle', result: null, error: null })
  const audit = useAsync(({ signal }) => loadAudit({ params: applied, signal }), [JSON.stringify(applied)])

  const rows = useMemo(() => audit.data || [], [audit.data])
  const actions = useMemo(() => [...new Set(rows.map((r) => r.action))].sort(), [rows])

  const runVerify = async () => {
    setVerify({ state: 'running', result: null, error: null })
    try {
      const result = await verifyAuditChain({})
      setVerify({ state: 'done', result, error: null })
    } catch (err) {
      setVerify({ state: 'done', result: null, error: err })
    }
  }

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 p-4">
        <ShieldCheck size={16} className="text-idbi-green" aria-hidden="true" />
        <div className="flex-1">
          <h2 className="font-bold text-slate-800">Audit log</h2>
          <p className="text-xs leading-relaxed text-slate-600">
            Append-only and hash-chained. The database refuses UPDATE and DELETE on this table; each row carries the
            hash of the one before it, so a tampered row breaks the chain at a known id.
          </p>
        </div>
        <button
          type="button"
          onClick={runVerify}
          disabled={verify.state === 'running'}
          className="inline-flex items-center gap-1.5 rounded-lg bg-idbi-green px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-idbi-greendk focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green focus-visible:ring-offset-2 disabled:opacity-50"
        >
          <ShieldCheck size={14} aria-hidden="true" />
          {verify.state === 'running' ? 'Verifying…' : 'Verify chain'}
        </button>
      </div>

      <div role="status" aria-live="polite">
        {verify.state === 'done' && (
          verify.error ? (
            <p className="flex items-start gap-2 border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-rag-redtx">
              <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
              Verification could not be completed: {verify.error.message}
            </p>
          ) : verify.result?.ok ? (
            <p className="flex items-start gap-2 border-b border-green-200 bg-green-50 px-4 py-3 text-sm text-rag-greentx">
              <ShieldCheck size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span>
                Chain intact — <b>{verify.result.checked?.toLocaleString('en-IN')}</b> rows recomputed and every hash
                matched. Nothing in this log has been edited or removed.
              </span>
            </p>
          ) : (
            <p className="flex items-start gap-2 border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-rag-redtx">
              <ShieldX size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span>
                <b>Chain broken.</b> {verify.result?.checked?.toLocaleString('en-IN')} rows checked; the first bad row is
                id <b>{verify.result?.first_bad_id ?? 'unknown'}</b>
                {verify.result?.reason && <> — {verify.result.reason}</>}. Treat everything after that id as unverified.
              </span>
            </p>
          )
        )}
      </div>

      <form
        className="flex flex-wrap items-end gap-3 border-b border-slate-200 p-3"
        onSubmit={(e) => {
          e.preventDefault()
          setApplied({
            limit: 50,
            ...(filters.actor.trim() ? { actor: filters.actor.trim() } : {}),
            ...(filters.action.trim() ? { action: filters.action.trim() } : {}),
            ...(filters.since ? { since: new Date(filters.since).toISOString() } : {}),
          })
        }}
      >
        <div className="flex flex-col gap-1">
          <label htmlFor="a-actor" className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Actor</label>
          <input id="a-actor" value={filters.actor} placeholder="username or user id"
            onChange={(e) => setFilters((f) => ({ ...f, actor: e.target.value }))}
            className="w-52 rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green" />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="a-action" className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Action</label>
          <input id="a-action" list="audit-actions" value={filters.action} placeholder="e.g. auth.password.changed"
            onChange={(e) => setFilters((f) => ({ ...f, action: e.target.value }))}
            className="w-60 rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green" />
          <datalist id="audit-actions">{actions.map((a) => <option key={a} value={a} />)}</datalist>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="a-since" className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Since</label>
          <input id="a-since" type="datetime-local" value={filters.since}
            onChange={(e) => setFilters((f) => ({ ...f, since: e.target.value }))}
            className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green" />
        </div>
        <button type="submit" className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green">
          Apply filters
        </button>
        <button
          type="button"
          onClick={() => { setFilters({ actor: '', action: '', since: '' }); setApplied({ limit: 50 }) }}
          className="rounded-lg px-3 py-1.5 text-sm font-semibold text-slate-600 transition hover:text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
        >
          Clear
        </button>
      </form>

      {audit.error ? (
        <div className="p-4"><ErrorState title="Could not read the audit log" error={audit.error} onRetry={audit.reload} /></div>
      ) : audit.loading ? (
        <div className="p-4"><Loading label="Reading the audit log…" /></div>
      ) : rows.length === 0 ? (
        <div className="p-4">
          <Empty title="No entries match those filters" hint="Nothing is hidden — the filters simply matched nothing. Clear them to see the whole log." />
        </div>
      ) : (
        <div className="max-h-[520px] overflow-auto scroll-thin" tabIndex={0} role="region" aria-label="Audit log, scrollable">
          <DataTable caption={`${rows.length} of ${audit.meta?.total ?? rows.length} audit entries, newest first`}>
            <thead className="sticky top-0 z-10 bg-slate-50 text-xs">
              <tr>
                <th scope="col" className="px-3 py-2 text-right font-semibold text-slate-600">#</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">When</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Actor</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Action</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Target</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-slate-100 align-top">
                  <th scope="row" className="px-3 py-2 text-right font-mono text-xs font-normal text-slate-600">{r.id}</th>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-700">{new Date(r.ts).toLocaleString('en-IN')}</td>
                  <td className="px-3 py-2 text-xs text-slate-700">
                    {r.actor_role || 'system'}
                    {r.actor_user_id && <div className="font-mono text-[10px] text-slate-600">{String(r.actor_user_id).slice(0, 8)}…</div>}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-800">{r.action}</td>
                  <td className="px-3 py-2 text-xs text-slate-600">
                    {r.target_type ? `${r.target_type} ${String(r.target_id ?? '').slice(0, 12)}` : '—'}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">
                    {auditDetail(r.payload)}
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      )}
    </section>
  )
}

export default function Admin() {
  return (
    <AppShell
      view="admin"
      title="Administration"
      subtitle="Users and roles, and the append-only audit log"
      help="admin"
    >
      <UsersPanel />
      <AuditPanel />
    </AppShell>
  )
}
