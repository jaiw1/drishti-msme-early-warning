// Model & Metrics — the published run's own numbers, plus the pre-registered validation.
//
// `GET /drishti/validation` returns whatever `make validate` attached to the published run.
// The table below prints it as it is: pass, fail, **and pending**. A criterion that has not
// been run yet is shown as pending rather than quietly dropped or counted as a pass — the
// pending rows are the disclosure, and hiding them would be the dishonest move.

import { CircleCheck, CircleSlash, Clock, ShieldAlert, TriangleAlert } from 'lucide-react'
import AppShell from '../components/AppShell'
import Analytics from '../components/Analytics'
import DataTable from '../components/DataTable'
import Empty from '../components/states/Empty'
import ErrorState from '../components/states/ErrorState'
import Loading from '../components/states/Loading'
import { useAuth } from '../auth/AuthContext'
import useAsync from '../lib/useAsync'
import { loadMetrics, loadValidation } from '../domain/drishti'
import { badgeForMode } from '../domain/provenance'

const STATUS = {
  pass: { label: 'Pass', icon: CircleCheck, className: 'text-rag-greentx', row: '' },
  fail: { label: 'Fail', icon: TriangleAlert, className: 'text-rag-redtx', row: 'bg-red-50/60' },
  // A failure whose acceptance was recorded on the run in advance — still a failure (the
  // label says so), rendered in the failure colour family, but with its own icon and row
  // tint so it never reads as either a plain fail (still blocking) or a pass.
  accepted: { label: 'Fail — accepted', icon: ShieldAlert, className: 'text-rose-700', row: 'bg-rose-100/70' },
  pending: { label: 'Pending', icon: Clock, className: 'text-rag-ambertx', row: 'bg-amber-50/50' },
  skipped: { label: 'Skipped', icon: CircleSlash, className: 'text-slate-600', row: '' },
}

const statusOf = (raw) => {
  const key = String(raw ?? '').toLowerCase()
  if (key in STATUS) return key
  if (key === 'passed' || key === 'ok' || key === 'true') return 'pass'
  if (key === 'failed' || key === 'false') return 'fail'
  if (key === 'not_run' || key === 'todo' || key === '' || key === 'null' || key === 'undefined') return 'pending'
  return 'skipped'
}

/**
 * The report's criteria, whichever of the two shapes `report.json` used.
 *
 * `states` is the optional `criteria_states` map from `GET /drishti/validation` — id ->
 * `"pass"` / `"accepted_failure"` / `"blocking_failure"` / anything else. It is what tells
 * this table apart a failure nobody has looked at (blocking) from one that was reviewed and
 * signed off on in advance (accepted) — the report's own `status` field cannot say that on
 * its own. Called with one argument, this behaves exactly as it always has: every entry's
 * status comes from `statusOf` on the report's own fields, and an absent/empty `states` map
 * (old runs, the frozen snapshot) never changes that.
 */
export function criteriaRows(report, states) {
  const raw = report?.criteria ?? report?.results ?? report?.checks
  if (!raw) return []
  const entries = Array.isArray(raw)
    ? raw
    : Object.entries(raw).map(([id, value]) => (
      value && typeof value === 'object' ? { id, ...value } : { id, status: value }
    ))
  return entries.map((entry) => {
    const id = entry.id || entry.criterion || entry.name || '—'
    const fallback = statusOf(entry.status ?? entry.result ?? entry.outcome ?? entry.passed)
    const state = states?.[id]
    const status = state === 'accepted_failure' ? 'accepted'
      : state === 'blocking_failure' ? 'fail'
        : state === 'pass' ? 'pass'
          : fallback
    return {
      id,
      description: entry.description || entry.title || entry.metric || '',
      status,
      observed: entry.observed ?? entry.value ?? entry.actual ?? null,
      expected: entry.expected ?? entry.band ?? entry.threshold ?? null,
      note: entry.note || entry.reason || '',
    }
  })
}

