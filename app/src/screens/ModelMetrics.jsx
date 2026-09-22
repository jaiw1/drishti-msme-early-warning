// Model & Metrics — the published run's own numbers, plus the pre-registered validation.
//
// `GET /drishti/validation` returns whatever `make validate` attached to the published run.
// The table below prints it as it is: pass, fail, **and pending**. A criterion that has not
// been run yet is shown as pending rather than quietly dropped or counted as a pass — the
// pending rows are the disclosure, and hiding them would be the dishonest move.

import { CircleCheck, CircleSlash, Clock, FileText, ShieldAlert, TriangleAlert } from 'lucide-react'
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
  // `report` is a verdict, not an absence: the criterion ran and its number is published
  // with no pre-registered band to gate it. Rendering it as "Skipped" contradicted the
  // criterion's own note ("REPORTED, NOT GATED") in the very next column.
  report: { label: 'Report only', icon: FileText, className: 'text-slate-700', row: '' },
  skipped: { label: 'Skipped', icon: CircleSlash, className: 'text-slate-600', row: '' },
}

const statusOf = (raw) => {
  const key = String(raw ?? '').toLowerCase()
  if (key in STATUS) return key
  if (key === 'passed' || key === 'ok' || key === 'true') return 'pass'
  if (key === 'failed' || key === 'false') return 'fail'
  if (key === 'not_run' || key === 'todo' || key === '' || key === 'null' || key === 'undefined') return 'pending'
  if (key === 'report' || key === 'reported' || key === 'report_only') return 'report'
  return 'skipped'
}

// Fixed decimal places for the Observed and Required columns. `Number(v.toFixed(4))`
// stripped trailing zeros per value, so one row printed 0.8885 and the next 0.82 in the
// same column — a precision that changed row to row and made the table read as if the
// criteria were measured to different accuracies.
const COLUMN_DP = 3

/**
 * One number at the column's fixed precision.
 *
 * Integers are left alone: a criterion whose band is a count of 5 must not read "5.000".
 * A non-zero value smaller than the column's resolution is the other exception — rounding
 * -0.000068 to "-0.000" would print a criterion that passed `< 0` as a tie — so it falls
 * back to three significant figures rather than to a false zero.
 */
function fixedNumber(value) {
  if (!Number.isFinite(value)) return String(value)
  if (Number.isInteger(value)) return String(value)
  const fixed = value.toFixed(COLUMN_DP)
  return Number(fixed) === 0 ? String(Number(value.toPrecision(3))) : fixed
}

/** Three significant figures — the precision the report publishes its own cells at. */
const sig3 = (value) => String(Number(value.toPrecision(3)))

// What a breakdown's cells are, per the criterion's own `scope`, so the summary names the
// thing that was measured rather than saying "cells" about eight lending portfolios.
const SCOPE_NOUN = {
  per_portfolio: 'portfolios',
  per_segment: 'segments',
  per_sector: 'sectors',
  per_cut: 'cells',
}

// The verb a non-numeric criterion is summarised with. `monotone_increasing` cells carry a
// [green, amber, red] triple, not one number, so there is no min or max to take.
const OP_WORD = { monotone_increasing: 'monotone', monotone_decreasing: 'monotone', exists: 'present' }

/**
 * A per-cell criterion's observed value, summarised.
 *
 * DR-06, DR-09 and DR-11 carry `result.value: null` and put every measurement in
 * `result.breakdown[]`, so the Observed column printed an em dash beside a Pass — the one
 * shape where the table had a verdict and showed no number at all. The summary is the
 * cell the criterion is actually gated on: the MINIMUM for a floor (`ge`), the MAXIMUM for
 * a ceiling (`le`), and a pass count when the cells are not single numbers.
 */
export function summariseBreakdown(result, { op, scope } = {}) {
  const cells = Array.isArray(result?.breakdown) ? result.breakdown : []
  if (cells.length === 0) return null
  const noun = SCOPE_NOUN[String(scope || '').toLowerCase()] || 'cells'
  const key = String(op || '').toLowerCase()
  const numbers = cells.map((c) => c?.value).filter((v) => typeof v === 'number' && Number.isFinite(v))
  if (numbers.length === cells.length) {
    if (key === 'ge' || key === 'gte') return `min ${sig3(Math.min(...numbers))} across ${cells.length} ${noun}`
    if (key === 'le' || key === 'lte') return `max ${sig3(Math.max(...numbers))} across ${cells.length} ${noun}`
  }
  const passed = cells.filter((c) => String(c?.status || '').toLowerCase() === 'pass').length
  return `${OP_WORD[key] || 'pass'} in ${passed}/${cells.length} ${noun}`
}

/**
 * One criterion's observed value, printed the way a reviewer reads it.
 *
 * The harness nests the measurement under `result.value`; a bare `[0.82, 0.92]` band
 * rendered through `String()` came out as `0.82,0.92`, and an object-valued criterion
 * (several are) came out as `[object Object]`.
 */
