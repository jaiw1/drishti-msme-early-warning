// Where the Red and Amber lines sit, who moved them, and why.
//
// A threshold is a business decision, not a model output. Three things follow, and this
// screen is built around them:
//
//   * moving one changes what officers are asked to work, so it needs a justification and
//     a confirmation, not a slider that commits on release;
//   * nothing is rescored. `PUT /drishti/threshold` writes one `threshold_change` row and
//     returns `rescored: false`; bands are recomputed on read. The screen says so, because
//     "we moved the line" and "we changed the model" are very different claims;
//   * the history is the audit. Every past change, its author's justification, and what it
//     did to the bands is on this page.

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { History, SlidersHorizontal, TriangleAlert } from 'lucide-react'
import AppShell from '../components/AppShell'
import Dialog from '../components/Dialog'
import DataTable from '../components/DataTable'
import Empty from '../components/states/Empty'
import ErrorState from '../components/states/ErrorState'
import Loading from '../components/states/Loading'
import { useToast } from '../components/Toasts'
import { useAuth } from '../auth/AuthContext'
import useAsync from '../lib/useAsync'
import { inr, pct } from '../lib/format'
import { loadThreshold, saveThreshold } from '../domain/drishti'
import { badgeForMode } from '../domain/provenance'

const MIN_JUSTIFICATION = 10

/**
 * The rationale behind the current lines.
 *
 * DM-5 may emit `method`, `cost_params` and `alternatives`; the platform emits a
 * `cost_model` with a cost curve. Read whichever is present and say plainly when neither
 * is — an unexplained threshold is exactly the thing this panel exists to prevent.
 */
