import { useState, useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, LabelList,
} from 'recharts'
import { inr } from '../lib/format'
import { TriangleAlert, Layers, IndianRupee, ShieldCheck } from 'lucide-react'

const IDBI_MSME_BOOK_CR = 30000   // ~₹30,000 cr — IDBI's real MSME/priority book (frame the sample against it)

function groupBy(rows, key) {
  const m = {}
  for (const r of rows) {
    const g = (m[r[key]] ||= { name: r[key], total: 0, red: 0, amber: 0, green: 0, flagged: 0, count: 0 })
    g.total += r.sanctioned; g.count++
    g[r.bucket] += r.sanctioned
    if (r.bucket !== 'green') g.flagged++
  }
  return Object.values(m)
    .map((g) => ({ ...g, redCr: g.red / 1e7, amberCr: g.amber / 1e7, pctFlagged: (g.red + g.amber) / g.total }))
    .sort((a, b) => (b.red + b.amber) - (a.red + a.amber))
}

function Slider({ label, value, set, min, max, step, fmt }) {
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-slate-600">{label}</span>
        <span className="font-bold text-idbi-green">{fmt(value)}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => set(+e.target.value)}
        className="w-full accent-idbi-green cursor-pointer" />
    </div>
  )
}

export default function PortfolioRisk({ data }) {
  const [cure, setCure] = useState(0.4)
  const [prov, setProv] = useState(0.15)
  const port = data.portfolio

  const bySector = useMemo(() => groupBy(port, 'sector'), [port])
  const bySegment = useMemo(() => groupBy(port, 'segment'), [port])

  const econ = useMemo(() => {
    const flagged = port.filter((r) => r.bucket !== 'green')
    const expNpa = flagged.reduce((s, r) => s + r.pd * r.sanctioned, 0)   // expected ₹ that turns NPA
    const sampleCr = port.reduce((s, r) => s + r.sanctioned, 0) / 1e7
    const scale = IDBI_MSME_BOOK_CR / sampleCr
    const provAtRisk = expNpa * prov
    const provSaved = provAtRisk * cure
    const exposureProtected = expNpa * cure
    return { expNpa, sampleCr, scale, provSaved, exposureProtected, flaggedCount: flagged.length }
  }, [port, cure, prov])

  const topSector = bySector[0]

  return (
    <div className="space-y-5">
      {/* headline impact cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-2 text-rag-red mb-1"><TriangleAlert size={16} /><span className="text-xs font-semibold uppercase tracking-wide">Flagged exposure</span></div>
          <div className="text-2xl font-extrabold text-slate-900">{inr(data.portfolio_summary.exposure_at_risk)}</div>
          <div className="text-xs text-slate-400">{econ.flaggedCount} watch-list accounts (red + amber)</div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-2 text-idbi-orange mb-1"><Layers size={16} /><span className="text-xs font-semibold uppercase tracking-wide">Most-stressed sector</span></div>
          <div className="text-2xl font-extrabold text-slate-900">{topSector?.name}</div>
          <div className="text-xs text-slate-400">{inr((topSector?.red + topSector?.amber) || 0)} flagged ({Math.round((topSector?.pctFlagged || 0) * 100)}% of its book)</div>
        </div>
        <div className="bg-white rounded-xl border border-idbi-green/30 p-4 bg-idbi-green/5">
          <div className="flex items-center gap-2 text-idbi-green mb-1"><ShieldCheck size={16} /><span className="text-xs font-semibold uppercase tracking-wide">Provisioning saved / yr</span></div>
          <div className="text-2xl font-extrabold text-idbi-green">{inr(econ.provSaved * econ.scale)}</div>
          <div className="text-xs text-slate-400">scaled to IDBI's ~₹{IDBI_MSME_BOOK_CR.toLocaleString('en-IN')} cr MSME book</div>
        </div>
      </div>

      {/* concentration */}
      <div className="grid lg:grid-cols-2 gap-5">
        <section className="bg-white rounded-xl border border-slate-200 p-5">
          <h3 className="font-bold text-slate-800">Where is the risk concentrated? (by sector)</h3>
          <p className="text-xs text-slate-400 mt-1 mb-4">Flagged exposure (₹ cr) per sector — a fast read on which pockets of the book are stressed.</p>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={bySector} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f6" />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748b' }} />
              <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} unit=" cr" />
              <Tooltip formatter={(v, n) => [`₹${(+v).toFixed(2)} cr`, n === 'redCr' ? 'Red' : 'Amber']} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar dataKey="amberCr" name="Amber" stackId="a" fill="#d97706" isAnimationActive={false} />
              <Bar dataKey="redCr" name="Red" stackId="a" fill="#dc2626" radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </section>

        <section className="bg-white rounded-xl border border-slate-200 p-5">
          <h3 className="font-bold text-slate-800">Risk by segment</h3>
          <p className="text-xs text-slate-400 mt-1 mb-4">Share of each segment's book that is flagged — is the stress in Micro, Small or Medium?</p>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={bySegment} margin={{ top: 18, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f6" />
              <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#64748b' }} />
              <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
              <Tooltip formatter={(v) => [`${(v * 100).toFixed(1)}%`, 'flagged']} />
              <Bar dataKey="pctFlagged" fill="#02684F" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                <LabelList dataKey="pctFlagged" position="top" formatter={(v) => `${(v * 100).toFixed(1)}%`}
                           style={{ fontSize: 11, fill: '#334155', fontWeight: 700 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </section>
      </div>

      {/* what-if */}
      <section className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-center gap-2 mb-1">
          <IndianRupee size={18} className="text-idbi-green" />
          <h3 className="font-bold text-slate-800">What early action is worth — provisioning what-if</h3>
        </div>
        <p className="text-xs text-slate-400 mb-5 max-w-3xl">
          When a loan slips to NPA the bank must set aside provisions (RBI IRAC). If officers act on DRISHTi's early
          flags and rescue a share of them, that provisioning is avoided. Move the sliders to see the impact.
        </p>
        <div className="grid md:grid-cols-2 gap-8">
          <div className="space-y-5">
            <Slider label="Accounts cured by acting early" value={cure} set={setCure} min={0.1} max={0.7} step={0.05} fmt={(v) => `${Math.round(v * 100)}%`} />
            <Slider label="Provisioning rate on NPA (IRAC)" value={prov} set={setProv} min={0.1} max={0.4} step={0.05} fmt={(v) => `${Math.round(v * 100)}%`} />
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Illustrative. Expected NPA = Σ (model PD × exposure) over flagged accounts; provisioning saved = that × rate × cure-rate,
              then scaled from the ₹{Math.round(econ.sampleCr).toLocaleString('en-IN')} cr sample to IDBI's full MSME book.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl border border-idbi-green/30 bg-idbi-green/5 p-4 flex flex-col justify-center">
              <div className="text-3xl font-extrabold text-idbi-green">{inr(econ.provSaved * econ.scale)}</div>
              <div className="text-sm font-semibold text-slate-700 mt-1">Provisioning saved / yr</div>
              <div className="text-xs text-slate-400">on full MSME book</div>
            </div>
            <div className="rounded-xl border border-slate-200 p-4 flex flex-col justify-center">
              <div className="text-3xl font-extrabold text-slate-900">{inr(econ.exposureProtected * econ.scale)}</div>
              <div className="text-sm font-semibold text-slate-700 mt-1">Exposure kept performing</div>
              <div className="text-xs text-slate-400">loans rescued before NPA</div>
            </div>
            <div className="col-span-2 rounded-xl border border-slate-100 bg-slate-50 p-3 text-xs text-slate-500">
              On this {Math.round(econ.sampleCr).toLocaleString('en-IN')}-cr sample: <b className="text-slate-700">{inr(econ.provSaved)}</b> provisioning saved ·
              expected NPA in flagged book <b className="text-slate-700">{inr(econ.expNpa)}</b>.
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