function ValidationSummary({ validation }) {
  const data = validation.data
  if (validation.loading) return <Loading label="Loading the validation report…" />
  if (validation.error) {
    return <ErrorState title="Could not load the validation report" error={validation.error} onRetry={validation.reload} />
  }
  if (!data?.available) {
    return (
      <Empty
        icon={Clock}
        title="No validation report is attached to this run"
        hint={data?.note || 'The pre-registered criteria are run by `make validate` in msme-ews/; the batch runner attaches the report to the run it publishes. Until then nothing here claims to be validated.'}
      />
    )
  }

  const rows = criteriaRows(data.report, data.criteria_states)
  const counts = rows.reduce((acc, r) => ({ ...acc, [r.status]: (acc[r.status] || 0) + 1 }), {})
  // Each accepted row's own pre-registered rationale, keyed by criterion id — never
  // invented, only ever what `accepted_failures.criteria[].reason` actually says.
  const reasonById = new Map((data.accepted_failures?.criteria || []).map((c) => [c.id, c.reason]))

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 p-4">
        <div className="min-w-0 flex-1">
          <h3 className="font-bold text-slate-800">Pre-registered validation criteria</h3>
          <p className="mt-0.5 text-xs leading-relaxed text-slate-600">
            `validation/criteria.yaml` was committed before the first result, so the bands below were fixed in
            advance — the git timestamp is the pre-registration.
            {data.criteria_sha && <> Criteria SHA <code className="rounded bg-slate-100 px-1 font-mono text-[11px]">{String(data.criteria_sha).slice(0, 12)}</code>.</>}
          </p>
        </div>
        <ul className="flex flex-wrap gap-2 text-xs font-semibold">
          {['pass', 'fail', 'accepted', 'pending', 'skipped'].map((key) => counts[key] ? (
            <li key={key} className={`rounded-full border border-slate-200 px-2.5 py-1 ${STATUS[key].className}`}>
              {counts[key]} {STATUS[key].label.toLowerCase()}
            </li>
          ) : null)}
        </ul>
      </div>

      {data.accepted_failures && (
        <div className="border-b border-rose-200 bg-rose-50/70 px-4 py-3 text-xs leading-relaxed text-slate-700">
          <p>
            <b>
              {data.accepted_failures.accepted.length} criterion{data.accepted_failures.accepted.length === 1 ? '' : 's'} failed
              and {data.accepted_failures.accepted.length === 1 ? 'was' : 'were'} accepted in advance
            </b>
            {data.accepted_failures.recorded_at && (
              <> — recorded on this published run at{' '}
                <code className="rounded bg-white px-1 font-mono text-[11px]">{data.accepted_failures.recorded_at}</code>
              </>
            )}.
          </p>
          {data.accepted_failures.note && <p className="mt-1">{data.accepted_failures.note}</p>}
        </div>
      )}

      {rows.length === 0 ? (
        <div className="p-4">
          <Empty title="The report carries no criteria" hint="It was attached to the run, but has no per-criterion results in it." />
        </div>
      ) : (
        <div className="max-h-[420px] overflow-auto scroll-thin">
          <DataTable caption={`${rows.length} pre-registered validation criteria and their outcomes`}>
            <thead className="sticky top-0 z-10 bg-slate-50 text-xs">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Criterion</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">What it checks</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold text-slate-600">Observed</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold text-slate-600">Required</th>
                <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Result</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const spec = STATUS[r.status]
                const Icon = spec.icon
                // An accepted row shows the criterion's own pre-registered rationale for why
                // the failure was accepted; every other row keeps the report's plain note.
                const annotation = r.status === 'accepted' ? (reasonById.get(r.id) || r.note) : r.note
                return (
                  <tr key={r.id} className={`border-t border-slate-100 ${spec.row}`}>
                    <th scope="row" className="px-3 py-2 text-left font-mono text-xs font-semibold text-slate-800">{r.id}</th>
                    <td className="px-3 py-2 text-slate-700">{r.description || '—'}</td>
                    <td className="px-3 py-2 text-right font-semibold text-slate-800">
                      {r.observed === null ? '—' : String(r.observed)}
                    </td>
                    <td className="px-3 py-2 text-right text-slate-600">{r.expected === null ? '—' : String(r.expected)}</td>
                    <td className={`px-3 py-2 font-semibold ${spec.className}`}>
                      <span className="inline-flex items-center gap-1.5">
                        <Icon size={14} aria-hidden="true" /> {spec.label}
                      </span>
                      {annotation && <span className="ml-1 font-normal text-slate-600">— {annotation}</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </DataTable>
        </div>
      )}

      {data.verify_result && (
        <p className="border-t border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-relaxed text-slate-700">
          Run verification: <b>{String(data.verify_result.status ?? data.verify_result.ok ?? 'recorded')}</b>
          {data.verify_result.note && <> — {data.verify_result.note}</>}
        </p>
      )}
    </section>
  )
}

export default function ModelMetrics() {
  const { isStatic } = useAuth()
  const live = !isStatic
  const metrics = useAsync(({ signal }) => loadMetrics({ live, signal }), [live])
  const validation = useAsync(({ signal }) => loadValidation({ live, signal }), [live])
  const badge = badgeForMode(metrics.meta?.provenance_mode, metrics.source)

  return (
    <AppShell
      view="analytics"
      title="Model Performance"
      subtitle="Honest metrics, rank-ordering per portfolio, lead-time and model rigor"
      help="model"
      source={badge.source}
      sandbox={badge.sandbox}
      sourceDetail={badge.detail}
    >
      {metrics.error ? (
        <ErrorState title="Could not load the metrics" error={metrics.error} onRetry={metrics.reload} />
      ) : metrics.loading ? (
        <Loading label="Loading model metrics…" />
      ) : !metrics.data?.published ? (
        <Empty
          title="No model run is published"
          hint="Metrics describe a published run. Until the batch runner publishes one, this screen has nothing honest to show."
        />
      ) : (
        <>
          {metrics.data.generated_from && (
            <p className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs leading-relaxed text-slate-700">
              <b>Where these numbers come from: </b>{metrics.data.generated_from}
            </p>
          )}
          <Analytics metrics={metrics.data.metrics} rigor={metrics.data.rigor} />
          <div className="pt-2">
            <h2 className="text-lg font-extrabold text-slate-900">Validation</h2>
            <p className="mb-4 text-xs text-slate-600">
              Every criterion, with the ones that have not been run shown as pending rather than omitted.
            </p>
            <ValidationSummary validation={validation} />
          </div>
        </>
      )}
    </AppShell>
  )
}
