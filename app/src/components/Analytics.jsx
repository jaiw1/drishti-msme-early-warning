import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LabelList,
  Legend, LineChart, Line, ReferenceLine,
} from 'recharts'
import { pct } from '../lib/format'

const SIGNAL_GROUPS = [
  { key: 'Days-past-due / repayment', color: '#dc2626' },
  { key: 'Cash-flow (inflows / GST)', color: '#0ea5e9' },
  { key: 'Credit-limit utilisation', color: '#FF4D01' },
  { key: 'Adverse filings', color: '#a855f7' },
  { key: 'Borrower profile', color: '#94a3b8' },
]

function Rigor({ rigor }) {
  if (!rigor?.leakage_by_lead) return null
  const leak = rigor.leakage_by_lead.map((L) => ({ bucket: L.bucket, ...L.shares }))
  const rel = (rigor.calibration?.reliability || []).map((r) => ({ pred: Math.round(r.pred * 100), obs: Math.round(r.obs * 100) }))
  const oot = rigor.out_of_time || {}
  const ladder = rigor.baseline_ladder || []

  return (
    <>
      <div className="grid lg:grid-cols-2 gap-5">
        <section className="bg-white rounded-xl border border-slate-200 p-5">
          <h3 className="font-bold text-slate-800">Proof it's real early warning, not a leak</h3>
          <p className="text-xs text-slate-400 mt-1 mb-4">
            What the model actually "looks at", by how far ahead it's predicting. Far out (10–12 mo) it watches
            <b> cash-flow &amp; credit-limit use</b> — missed payments (red) barely register until the final months.
            So the long-range warnings can't be a late-payment signal in disguise.
          </p>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={leak} margin={{ top: 6, right: 8, left: -20, bottom: 0 }} barCategoryGap="22%">
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f6" />
              <XAxis dataKey="bucket" tick={{ fontSize: 11, fill: '#64748b' }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#94a3b8' }} unit="%" />
              <Tooltip formatter={(v, n) => [`${v}%`, n]} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              {SIGNAL_GROUPS.map((g) => (
                <Bar key={g.key} dataKey={g.key} stackId="a" fill={g.color} isAnimationActive={false}
                     radius={g.key === 'Borrower profile' ? [4, 4, 0, 0] : 0} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </section>

        <section className="bg-white rounded-xl border border-slate-200 p-5">
          <h3 className="font-bold text-slate-800">Calibration — is a "40% risk" really 40%?</h3>
          <p className="text-xs text-slate-400 mt-1 mb-4">
            Predicted probability vs actual observed default rate, by risk band. On the dashed line = perfectly
            calibrated, so the PD numbers officers see are trustworthy. (Brier {rigor.calibration?.brier_calibrated})
          </p>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={rel} margin={{ top: 6, right: 12, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f6" />
              <XAxis dataKey="pred" type="number" domain={[0, 100]} tick={{ fontSize: 10, fill: '#94a3b8' }} unit="%"
                     label={{ value: 'Predicted', fontSize: 10, fill: '#94a3b8', position: 'insideBottom', dy: 10 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#94a3b8' }} unit="%" />
              <Tooltip formatter={(v, n) => [`${v}%`, n === 'obs' ? 'Actual' : 'Predicted']} />
              <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]} stroke="#cbd5e1" strokeDasharray="5 4" />
              <Line type="monotone" dataKey="obs" stroke="#02684F" strokeWidth={2.5} dot={{ r: 2 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </section>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-2xl font-extrabold text-idbi-green">{oot.auc}</div>
          <div className="text-sm font-semibold text-slate-700">Out-of-time AUC</div>
          <div className="text-xs text-slate-400">trained on {oot.train_window}, tested on {oot.test_window} — holds up over time</div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-2xl font-extrabold text-idbi-green">no account overlap</div>
          <div className="text-sm font-semibold text-slate-700">Leakage-safe split</div>
          <div className="text-xs text-slate-400">no business appears in both training &amp; test; metrics on held-out only</div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-2xl font-extrabold text-idbi-green">
            {ladder.map((l) => l.auc).join(' ≈ ')}
          </div>
          <div className="text-sm font-semibold text-slate-700">Robust to model choice</div>
          <div className="text-xs text-slate-400">a transparent logistic scorecard ≈ LightGBM — the signal is genuine, not a black-box artefact</div>
        </div>
      </div>
    </>
  )
}

function ThresholdExhibit({ data }) {
  const rows = data.portfolio
  const redThr = data.portfolio_summary.red_thr * 100
  const amberThr = data.portfolio_summary.amber_thr * 100
  // accounts in this snapshot that really do default within the next 12 months (demo outcome reveal)
  const coming = rows.filter((r) => r.ground_truth_default === 1 && r.snap_months_to_npa >= 1 && r.snap_months_to_npa <= 12)
  const point = (t) => ({
    thr: t,
    workload: +((100 * rows.filter((r) => r.pd * 100 >= t).length) / rows.length).toFixed(1),
    caught: +((100 * coming.filter((r) => r.pd * 100 >= t).length) / Math.max(1, coming.length)).toFixed(1),
  })
  const curve = [0.5, 1, 1.5, 2, 3, 4, 6, 8, 12, 16, 22, 30, 40, 55, 70, 85].map(point)
  const amber = point(amberThr)
  const red = point(redThr)

  return (
    <section className="bg-white rounded-xl border border-slate-200 p-5">
      <h3 className="font-bold text-slate-800">Where the Red / Amber lines sit — and why</h3>
      <p className="text-xs text-slate-400 mt-1 mb-4">
        Any cut-off trades <b>officer workload</b> against <b>catch-rate</b>, shown here on this book's actual
        next-12-month outcomes. The Amber "watch" line ({amberThr}%) puts <b>{amber.workload}%</b> of the book under
        watch and catches <b>{amber.caught}%</b> of the defaults coming in the next 12 months; the Red "act-now"
        line ({redThr}%) concentrates urgent action on just <b>{red.workload}%</b> of accounts. The lines are sized
        to a realistic review capacity — not picked to flatter the metrics.
      </p>
      <ResponsiveContainer width="100%" height={250}>
        <LineChart data={curve} margin={{ top: 14, right: 12, left: -20, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eef2f6" />
          <XAxis dataKey="thr" type="number" scale="log" domain={[0.5, 85]} ticks={[1, 2, 4, 10, 20, 40, 80]}
                 tick={{ fontSize: 10, fill: '#94a3b8' }} unit="%" />
          <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#94a3b8' }} unit="%" />
          <Tooltip formatter={(v, n) => [`${v}%`, n]} labelFormatter={(l) => `cut-off ${l}%`} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <ReferenceLine x={amberThr} stroke="#d97706" strokeDasharray="4 4"
                         label={{ value: 'Amber', fontSize: 9, fill: '#d97706', position: 'top' }} />
          <ReferenceLine x={redThr} stroke="#dc2626" strokeDasharray="4 4"
                         label={{ value: 'Red', fontSize: 9, fill: '#dc2626', position: 'top' }} />
          <Line type="monotone" dataKey="caught" name="Coming defaults caught" stroke="#02684F" strokeWidth={2.5} dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="workload" name="Book flagged (workload)" stroke="#FF4D01" strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </section>
  )
}

function Stat({ value, label, hint }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
      <div className="text-3xl font-extrabold text-idbi-green">{value}</div>
      <div className="text-sm font-semibold text-slate-700 mt-1">{label}</div>
      <div className="text-xs text-slate-400 mt-0.5">{hint}</div>
    </div>
  )
}

export default function Analytics({ data }) {
  const m = data.metrics
  const lead = m.recall_by_lead_time.map((d) => ({ ...d, recallPct: Math.round(d.recall * 100) }))
  const budget = m.recall_at_budget.map((d) => ({ name: `Top ${Math.round(d.budget * 100)}%`, recallPct: Math.round(d.recall * 100) }))

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat value={m.auc} label="ROC-AUC" hint="ranking quality (0.5 = random, 1.0 = perfect)" />
        <Stat value={m.ks} label="KS statistic" hint="separation of good vs bad" />
        <Stat value={`${m.median_first_warning_months} mo`} label="Median early warning" hint="how far ahead we raise the first flag" />
        <Stat value={pct(m.pct_flagged_6mo_ahead)} label="Flagged ≥6 mo ahead" hint="share of future defaults caught early" />
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <section className="bg-white rounded-xl border border-slate-200 p-5">
          <h3 className="font-bold text-slate-800">Can we really see it a year early?</h3>
          <p className="text-xs text-slate-400 mt-1 mb-4">
            Share of future defaults we catch (at a 10% monthly review budget), by how many months before NPA.
            It <b>honestly declines</b> the further out we look — exactly how a real early-warning system behaves.
          </p>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={lead} margin={{ top: 16, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f6" />
              <XAxis dataKey="bucket" tick={{ fontSize: 11, fill: '#64748b' }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#94a3b8' }} unit="%" />
              <Tooltip formatter={(v) => [`${v}%`, 'Caught']} />
              <Bar dataKey="recallPct" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                <LabelList dataKey="recallPct" position="top" formatter={(v) => `${v}%`} style={{ fontSize: 11, fill: '#334155', fontWeight: 700 }} />
                {lead.map((d, i) => (
                  <Cell key={i} fill={['#dc2626', '#ea580c', '#d97706', '#0ea5e9'][i]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </section>

        <section className="bg-white rounded-xl border border-slate-200 p-5">
          <h3 className="font-bold text-slate-800">Recall at the officer's review budget</h3>
          <p className="text-xs text-slate-400 mt-1 mb-4">
            If officers review only the riskiest X% of accounts each month, what share of all future
            defaults do they catch? This is what a banker acts on — <b>not</b> raw accuracy.
          </p>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={budget} margin={{ top: 16, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f6" />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748b' }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#94a3b8' }} unit="%" />
              <Tooltip formatter={(v) => [`${v}%`, 'Caught']} />
              <Bar dataKey="recallPct" fill="#02684F" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                <LabelList dataKey="recallPct" position="top" formatter={(v) => `${v}%`} style={{ fontSize: 11, fill: '#334155', fontWeight: 700 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </section>
      </div>

      <ThresholdExhibit data={data} />

      <section className="bg-idbi-green/5 border border-idbi-green/20 rounded-xl p-5">
        <h3 className="font-bold text-idbi-green">Why we don't quote "90% accuracy"</h3>
        <p className="text-sm text-slate-600 mt-2 leading-relaxed">
          On an imbalanced book (~8% default), a model that flags <i>nothing</i> is already ~92% "accurate" — so raw
          accuracy is meaningless and misleading. We report <b>ROC-AUC / KS</b> (ranking quality), <b>recall at a
          realistic review budget</b> (what officers actually work), and <b>lead time</b> (how early we catch it).
          The model is trained and validated <b>out-of-sample</b> (no account appears in both training and test),
          and metrics are computed on the held-out set only.
        </p>
      </section>

      <div className="pt-2">
        <h2 className="text-lg font-extrabold text-slate-900">Model rigor — what a risk reviewer checks</h2>
        <p className="text-xs text-slate-400 mb-4">Leakage, calibration, out-of-time stability, and a baseline benchmark.</p>
        <Rigor rigor={data.rigor} />
      </div>
    </div>
  )
}
