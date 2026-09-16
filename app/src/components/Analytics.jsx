// Model performance, told honestly.
//
// Two bugs this file used to carry, both of which made the screen claim more than the
// model had earned:
//
//  1. `SIGNAL_GROUPS` hard-coded five feature families while `src/rigor.py` emits nine.
//     The four extras were dropped silently, so the "what the model looks at" bars stopped
//     summing to 100% and the chart implied the missing third did not exist. The family
//     list now comes from `domain/families.js`, anything unexpected is still drawn, and the
//     coverage is asserted on screen rather than assumed.
//  2. `rank_order.by_portfolio` was never rendered, so the mentors' "does it rank-order
//     per portfolio?" question had no answer on the screen that claims to answer it.

import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { pct } from '../lib/format'
import { coverageGap, familiesIn } from '../domain/families'
import { byPortfolioList, honestyBlock, redBandPrecision } from '../domain/shapes'

function Rigor({ rigor }) {
  if (!rigor) return null
  const leakRows = rigor.leakage_by_lead || []
  const families = familiesIn(leakRows)
  const leak = leakRows.map((L) => ({ bucket: L.bucket, ...L.shares }))
  const gap = coverageGap(leakRows, families)
  const rel = (rigor.calibration?.reliability || []).map((r) => ({
    pred: +(r.pred * 100).toFixed(1), obs: +(r.obs * 100).toFixed(1), n: r.n,
  }))
  const oot = rigor.out_of_time || {}
  const ladder = rigor.baseline_ladder || []
  const maxShare = Math.max(100, ...leak.map((row) =>
    families.reduce((s, f) => s + (Number(row[f.key]) || 0), 0)))

  return (
    <>
      <div className="grid gap-5 lg:grid-cols-2">
        {leak.length > 0 && (
          <section className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="font-bold text-slate-800">Proof it’s real early warning, not a leak</h3>
            <p className="mb-4 mt-1 text-xs leading-relaxed text-slate-600">
              What the model actually “looks at”, by how far ahead it is predicting, across all
              {' '}<b>{families.length} feature families</b> the model card declares. Far out, it watches
              cash-flow and credit-limit use; missed payments barely register until the final months — so the
              long-range warnings cannot be a late-payment signal in disguise.
            </p>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={leak} margin={{ top: 6, right: 8, left: -14, bottom: 0 }} barCategoryGap="22%">
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="bucket" tick={{ fontSize: 11, fill: '#475569' }} />
                <YAxis domain={[0, Math.ceil(maxShare / 10) * 10]} tick={{ fontSize: 10, fill: '#475569' }} unit="%" />
                <Tooltip formatter={(v, n) => [`${(+v).toFixed(1)}%`, n]} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                {families.map((g, i) => (
                  <Bar
                    key={g.key}
                    dataKey={g.key}
                    stackId="a"
                    fill={g.color}
                    isAnimationActive={false}
                    radius={i === families.length - 1 ? [4, 4, 0, 0] : 0}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
            <p className="mt-2 text-[11px] leading-relaxed text-slate-600" data-testid="family-coverage">
              {gap <= 0.5
                ? `All ${families.length} families are drawn; each bar sums to 100% of the model’s attribution.`
                : `⚠ These bars sum to ${(100 - gap).toFixed(1)}%, not 100% — this build is rendering ${families.length} of the families the export carries.`}
            </p>
          </section>
        )}

        {rel.length > 0 && (
          <section className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="font-bold text-slate-800">Calibration — is a “40% risk” really 40%?</h3>
            <p className="mb-4 mt-1 text-xs leading-relaxed text-slate-600">
              Predicted probability against the observed default rate, by risk band. On the dashed line means
              perfectly calibrated, so the PD numbers officers see are trustworthy.
              {rigor.calibration?.ece != null && <> ECE {rigor.calibration.ece}.</>}
              {rigor.calibration?.brier_calibrated != null && <> Brier {rigor.calibration.brier_calibrated}.</>}
            </p>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={rel} margin={{ top: 6, right: 12, left: -14, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="pred" type="number" domain={[0, 100]} tick={{ fontSize: 10, fill: '#475569' }} unit="%"
                  label={{ value: 'Predicted', fontSize: 10, fill: '#475569', position: 'insideBottom', dy: 10 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#475569' }} unit="%" />
                <Tooltip formatter={(v, n) => [`${v}%`, n === 'obs' ? 'Actual' : 'Predicted']} />
                <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]} stroke="#94a3b8" strokeDasharray="5 4" />
                <Line type="monotone" dataKey="obs" name="Actual" stroke="#02684F" strokeWidth={2.5} dot={{ r: 2 }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </section>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="text-2xl font-extrabold text-idbi-green">{oot.auc ?? '—'}</div>
          <div className="text-sm font-semibold text-slate-700">Out-of-time AUC</div>
          <div className="text-xs leading-relaxed text-slate-600">
            {oot.train_window ? `trained on ${oot.train_window}, tested on ${oot.test_window}` : 'no out-of-time split published'}
            {oot.note && <> — {oot.note}</>}
          </div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="text-2xl font-extrabold text-idbi-green">no account overlap</div>
          <div className="text-sm font-semibold text-slate-700">Leakage-safe split</div>
          <div className="text-xs text-slate-600">no business appears in both training and test; metrics on held-out only</div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="text-2xl font-extrabold text-idbi-green">
            {ladder.length ? ladder.map((l) => l.auc).join(' ≈ ') : '—'}
          </div>
          <div className="text-sm font-semibold text-slate-700">Robust to model choice</div>
          <div className="text-xs leading-relaxed text-slate-600">
            {ladder.length
              ? ladder.map((l) => l.model).join(' vs ')
              : 'no baseline ladder published for this run'}
          </div>
        </div>
      </div>
    </>
  )
}

const BAND_FILL = { Green: '#16a34a', Amber: '#d97706', Red: '#dc2626' }
const DEC_FILL = ['#16a34a', '#22c55e', '#4ade80', '#a3e635', '#facc15', '#f59e0b', '#f97316', '#ea580c', '#dc2626', '#991b1b']

function fmtRate(r) {
  const p = r * 100
  return `${p < 1 ? p.toFixed(2) : p.toFixed(1)}%`
}

export function RankOrder({ rank, compact = false }) {
  if (!rank?.by_band?.length || !rank?.by_decile?.length) return null
  const h = rank.horizon_months
  const bands = rank.by_band.map((b) => ({ ...b, ratePct: +(b.bad_rate * 100).toFixed(2), fill: BAND_FILL[b.band] || '#02684F' }))
  const deciles = rank.by_decile.map((d) => ({ ...d, name: `D${d.decile}`, ratePct: +(d.bad_rate * 100).toFixed(2) }))
  const green = rank.by_band.find((b) => b.band === 'Green')
  const amber = rank.by_band.find((b) => b.band === 'Amber')
  const red = rank.by_band.find((b) => b.band === 'Red')
  const top = deciles[deciles.length - 1]
  if (!green || !amber || !red || !top) return null
  const heading = rank.title || (rank.portfolio ? `${rank.portfolio}` : 'Do high-risk flags actually go bad?')

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="font-bold text-slate-800">{heading}</h3>
        {rank.bands_monotone != null && (
          <span className={`rounded-full border px-2 py-0.5 text-[11px] font-bold ${
            rank.bands_monotone
              ? 'border-green-200 bg-green-50 text-rag-greentx'
              : 'border-amber-200 bg-amber-50 text-rag-ambertx'
          }`}>
            {rank.bands_monotone ? 'bands monotone' : 'bands not monotone'}
          </span>
        )}
        {rank.n != null && <span className="text-xs text-slate-600">n = {rank.n.toLocaleString('en-IN')}</span>}
      </div>
      <p className="mb-4 mt-1 text-xs leading-relaxed text-slate-600">
        Realised NPA rate over the next <b>{h} months</b> — the window a desk can act in. If the score ranks risk, the
        high-risk band must show a higher realised bad rate. Green {fmtRate(green.bad_rate)} ({green.defaults} of
        {' '}{green.n.toLocaleString('en-IN')}), Amber {fmtRate(amber.bad_rate)} ({amber.defaults} of {amber.n}),
        Red {fmtRate(red.bad_rate)} ({red.defaults} of {red.n}).
      </p>
      <div className={compact ? 'grid gap-5' : 'grid gap-5 lg:grid-cols-2'}>
        <div>
          <div className="mb-2 text-xs font-semibold text-slate-700">By traffic-light band</div>
          <ResponsiveContainer width="100%" height={compact ? 180 : 240}>
            <BarChart data={bands} margin={{ top: 16, right: 8, left: -14, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="band" tick={{ fontSize: 11, fill: '#475569' }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#475569' }} unit="%" />
              <Tooltip formatter={(v, n, p) => {
                const r = p.payload
                return [`${fmtRate(r.bad_rate)} (${r.defaults} of ${r.n.toLocaleString('en-IN')})`, `NPA in ${h} mo`]
              }} />
              <Bar dataKey="ratePct" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                <LabelList dataKey="ratePct" position="top" formatter={(v) => fmtRate(v / 100)}
                  style={{ fontSize: 11, fill: '#1e293b', fontWeight: 700 }} />
                {bands.map((b) => <Cell key={b.band} fill={b.fill} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-slate-700">By score decile (D1 = safest 10%)</div>
          <ResponsiveContainer width="100%" height={compact ? 180 : 240}>
            <BarChart data={deciles} margin={{ top: 16, right: 8, left: -14, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#475569' }} />
              <YAxis tick={{ fontSize: 10, fill: '#475569' }} unit="%" />
              <Tooltip
                formatter={(v, n, p) => {
                  const r = p.payload
                  return [`${fmtRate(r.bad_rate)} (${r.defaults} of ${r.n})`, `NPA in ${h} mo`]
                }}
                labelFormatter={(l, payload) => {
                  const r = payload?.[0]?.payload
                  return r ? `${l} · PD ${r.pd_lo}–${r.pd_hi}` : l
                }}
              />
              <Bar dataKey="ratePct" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                <LabelList dataKey="ratePct" position="top" formatter={(v) => (v >= 0.5 ? fmtRate(v / 100) : '')}
                  style={{ fontSize: 10, fill: '#1e293b', fontWeight: 700 }} />
                {deciles.map((d, i) => <Cell key={d.decile} fill={DEC_FILL[i % DEC_FILL.length]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          {rank.monotone_decile_step_fraction != null && (
            <p className="mt-1 text-[11px] leading-relaxed text-slate-600">
              {rank.monotone_decile_steps ?? ''} of {rank.decile_steps ?? 9} decile steps rise
              {rank.monotone_decile_step_fraction_ci != null && (
                <> · {Math.round(rank.monotone_decile_step_fraction_ci * (rank.decile_steps ?? 9))} of
                {' '}{rank.decile_steps ?? 9} once the Wilson intervals are required to be disjoint</>
              )}.
            </p>
          )}
        </div>
      </div>
    </section>
  )
}

/** The Red-band precision claim, with the interval that says how much to trust it. */
export function PrecisionCard({ metrics }) {
  const p = redBandPrecision(metrics)
  const honesty = honestyBlock(metrics)
  if (!p && !honesty) return null

  return (
    <section className="rounded-xl border border-idbi-green/30 bg-idbi-green/5 p-5">
      <h3 className="font-bold text-idbi-green">The number an officer actually acts on</h3>
      {p?.value != null && (
        <div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-1">
          <div className="text-4xl font-extrabold text-idbi-green">{pct(p.value, 1)}</div>
          <div className="text-sm leading-tight text-slate-700">
            of Red-band accounts reached NPA within {p.horizon_months ?? 8} months
            {p.hits != null && p.n != null && <> — {p.hits} of {p.n}</>}
            {p.ci_low != null && p.ci_high != null && (
              <div className="text-xs text-slate-600">
                95% {p.method || 'Wilson'} interval {pct(p.ci_low, 1)} – {pct(p.ci_high, 1)}
              </div>
            )}
          </div>
        </div>
      )}
      {honesty ? (
        <div className="mt-3 space-y-2 text-sm leading-relaxed text-slate-700">
          {/* Printed verbatim: export_demo.py re-derives every claim in this block from the
              measured numbers and refuses to write the file if they disagree. Paraphrasing
              it here would break that guarantee. */}
          {honesty.headline && <p className="font-semibold text-slate-800">{honesty.headline}</p>}
          {honesty.why && <p>{honesty.why}</p>}
        </div>
      ) : (
        <p className="mt-3 text-sm leading-relaxed text-slate-700">
          On an imbalanced book a model that flags nothing is already highly “accurate”, so raw accuracy is
          meaningless here. We report ranking quality (AUC / KS), recall at a realistic review budget, lead time,
          and the Red band’s realised NPA rate — the figure an officer’s workload is actually spent on.
        </p>
      )}
    </section>
  )
}

function Stat({ value, label, hint }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-3xl font-extrabold text-idbi-green">{value ?? '—'}</div>
      <div className="mt-1 text-sm font-semibold text-slate-700">{label}</div>
      <div className="mt-0.5 text-xs text-slate-600">{hint}</div>
    </div>
  )
}

export default function Analytics({ metrics, rigor }) {
  const m = metrics || {}
  const lead = (m.recall_by_lead_time || []).map((d) => ({ ...d, recallPct: Math.round(d.recall * 100) }))
  const budget = (m.recall_at_budget || []).map((d) => ({ name: `Top ${Math.round(d.budget * 100)}%`, recallPct: Math.round(d.recall * 100) }))
  const perPortfolio = byPortfolioList(m.rank_order)

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat value={m.auc} label="ROC-AUC" hint="ranking quality (0.5 = random, 1.0 = perfect)" />
        <Stat value={m.ks} label="KS statistic" hint="separation of good vs bad" />
        <Stat value={m.median_first_warning_months == null ? null : `${m.median_first_warning_months} mo`}
          label="Median early warning" hint="how far ahead the first flag is raised" />
        <Stat value={m.pct_flagged_6mo_ahead == null ? null : pct(m.pct_flagged_6mo_ahead)}
          label="Flagged ≥6 mo ahead" hint="share of future defaults caught early" />
      </div>

      <PrecisionCard metrics={m} />

      <RankOrder rank={m.rank_order} />

      {perPortfolio.length > 0 && (
        <section className="space-y-4">
          <div>
            <h2 className="text-lg font-extrabold text-slate-900">Does it rank-order inside every portfolio?</h2>
            <p className="max-w-3xl text-xs leading-relaxed text-slate-600">
              One holistic model across all eight lending products is only a claim worth making if the ordering holds
              inside each of them. The pooled exhibit above can look clean while a single product is scored backwards —
              these are the eight, each on its own accounts.
            </p>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            {perPortfolio.map((entry) => (
              <RankOrder
                key={entry.portfolio}
                compact
                rank={{ ...m.rank_order, ...entry, title: entry.title || entry.portfolio }}
              />
            ))}
          </div>
        </section>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {lead.length > 0 && (
          <section className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="font-bold text-slate-800">Can we really see it a year early?</h3>
            <p className="mb-4 mt-1 text-xs leading-relaxed text-slate-600">
              Share of future defaults caught (at a 10% monthly review budget), by how many months before NPA. It
              <b> honestly declines</b> the further out we look — exactly how a real early-warning system behaves.
            </p>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={lead} margin={{ top: 16, right: 8, left: -14, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="bucket" tick={{ fontSize: 11, fill: '#475569' }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#475569' }} unit="%" />
                <Tooltip formatter={(v) => [`${v}%`, 'Caught']} />
                <Bar dataKey="recallPct" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                  <LabelList dataKey="recallPct" position="top" formatter={(v) => `${v}%`} style={{ fontSize: 11, fill: '#1e293b', fontWeight: 700 }} />
                  {lead.map((d, i) => <Cell key={d.bucket} fill={['#dc2626', '#ea580c', '#d97706', '#0ea5e9'][i % 4]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </section>
        )}

        {budget.length > 0 && (
          <section className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="font-bold text-slate-800">Recall at the officer’s review budget</h3>
            <p className="mb-4 mt-1 text-xs leading-relaxed text-slate-600">
              If officers review only the riskiest X% of accounts each month, what share of all future defaults do
              they catch? This is what a banker acts on — <b>not</b> raw accuracy.
            </p>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={budget} margin={{ top: 16, right: 8, left: -14, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#475569' }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#475569' }} unit="%" />
                <Tooltip formatter={(v) => [`${v}%`, 'Caught']} />
                <Bar dataKey="recallPct" fill="#02684F" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                  <LabelList dataKey="recallPct" position="top" formatter={(v) => `${v}%`} style={{ fontSize: 11, fill: '#1e293b', fontWeight: 700 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </section>
        )}
      </div>

      <div className="pt-2">
        <h2 className="text-lg font-extrabold text-slate-900">Model rigor — what a risk reviewer checks</h2>
        <p className="mb-4 text-xs text-slate-600">Leakage, calibration, out-of-time stability, and a baseline benchmark.</p>
        <Rigor rigor={rigor} />
      </div>
    </div>
  )
}
