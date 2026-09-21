// Data sources & sync — which of the bank's 25 APIs we have actually called, and what
// came back.
//
// This screen exists to be unflattering. A pending subscription is shown as pending; an
// API that has never been called says "never called"; a family that is simulated says
// SIMULATED in the same typeface as one that is real. The pending rows are the evidence
// that we have not overclaimed, which is worth more than a green wall would be.
//
// The one distinction worth reading twice: `sandbox_fixture`. IDBI's Atlas sandbox answers
// real endpoints with one canned payload shared across several APIs. "We called the bank's
// API" and "these are the bank's numbers" are different claims, and a row that was answered
// by the sandbox says **bank sandbox (mock, static)** rather than borrowing the credibility
// of a live pull.
//
// A second, newer distinction: `served_from_cache`. A night tonight's call failed, this
// platform can serve the last good response the same request got on an earlier night
// (`app/atlas/lastgood.py`). That row says **Bank API · last good pull** — the bytes are
// still the bank's, `last_success_at` says when they really arrived, and it is never
// counted as a live pull. `last_success_at` and `records` themselves are untouched by any
// of this: they stay the live figures the docstring in `app/routers/meta.py` says they are.

import {
  Activity, CircleCheck, CircleSlash, Clock, Database, History, Plug, TriangleAlert,
} from 'lucide-react'
import AppShell from '../components/AppShell'
import DataTable from '../components/DataTable'
import SourceBadge from '../components/SourceBadge'
import Empty from '../components/states/Empty'
import ErrorState from '../components/states/ErrorState'
import Loading from '../components/states/Loading'
import { useAuth } from '../auth/AuthContext'
import useAsync from '../lib/useAsync'
import { loadProvenance, loadSync } from '../domain/drishti'
import { badgeForFamilySource, badgeForMode } from '../domain/provenance'

export const SYNC_STATE = {
  never: { label: 'Never called', icon: CircleSlash, className: 'text-slate-600', row: '' },
  pending: { label: 'Subscription pending', icon: Clock, className: 'text-rag-ambertx', row: 'bg-amber-50/50' },
  ok: { label: 'OK', icon: CircleCheck, className: 'text-rag-greentx', row: '' },
  cached: { label: 'Bank API · last good pull', icon: History, className: 'text-idbi-green', row: '' },
  sandbox: { label: 'Bank sandbox (mock, static)', icon: Database, className: 'text-rag-ambertx', row: '' },
  error: { label: 'Error', icon: TriangleAlert, className: 'text-rag-redtx', row: 'bg-red-50/60' },
}

/**
 * One row's state, from the fields `metaSync` publishes.
 * Order matters: an error is an error even if the subscription is also pending, and a
 * cached reuse is checked before the sandbox/live split — `served_from_cache` and
 * `last_mode: 'cached'` are their own disclosure, not another flavour of sandbox.
 */
export function syncState(row) {
  const status = String(row?.last_status ?? '').toLowerCase()
  const subscription = String(row?.subscription_status ?? '').toLowerCase()
  if (row?.error || status === 'error' || status.startsWith('5') || status.startsWith('4')) return 'error'
  if (!row?.calls) {
    if (subscription && subscription !== 'approved' && subscription !== 'active') return 'pending'
    return 'never'
  }
  if (row?.served_from_cache || row?.last_mode === 'cached') return 'cached'
  if (row?.last_mode === 'sandbox_fixture' || row?.sandbox_fixture === true) return 'sandbox'
  if (row?.live === false) return 'sandbox'
  return 'ok'
}