function CostRationale({ cost }) {
  if (!cost) {
    return (
      <Empty
        title="This run published no cost rationale"
        hint="The thresholds in force were set without a cost model attached to the run, so this screen cannot tell you what trade-off they encode. The change history below still records who set them and why."
      />
    )
  }

  const curve = (cost.curve || cost.alternatives || []).map((p) => ({
    thr: +(Number(p.threshold ?? p.red_thr) * 100).toFixed(1),
    cost: Number(p.expected_cost ?? p.cost ?? 0) / 1e5,
    missed: Number(p.missed_npa ?? p.missed ?? 0),
    fp: Number(p.false_positives ?? p.fp ?? 0),
    flagged: Number(p.n_flagged ?? p.flagged ?? 0),
  })).filter((p) => Number.isFinite(p.thr))

  const facts = [
    cost.method && { label: 'Method', value: String(cost.method) },
    cost.cost_missed_npa != null && { label: 'Cost of a missed NPA', value: inr(cost.cost_missed_npa) },
    cost.cost_false_positive != null && { label: 'Cost of a false positive', value: inr(cost.cost_false_positive) },
    cost.ratio_missed_to_fp != null && { label: 'Missed NPA : false positive', value: `${cost.ratio_missed_to_fp} : 1` },
    cost.lgd != null && { label: 'Loss given default', value: pct(cost.lgd, 0) },
    cost.provision_rate != null && { label: 'Provisioning rate', value: pct(cost.provision_rate, 0) },
    cost.officer_review_hours != null && { label: 'Officer review time', value: `${cost.officer_review_hours} h per flag` },
  ].filter(Boolean)

  const params = cost.cost_params && typeof cost.cost_params === 'object'
    ? Object.entries(cost.cost_params).map(([k, v]) => ({ label: k.replace(/_/g, ' '), value: String(v) }))
    : []

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <h3 className="font-bold text-slate-800">Why the lines sit where they do</h3>
      <p className="mb-4 mt-1 max-w-3xl text-xs leading-relaxed text-slate-600">
        A missed NPA costs the book far more than an officer reviewing an account that turns out fine, so the cut-off
        is chosen where expected cost is lowest — not where accuracy looks best. Moving the Red line left catches more
        coming defaults and buys more work; moving it right does the opposite.
        {cost.provenance && (
          <> Costs here are <b>{Object.entries(cost.provenance).map(([k, v]) => `${k}: ${v}`).join(', ')}</b>.</>
        )}
      </p>

      {(facts.length > 0 || params.length > 0) && (
        <dl className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {[...facts, ...params].map((f) => (
            <div key={f.label} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <dt className="text-[11px] uppercase tracking-wide text-slate-600">{f.label}</dt>
              <dd className="mt-0.5 font-bold text-slate-800">{f.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {curve.length > 1 && (
        <>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={curve} margin={{ top: 14, right: 12, left: -6, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="thr" type="number" domain={['dataMin', 'dataMax']} tick={{ fontSize: 10, fill: '#475569' }} unit="%"
                label={{ value: 'Red cut-off', fontSize: 10, fill: '#475569', position: 'insideBottom', dy: 10 }} />
              <YAxis yAxisId="l" tick={{ fontSize: 10, fill: '#475569' }} unit=" L" />
              <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 10, fill: '#475569' }} />
              <Tooltip formatter={(v, n) => (n === 'Expected cost' ? [`₹${(+v).toFixed(1)} L`, n] : [v, n])}
                labelFormatter={(l) => `cut-off ${l}%`} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              {cost.chosen_red_thr != null && (
                <ReferenceLine x={+(cost.chosen_red_thr * 100).toFixed(1)} yAxisId="l" stroke="#b91c1c" strokeDasharray="4 4"
                  label={{ value: 'in force', fontSize: 9, fill: '#b91c1c', position: 'top' }} />
              )}
              <Line yAxisId="l" type="monotone" dataKey="cost" name="Expected cost" stroke="#02684F" strokeWidth={2.5} dot={false} isAnimationActive={false} />
              <Line yAxisId="r" type="monotone" dataKey="missed" name="NPAs missed" stroke="#b91c1c" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line yAxisId="r" type="monotone" dataKey="fp" name="False positives" stroke="#c2410c" strokeWidth={2} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
          {cost.expected_annual_saving != null && (
            <p className="mt-2 text-xs leading-relaxed text-slate-600">
              At the cut-off in force, the run puts the annual saving at <b>{inr(cost.expected_annual_saving)}</b>.
              That is the cost model’s own arithmetic on this book, not a realised figure.
            </p>
          )}
        </>
      )}
    </section>
  )
}

function ChangeDialog({ open, onClose, current, onSaved }) {
  const toast = useToast()
  const [red, setRed] = useState('')
  const [amber, setAmber] = useState('')
  const [justification, setJustification] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const firstRef = useRef(null)

  useEffect(() => {
    if (!open) return
    setRed(current?.red_thr != null ? String((current.red_thr * 100).toFixed(2)) : '')
    setAmber(current?.amber_thr != null ? String((current.amber_thr * 100).toFixed(2)) : '')
    setJustification('')
    setError(null)
  }, [open, current])

  const redValue = Number(red) / 100
  const amberValue = Number(amber) / 100
  const problems = []
  if (!Number.isFinite(redValue) || redValue <= 0 || redValue >= 1) problems.push('Red must be between 0 and 100%.')
  if (!Number.isFinite(amberValue) || amberValue <= 0 || amberValue >= 1) problems.push('Amber must be between 0 and 100%.')
  if (Number.isFinite(redValue) && Number.isFinite(amberValue) && amberValue >= redValue) {
    problems.push('Amber must sit below Red — otherwise no account can ever be Amber.')
  }
  if (justification.trim().length < MIN_JUSTIFICATION) {
    problems.push(`A justification of at least ${MIN_JUSTIFICATION} characters is required; it is stored with the change.`)
  }

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await saveThreshold({
        live: true, red_thr: redValue, amber_thr: amberValue, justification: justification.trim(),
      })
      const moved = result?.rebucketed
      toast.audited(
        `Thresholds changed to Red ≥ ${pct(result.red_thr, 2)}, Amber ≥ ${pct(result.amber_thr, 2)}.`,
        moved
          ? `Bands now: ${moved.red} red, ${moved.amber} amber, ${moved.green} green. No score row was modified.`
          : 'No score row was modified.',
      )
      onSaved?.(result)
      onClose()
    } catch (err) {
      setError(err)
      toast.error('Could not change the thresholds.', err?.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Change the Red and Amber thresholds"
      description="This changes what every officer is asked to work tomorrow morning. It does not re-score anything."
      initialFocusRef={firstRef}
      testId="threshold-dialog"
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy || problems.length > 0}
            className="rounded-lg bg-idbi-green px-4 py-2 text-sm font-semibold text-white transition hover:bg-idbi-greendk focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green focus-visible:ring-offset-2 disabled:opacity-50"
          >
            {busy ? 'Applying…' : 'Confirm and apply'}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="thr-red" className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Red — act now (%)</label>
            <input
              id="thr-red"
              ref={firstRef}
              type="number"
              inputMode="decimal"
              min="0.01"
              max="99.99"
              step="0.01"
              value={red}
              onChange={(e) => setRed(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
            />
            <p className="text-[11px] text-slate-600">was {pct(current?.red_thr, 2)}</p>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="thr-amber" className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Amber — watch (%)</label>
            <input
              id="thr-amber"
              type="number"
              inputMode="decimal"
              min="0.01"
              max="99.99"
              step="0.01"
              value={amber}
              onChange={(e) => setAmber(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
            />
            <p className="text-[11px] text-slate-600">was {pct(current?.amber_thr, 2)}</p>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="thr-why" className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">
            Justification <span className="font-normal normal-case text-slate-600">(required, stored with the change)</span>
          </label>
          <textarea
            id="thr-why"
            rows={4}
            maxLength={2000}
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            aria-describedby="thr-why-help"
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
          />
          <p id="thr-why-help" className="text-[11px] leading-relaxed text-slate-600">
            Say what changed in the book or in capacity that warrants the new line. This text is shown on the
            history below and in the audit log, permanently.
          </p>
        </div>

        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-rag-ambertx">
          <p className="flex items-start gap-2">
            <TriangleAlert size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span>
              Applying this writes one audited change row. <b>No account is re-scored</b> — bands are recomputed on
              read, so every account’s PD is exactly what the published run produced. The run’s own published bands
              stay visible on the watch-list alongside the new ones.
            </span>
          </p>
        </div>

        {problems.length > 0 && (
          <ul className="space-y-1 text-xs text-rag-redtx" role="status" aria-live="polite">
            {problems.map((p) => <li key={p}>{p}</li>)}
          </ul>
        )}
        {error && <p className="text-xs text-rag-redtx" role="alert">{error.message}</p>}
      </div>
    </Dialog>
  )
}

export default function Thresholds() {
  const { isStatic, roleCode } = useAuth()
  const live = !isStatic
  const [dialog, setDialog] = useState(false)
  const current = useAsync(({ signal }) => loadThreshold({ live, signal }), [live])
  const data = current.data
  const badge = badgeForMode(current.meta?.provenance_mode, current.source)
  const editable = live && (data?.editable_by || ['M', 'A']).includes(roleCode)
  const drifted = useMemo(() => (
    data && data.published_red_thr != null
    && (data.red_thr !== data.published_red_thr || data.amber_thr !== data.published_amber_thr)
  ), [data])

  return (
    <AppShell
      view="threshold"
      title="Risk thresholds"
      subtitle="Where Red and Amber sit, what that trade-off costs, and every change ever made"
      help="threshold"
      source={badge.source}
      sandbox={badge.sandbox}
      sourceDetail={badge.detail}
      actions={editable ? (
        <button
          type="button"
          onClick={() => setDialog(true)}
          className="inline-flex items-center gap-1.5 rounded-lg bg-idbi-green px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-idbi-greendk focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green focus-visible:ring-offset-2"
        >
          <SlidersHorizontal size={14} aria-hidden="true" /> Change thresholds
        </button>
      ) : null}
    >
      {current.error ? (
        <ErrorState title="Could not load the thresholds" error={current.error} onRetry={current.reload} />
      ) : current.loading ? (
        <Loading label="Loading thresholds…" />
      ) : (
        <>
          <section className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-red-200 bg-white p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-rag-redtx">Red — act now</div>
              <div className="mt-1 text-3xl font-extrabold text-rag-redtx">{pct(data.red_thr, 2)}</div>
              {drifted && <p className="mt-1 text-xs text-slate-600">run published {pct(data.published_red_thr, 2)}</p>}
            </div>
            <div className="rounded-xl border border-amber-200 bg-white p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-rag-ambertx">Amber — watch</div>
              <div className="mt-1 text-3xl font-extrabold text-rag-ambertx">{pct(data.amber_thr, 2)}</div>
              {drifted && <p className="mt-1 text-xs text-slate-600">run published {pct(data.published_amber_thr, 2)}</p>}
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-600">In force since</div>
              <div className="mt-1 text-lg font-extrabold text-slate-800">
                {data.changed_at ? new Date(data.changed_at).toLocaleString('en-IN') : 'the model run was published'}
              </div>
              <p className="mt-1 text-xs text-slate-600">
                source: {data.source === 'threshold_change' ? 'a manager’s audited change' : 'the published model run'}
              </p>
            </div>
          </section>

          {data.justification && (
            <p className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm leading-relaxed text-slate-700">
              <b>Why these lines: </b>{data.justification}
            </p>
          )}

          {!editable && (
            <p className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-700">
              {live
                ? <>Thresholds are set by a manager or an administrator. You can see them and the reasoning; changing them is not your role’s to do.</>
                : <>This is the frozen demo bundle. There is no backend to record a threshold change against, so the control is absent rather than fake.</>}
            </p>
          )}

          <CostRationale cost={data.cost_model} />

          <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <div className="flex items-center gap-2 border-b border-slate-200 p-4">
              <History size={16} className="text-idbi-green" aria-hidden="true" />
              <h3 className="font-bold text-slate-800">Change history</h3>
            </div>
            {(data.history || []).length === 0 ? (
              <div className="p-4">
                <Empty
                  icon={History}
                  title="No threshold has ever been changed"
                  hint="The lines in force are the ones the published model run shipped with."
                />
              </div>
            ) : (
              <div className="overflow-x-auto scroll-thin">
                <DataTable caption={`${data.history.length} threshold changes, newest first`}>
                  <thead className="bg-slate-50 text-xs">
                    <tr>
                      <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">When</th>
                      <th scope="col" className="px-3 py-2 text-right font-semibold text-slate-600">Red</th>
                      <th scope="col" className="px-3 py-2 text-right font-semibold text-slate-600">Amber</th>
                      <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Justification</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...data.history].reverse().map((h) => (
                      <tr key={h.id} className="border-t border-slate-100">
                        <th scope="row" className="whitespace-nowrap px-3 py-2 text-left font-normal text-slate-700">
                          {h.at ? new Date(h.at).toLocaleString('en-IN') : '—'}
                        </th>
                        <td className="whitespace-nowrap px-3 py-2 text-right text-slate-700">
                          {pct(h.red_thr_before, 2)} → <b className="text-rag-redtx">{pct(h.red_thr_after, 2)}</b>
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right text-slate-700">
                          {pct(h.amber_thr_before, 2)} → <b className="text-rag-ambertx">{pct(h.amber_thr_after, 2)}</b>
                        </td>
                        <td className="px-3 py-2 text-slate-700">{h.justification || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </DataTable>
              </div>
            )}
            <p className="border-t border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-relaxed text-slate-600">
              The author of each change is in the append-only audit log, which an administrator can read and verify.
              This table shows the change itself; the audit log shows who made it.
            </p>
          </section>

          <ChangeDialog
            open={dialog}
            onClose={() => setDialog(false)}
            current={data}
            onSaved={current.reload}
          />
        </>
      )}
    </AppShell>
  )
}