export function formatObserved(value) {
  if (value === null || value === undefined) return null
  if (Array.isArray(value)) return value.map((v) => formatObserved(v)).join(' – ')
  if (typeof value === 'number') return fixedNumber(value)
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'object') {
    return Object.entries(value).map(([k, v]) => `${k.replace(/_/g, ' ')} ${formatObserved(v)}`).join(' · ')
  }
  return String(value)
}

// The three criteria whose figure a reader will otherwise read against the headline on the
// same screen. They measure the same metrics the run publishes, over a DIFFERENT
// population: the validation runner's labelable mature subset (every eligible holdout
// row), not the banded book the run published. Saying so is cheaper than letting a jury
// find two numbers for "the AUC" and conclude one of them is wrong.
const POPULATION_ROWS = new Set(['DR-01', 'DR-02', 'DR-26'])
const POPULATION_NOTE = 'Different population from the headline above: this is the validation runner’s labelable mature subset, not the run’s published book.'

/** The runner's own wording, first sentence only — some details run to a paragraph. */
export function firstSentence(text, max = 200) {
  const raw = String(text || '').trim()
  if (!raw) return ''
  // Not a lookbehind: Safari only learned those in 16.4, and a regex the parser rejects
  // takes the whole bundle down rather than one table cell.
  const stop = raw.indexOf('. ')
  const cut = stop === -1 ? raw : raw.slice(0, stop + 1)
  return cut.length > max ? `${cut.slice(0, max - 1).trimEnd()}…` : cut
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
    // `entry.result` is an OBJECT in the shape the harness publishes, and feeding an object
    // to `statusOf` stringified it to "[object object]" and fell through to "skipped" — so
    // every reported-not-gated criterion the platform serves read "Skipped" beside its own
    // note saying "REPORTED, NOT GATED".
    const nested = entry.result && typeof entry.result === 'object' ? entry.result.status : entry.result
    const fallback = statusOf(entry.status ?? nested ?? entry.outcome ?? entry.passed)
    const state = states?.[id]
    const status = state === 'accepted_failure' ? 'accepted'
      : state === 'blocking_failure' ? 'fail'
        : state === 'pass' ? 'pass'
          : state === 'report' ? 'report'
            : fallback
    const observed = entry.observed ?? entry.value ?? entry.actual ?? entry.result?.value ?? null
    return {
      id,
      description: entry.description || entry.title || entry.metric || '',
      status,
      observed,
      // Only when there is no top-level measurement at all: a criterion that publishes
      // both a value and a breakdown keeps printing its value, exactly as before.
      observedSummary: observed === null ? summariseBreakdown(entry.result, entry) : null,
      detail: entry.result?.detail || entry.detail || '',
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
  // `accepted_failures.accepted` is the whole `--accept-known-failures` list, and the
  // platform records ONE list for both products — so DRISHTi's banner was counting
  // SANKET's accepted failures too (6, beside a tally that said 4). Count only the ids
  // this report actually carries.
  const idsInReport = new Set(rows.map((r) => r.id))
  const acceptedHere = (data.accepted_failures?.accepted || []).filter((id) => idsInReport.has(id))

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
          {['pass', 'fail', 'accepted', 'pending', 'report', 'skipped'].map((key) => counts[key] ? (
            <li key={key} className={`rounded-full border border-slate-200 px-2.5 py-1 ${STATUS[key].className}`}>
              {counts[key]} {STATUS[key].label.toLowerCase()}
            </li>
          ) : null)}
        </ul>
      </div>

      {data.accepted_failures && acceptedHere.length > 0 && (
        <div className="border-b border-rose-200 bg-rose-50/70 px-4 py-3 text-xs leading-relaxed text-slate-700">
          <p>
            <b>
              {acceptedHere.length === 1
                ? '1 criterion failed and was accepted in advance'
                : `${acceptedHere.length} criteria failed and were accepted in advance`}
              {' '}({acceptedHere.join(', ')})
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
        <div className="max-h-[420px] overflow-auto scroll-thin" tabIndex={0} role="region" aria-label="Pre-registered validation criteria, scrollable">
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
                    <td className="px-3 py-2 text-slate-700">
                      {r.description || '—'}
                      {POPULATION_ROWS.has(r.id) && (
                        <span className="mt-0.5 block text-[11px] leading-relaxed text-slate-600">
                          {POPULATION_NOTE}
                          {r.detail && <> Runner: {firstSentence(r.detail)}</>}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right font-semibold text-slate-800">
                      {formatObserved(r.observed) ?? r.observedSummary ?? '—'}
                    </td>
                    <td className="px-3 py-2 text-right text-slate-600">{formatObserved(r.expected) ?? '—'}</td>
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
          Run verification: <b>{String(
            data.verify_result.status
            ?? data.verify_result.ok
            ?? (data.verify_result.passed === true ? 'passed'
              : data.verify_result.passed === false ? 'failed' : 'recorded'),
          )}</b>
          {data.verify_result.reason && <> — {data.verify_result.reason}</>}
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