function Runs({ runs }) {
  const entries = Object.entries(runs || {})
  if (entries.length === 0) return null
  return (
    <section className="grid gap-3 md:grid-cols-2">
      {entries.map(([product, run]) => (
        <div key={product} className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-bold uppercase text-slate-800">{product}</h3>
            {run?.published ? (
              <span className="rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-[11px] font-bold text-rag-greentx">published</span>
            ) : (
              <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-bold text-slate-600">no published run</span>
            )}
            {run?.provenance_mode && (
              <SourceBadge {...badgeForMode(run.provenance_mode, 'api')} />
            )}
          </div>
          {run?.published ? (
            <dl className="mt-2 space-y-1 text-xs text-slate-700">
              <div><dt className="inline font-semibold">Run </dt>
                <dd className="inline font-mono text-[11px]">{run.model_run_id}</dd></div>
              <div><dt className="inline font-semibold">Rows </dt>
                <dd className="inline">{run.n_rows?.toLocaleString('en-IN')}</dd></div>
              <div><dt className="inline font-semibold">Published </dt>
                <dd className="inline">{run.published_at ? new Date(run.published_at).toLocaleString('en-IN') : '—'}</dd></div>
              {run.generated_from && (
                <div className="pt-1"><dt className="font-semibold">Built from</dt>
                  <dd className="leading-relaxed text-slate-600">{run.generated_from}</dd></div>
              )}
            </dl>
          ) : (
            <p className="mt-2 text-xs leading-relaxed text-slate-600">
              Nothing is published for this product, so its screens have nothing to show. That is the honest state,
              not an outage.
            </p>
          )}
          {run?.provenance && (
            <ul className="mt-3 flex flex-wrap gap-1.5">
              {Object.entries(run.provenance).map(([family, source]) => (
                <li key={family} className="flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-700">
                  <span className="font-semibold">{family}</span>
                  <SourceBadge {...badgeForFamilySource(source)} iconOnly />
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </section>
  )
}

const DRIFT_TONE = {
  no_material_shift: 'text-rag-greentx',
  moderate_shift: 'text-rag-ambertx',
  significant_shift: 'text-rag-redtx',
}

const hours = (n) => (n == null ? '—' : n < 1 ? `${Math.round(n * 60)} min` : `${n.toFixed(1)} h`)

/**
 * How old the published run is, and how far its score distribution moved against the run it
 * superseded. Both come straight from `GET /meta/provenance`; the screen used to drop them,
 * which meant a stale run or a significant population shift was visible to the platform and
 * to nobody looking at it.
 */
function Freshness({ freshness, drift }) {
  const products = Array.from(new Set([...Object.keys(freshness || {}), ...Object.keys(drift || {})]))
  if (products.length === 0) return null
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="flex items-center gap-2 font-bold text-slate-800">
        <Activity size={16} className="text-idbi-green" aria-hidden="true" /> Freshness and drift
      </h3>
      <p className="mb-3 mt-1 text-xs leading-relaxed text-slate-600">
        How old the published run is, against the staleness limit the platform enforces, and how far its
        score distribution has moved from the run it replaced. Drift is a flag to investigate, not a verdict.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        {products.map((product) => {
          const f = freshness?.[product]
          const d = drift?.[product]
          return (
            <div key={product} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-bold uppercase text-slate-800">{product}</span>
                {f && (
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] font-bold ${
                    f.stale ? 'border-red-200 bg-red-50 text-rag-redtx' : 'border-green-200 bg-green-50 text-rag-greentx'
                  }`}>
                    {f.stale ? 'stale' : 'fresh'}
                  </span>
                )}
              </div>
              {f ? (
                <p className="mt-1.5 text-xs leading-relaxed text-slate-700">
                  Published <b>{hours(f.age_hours)}</b> ago
                  {f.threshold_hours != null && <> · limit {f.threshold_hours} h</>}
                  {f.n_rows != null && <> · {f.n_rows.toLocaleString('en-IN')} rows</>}
                  {f.reason && <> — {f.reason}</>}
                </p>
              ) : (
                <p className="mt-1.5 text-xs text-slate-600">No freshness recorded for this product.</p>
              )}
              {d?.available ? (
                <p className="mt-1.5 text-xs leading-relaxed text-slate-700">
                  Score drift (PSI) <b className={DRIFT_TONE[d.band] || 'text-slate-800'}>{d.psi}</b>
                  {d.band && <> — {String(d.band).replace(/_/g, ' ')}</>}
                  {d.score_field && <> on <code className="rounded bg-white px-1 font-mono text-[11px]">{d.score_field}</code></>}
                  {d.previous_model_run_id && (
                    <> · against run <code className="rounded bg-white px-1 font-mono text-[11px]">{String(d.previous_model_run_id).slice(0, 8)}</code></>
                  )}
                </p>
              ) : (
                <p className="mt-1.5 text-xs leading-relaxed text-slate-600">
                  No drift figure: {d?.reason || 'the platform published none for this product'}.
                </p>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

export default function DataSources() {
  const { isStatic } = useAuth()
  const live = !isStatic
  const sync = useAsync(({ signal }) => loadSync({ live, signal }), [live])
  const provenance = useAsync(({ signal }) => loadProvenance({ live, signal }), [live])

  const rows = sync.data || []
  const meta = sync.meta || {}
  const counts = rows.reduce((acc, r) => {
    const key = syncState(r)
    return { ...acc, [key]: (acc[key] || 0) + 1 }
  }, {})

  return (
    <AppShell
      view="sources"
      title="Data sources & sync"
      subtitle="Every bank API this product depends on, and what it has actually returned"
      help="sources"
    >
      {sync.error ? (
        <ErrorState title="Could not read the sync status" error={sync.error} onRetry={sync.reload} />
      ) : sync.loading ? (
        <Loading label="Reading the pull manifest…" />
      ) : (
        <>
          <section className="rounded-xl border border-slate-200 bg-white px-4 py-3">
            <p className="text-sm leading-relaxed text-slate-700">
              {meta.real_data
                ? <><b>Some data on this deployment came from the bank.</b> The rows marked live below are the ones it came from.</>
                : <><b>No screen in this product is showing the bank’s production numbers.</b> Every family below is a
                  fixture or simulated, and every figure in the app carries a badge saying which.</>}
              {meta.note && <> {meta.note}</>}
            </p>
            {meta.gateway && (
              <p className="mt-2 text-xs leading-relaxed text-slate-600">
                Atlas gateway: <b>{meta.gateway.mode}</b>
                {meta.gateway.writes_allowed ? ' · writes allowed' : ' · writes disabled'}
                {meta.gateway.reason && <> — {meta.gateway.reason}</>}
              </p>
            )}
            {provenance.data?.cached?.apis?.length > 0 && (
              <p className="mt-2 flex items-center gap-1.5 text-xs leading-relaxed text-slate-600">
                <History size={12} className="shrink-0 text-idbi-green" aria-hidden="true" />
                <span>
                  <b>{provenance.data.cached.apis.length}</b> API{provenance.data.cached.apis.length === 1 ? '' : 's'}{' '}
                  answered tonight from a cached last-good pull
                  {provenance.data.cached.last_reused_at && (
                    <>, most recently {new Date(provenance.data.cached.last_reused_at).toLocaleString('en-IN')}</>
                  )}. The bytes are the bank’s; they are not counted as live.
                </span>
              </p>
            )}
          </section>

          <Runs runs={meta.runs} />

          <Freshness freshness={provenance.data?.freshness} drift={provenance.data?.drift} />

          <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 p-4">
              <Plug size={16} className="text-idbi-green" aria-hidden="true" />
              <h3 className="flex-1 font-bold text-slate-800">Per-API status</h3>
              <ul className="flex flex-wrap gap-2 text-xs font-semibold">
                {Object.entries(counts).map(([key, n]) => (
                  <li key={key} className={`rounded-full border border-slate-200 px-2.5 py-1 ${SYNC_STATE[key].className}`}>
                    {n} {SYNC_STATE[key].label.toLowerCase()}
                  </li>
                ))}
              </ul>
            </div>

            {rows.length === 0 ? (
              <div className="p-4">
                <Empty
                  icon={Plug}
                  title={live ? 'No API has been registered against a pull yet' : 'This bundle has no backend to ask'}
                  hint={live
                    ? 'The batch runner writes a pull-manifest row the first time it calls an endpoint. Until then there is nothing to report — which is itself the status.'
                    : 'Sync status is read from the platform database. The frozen demo bundle was built without one, so nothing can be claimed here.'}
                />
              </div>
            ) : (
              <div className="overflow-x-auto scroll-thin">
                <DataTable caption={`${rows.length} bank APIs and their current pull status`}>
                  <thead className="bg-slate-50 text-xs">
                    <tr>
                      <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">API</th>
                      <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">What it gives us</th>
                      <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Used by</th>
                      <th scope="col" className="px-3 py-2 text-right font-semibold text-slate-600">Calls</th>
                      <th scope="col" className="px-3 py-2 text-right font-semibold text-slate-600">Records</th>
                      <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Last pull</th>
                      <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => {
                      const key = syncState(r)
                      const spec = SYNC_STATE[key]
                      const Icon = spec.icon
                      return (
                        <tr key={r.api_id} className={`border-t border-slate-100 ${spec.row}`}>
                          <th scope="row" className="px-3 py-2 text-left font-mono text-xs font-semibold text-slate-800">{r.api_id}</th>
                          <td className="px-3 py-2 text-slate-700">{r.label || '—'}</td>
                          <td className="px-3 py-2 text-slate-600">{(r.used_by || []).join(', ') || '—'}</td>
                          <td className="px-3 py-2 text-right text-slate-700">{r.calls ?? 0}</td>
                          <td className="px-3 py-2 text-right text-slate-700">{(r.records ?? 0).toLocaleString('en-IN')}</td>
                          <td className="whitespace-nowrap px-3 py-2 text-slate-600">
                            {r.last_pulled_at ? new Date(r.last_pulled_at).toLocaleString('en-IN') : '—'}
                            {r.latency_ms != null && <span className="text-slate-600"> · {Math.round(r.latency_ms)} ms</span>}
                          </td>
                          <td className={`px-3 py-2 font-semibold ${spec.className}`}>
                            <span className="inline-flex items-center gap-1.5">
                              <Icon size={14} aria-hidden="true" /> {spec.label}
                              {key === 'cached' && r.last_success_at && (
                                <span className="font-normal text-slate-600">
                                  {' '}({new Date(r.last_success_at).toLocaleString('en-IN')})
                                </span>
                              )}
                            </span>
                            {(r.error || r.note) && (
                              <span className="ml-1 font-normal text-slate-600">— {r.error || r.note}</span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </DataTable>
              </div>
            )}
          </section>

          {provenance.data?.products && (
            <section className="rounded-xl border border-slate-200 bg-white p-4">
              <h3 className="font-bold text-slate-800">Provenance, by data family</h3>
              <p className="mb-3 mt-1 text-xs leading-relaxed text-slate-600">
                {provenance.data.note}
              </p>
              <div className="space-y-3">
                {Object.entries(provenance.data.products).map(([product, entry]) => (
                  <div key={product}>
                    <div className="mb-1.5 text-xs font-extrabold uppercase tracking-wide text-idbi-green">
                      {product} <span className="font-normal normal-case text-slate-600">— {entry.status}</span>
                    </div>
                    <ul className="flex flex-wrap gap-1.5">
                      {Object.entries(entry.families || {}).map(([family, source]) => (
                        <li key={family} className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-700">
                          <span className="font-semibold">{family}</span>
                          <SourceBadge {...badgeForFamilySource(source, { cached: (entry.cached_families || []).includes(family) })} />
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </AppShell>
  )
}
