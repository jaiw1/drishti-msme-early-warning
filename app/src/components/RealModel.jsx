import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LabelList,
  LineChart, Line, ReferenceLine,
} from 'recharts'
import { BadgeCheck, Building2, TriangleAlert, CircleCheck } from 'lucide-react'
import DataTable from './DataTable'

function Stat({ value, label, hint, tint = 'text-idbi-green' }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className={`text-3xl font-extrabold ${tint}`}>{value}</div>
      <div className="text-sm font-semibold text-slate-700 mt-1">{label}</div>
      <div className="text-xs text-slate-500">{hint}</div>
    </div>
  )
}

export default function RealModel({ data, syntheticAuc }) {
  if (!data) return <div className="text-slate-500 text-sm">Loading real-data validation…</div>
  const m = data.metrics, meta = data.meta
  const feats = data.top_features.slice(0, 8).map((f) => ({ name: f.feature, v: f.importance }))
  const rel = (data.reliability || []).map((r) => ({ pred: Math.round(r.pred * 100), obs: Math.round(r.obs * 100) }))

  return (
    <div className="space-y-5">
      {/* hero: the honesty centerpiece */}
      <section className="bg-idbi-green/5 border border-idbi-green/30 rounded-xl p-5">
        <div className="flex items-center gap-2 text-idbi-green mb-2">
          <BadgeCheck size={20} /><h3 className="font-extrabold text-lg">Validated on REAL Indian MSME data</h3>
        </div>
        <p className="text-sm text-slate-600 leading-relaxed max-w-4xl">
          The cockpit runs on synthetic data (its ~{Math.round((syntheticAuc || 0.95) * 100) / 100} score is illustrative, not a real-world claim).
          To prove the <b>method</b> holds up, we ran the <b>same modelling approach on {meta.n_companies.toLocaleString('en-IN')} real Indian
          MSMEs</b> ({meta.n_company_years.toLocaleString('en-IN')} company-years, FY2018–FY2026) with <b>{meta.n_defaults.toLocaleString('en-IN')} real
          defaults</b> — where "default" is an actual credit-rating downgrade to 'D'. On real data it scores an honest
          <b> {m.auc}</b> — squarely in the realistic band. So the numbers you can trust are these, and the method behind the cockpit is sound.
        </p>
        <p className="text-xs text-slate-500 mt-2">Source: {meta.source}. Predicts default within {meta.horizon_years} years from annual financials; no company appears in both training and test.</p>
      </section>

      {/* headline stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat value={m.auc} label="Real-data ROC-AUC"
              hint={m.auc_ci ? `95% CI ${m.auc_ci[0]}–${m.auc_ci[1]} · honest band ~0.75–0.85` : 'honest band ~0.75–0.85 — no synthetic inflation'} />
        <Stat value={`${m.auc} vs ${m.logistic_auc}`} label="LightGBM vs logistic" hint="on real data, the model earns its keep" />
        <Stat value={meta.n_companies.toLocaleString('en-IN')} label="Real companies" hint={`${meta.n_defaults.toLocaleString('en-IN')} real defaults · ${(meta.default_rate * 100).toFixed(1)}% of ${meta.n_company_years.toLocaleString('en-IN')} company-years`} />
        <Stat value={m.brier} label="Brier score" hint="well-calibrated probabilities" tint="text-slate-900" />
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        {/* what drives real default */}
        <section className="bg-white rounded-xl border border-slate-200 p-5">
          <h3 className="font-bold text-slate-800">What predicts real default</h3>
          <p className="text-xs text-slate-500 mt-1 mb-4">Most important financial signals the model learned from real Indian MSMEs.</p>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={feats} layout="vertical" margin={{ top: 4, right: 30, left: 40, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f6" horizontal={false} />
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: '#475569' }} width={120} />
              <Tooltip formatter={(v) => [v, 'importance']} />
              <Bar dataKey="v" fill="#02684F" radius={[0, 5, 5, 0]} isAnimationActive={false}>
                <LabelList dataKey="v" position="right" style={{ fontSize: 10, fill: '#94a3b8' }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </section>

        {/* calibration */}
        <section className="bg-white rounded-xl border border-slate-200 p-5">
          <h3 className="font-bold text-slate-800">Calibration on real data</h3>
          <p className="text-xs text-slate-500 mt-1 mb-4">Predicted vs actual default rate by risk band — on the dashed line = trustworthy probabilities.</p>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={rel} margin={{ top: 6, right: 12, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f6" />
              <XAxis dataKey="pred" type="number" domain={[0, 100]} tick={{ fontSize: 10, fill: '#94a3b8' }} unit="%" />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#94a3b8' }} unit="%" />
              <Tooltip formatter={(v, n) => [`${v}%`, n === 'obs' ? 'Actual' : 'Predicted']} />
              <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]} stroke="#cbd5e1" strokeDasharray="5 4" />
              <Line type="monotone" dataKey="obs" stroke="#02684F" strokeWidth={2.5} dot={{ r: 2 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </section>
      </div>

      {/* real example companies */}
      <section className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="p-4 border-b border-slate-100 flex items-center gap-2">
          <Building2 size={16} className="text-idbi-green" />
          <h3 className="font-bold text-slate-800">Real companies the model scored</h3>
          <span className="text-xs text-slate-500">(anonymised — real financials &amp; outcomes)</span>
        </div>
        <div className="overflow-x-auto">
          <DataTable caption="Real companies the model scored, with their financials and their actual outcome">
            <thead className="bg-slate-50 text-xs text-slate-600">
              <tr>
                <th scope="col" className="text-left px-4 py-2 font-semibold">Company</th>
                <th scope="col" className="text-left px-4 py-2 font-semibold">Industry</th>
                <th scope="col" className="text-right px-4 py-2 font-semibold">Int. cover</th>
                <th scope="col" className="text-right px-4 py-2 font-semibold">D/E</th>
                <th scope="col" className="text-right px-4 py-2 font-semibold">Margin</th>
                <th scope="col" className="text-right px-4 py-2 font-semibold">Risk</th>
                <th scope="col" className="text-left px-4 py-2 font-semibold">Outcome</th>
                <th scope="col" className="text-left px-4 py-2 font-semibold">Top reason</th>
              </tr>
            </thead>
            <tbody>
              {data.examples.map((e) => {
                const bad = e.outcome.startsWith('Default')
                return (
                  <tr key={e.id} className="border-t border-slate-50">
                    <th scope="row" className="px-4 py-2.5 text-left font-semibold text-slate-800">{e.id}<span className="text-slate-600 font-normal"> · {e.obs_year}</span></th>
                    <td className="px-4 py-2.5 text-slate-500">{e.industry}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{e.interest_cover ?? '—'}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{e.debt_to_equity ?? '—'}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{e.pat_margin != null ? `${e.pat_margin}%` : '—'}</td>
                    <td className={`px-4 py-2.5 text-right font-bold ${e.pd >= 0.5 ? 'text-rag-redtx' : e.pd >= 0.15 ? 'text-rag-ambertx' : 'text-rag-greentx'}`}>{Math.round(e.pd * 100)}%</td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full ${bad ? 'bg-red-50 text-rag-redtx' : 'bg-green-50 text-rag-greentx'}`}>
                        {bad ? <TriangleAlert size={12} /> : <CircleCheck size={12} />}{e.outcome}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-slate-500 max-w-[260px] truncate">{e.reasons?.[0] || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </DataTable>
        </div>
      </section>

      <section className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-xs text-slate-500 leading-relaxed">
        <b className="text-slate-700">Honest caveats:</b> the rated-MSME universe skews toward firms seeking bank facilities (selection bias),
        so this is "which <i>rated</i> MSMEs default." It uses <b>annual</b> financials, so it <b>complements</b> — not replaces — the
        monthly behavioural early-warning in the cockpit. "Default" = an actual 'D' credit-rating event. A real deployment would add
        bureau/GST/transaction signals on top.
      </section>
    </div>
  )
}
