import { useState } from 'react'
import {
  Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, ReferenceArea, ComposedChart, Area, Legend,
} from 'recharts'
import { X, TriangleAlert, FileText, Copy, Check, CalendarClock, Share2 } from 'lucide-react'
import { inr, pct, RAG } from '../lib/format'

export default function AccountDetail({ data, accountId, onClose }) {
  const [copied, setCopied] = useState(false)
  if (!accountId) return null
  const rec = data.portfolio.find((r) => r.account_id === accountId)
  const tl = data.timelines[accountId]
  const rag = RAG[rec.bucket]
  const redThr = data.portfolio_summary.red_thr * 100
  const amberThr = data.portfolio_summary.amber_thr * 100
  const refMonth = data.meta.reference_month

  const series = tl?.map((p) => ({
    date: p.date, pd: +((p.pd_smooth ?? p.pd) * 100).toFixed(1), pdRaw: +(p.pd * 100).toFixed(1),
    util: +(p.utilisation * 100).toFixed(0),
    inflowIdx: +(p.inflow / tl[0].inflow * 100).toFixed(0), mtn: p.months_to_npa, bucket: p.bucket,
  }))
  const lastDate = series?.[series.length - 1]?.date
  const npaEta = rec.ground_truth_default ? rec.snap_months_to_npa : null
  const futureMonths = series?.filter((p) => p.date > refMonth).length ?? 0
  const hasFuture = futureMonths >= 2

  const copyMemo = () => {
    navigator.clipboard?.writeText(data.memos[accountId] || '')
    setCopied(true); setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="fixed inset-0 z-40">
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} />
      <div className="absolute right-0 top-0 h-full w-full max-w-[720px] bg-slate-50 shadow-2xl overflow-y-auto scroll-thin">
        {/* header */}
        <div className="sticky top-0 z-10 bg-white border-b border-slate-200 px-6 py-4 flex items-start gap-4">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-extrabold text-slate-900">{rec.account_id}</h2>
              <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${rag.soft}`}>{rag.label.toUpperCase()}</span>
            </div>
            <div className="text-sm text-slate-500 mt-0.5">
              {rec.sector} · {rec.region} · {rec.loan_type} · {inr(rec.sanctioned)} sanctioned · {rec.business_age_years}y old
            </div>
          </div>
          <div className="text-right">
            <div className={`text-3xl font-extrabold ${rag.text} leading-none`}>{pct(rec.pd)}</div>
            <div className="text-[11px] text-slate-400 uppercase tracking-wide">12-mo default prob.</div>
          </div>
          <button onClick={onClose} aria-label="Close account detail"
            className="text-slate-400 hover:text-slate-700 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"><X size={22} /></button>
        </div>

        <div className="p-6 space-y-5">
          {/* lead-time / outcome banner */}
          <div className="flex flex-wrap gap-3">
            {rec.bucket === 'green' ? (
              <div className="flex items-center gap-2 bg-idbi-green/10 text-idbi-green rounded-lg px-3 py-2 text-sm font-semibold">
                <CalendarClock size={16} /> Healthy — no early-warning flag
              </div>
            ) : (
              <div className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold border ${rag.soft}`}>
                <CalendarClock size={16} /> On the watch-list · {rag.label}
                {rec.first_warning_lead ? ` · first flagged ${rec.first_warning_lead} mo before trouble` : ''}
              </div>
            )}
            {rec.runway?.rising && rec.runway.months && (
              <div className="flex items-center gap-2 bg-slate-100 text-slate-700 border border-slate-200 rounded-lg px-3 py-2 text-sm font-semibold"
                   title="Projected from the recent risk trend (least-squares). Median error ≈3 months on the synthetic book — a horizon for prioritisation, not a promise.">
                <CalendarClock size={16} /> Runway: ≈{rec.runway.months} mo before {rec.runway.toCritical ? 'critical' : 'act-now (Red)'}
              </div>
            )}
            {rec.eco_red >= 1 && (
              <div className="flex items-center gap-2 bg-orange-50 text-idbi-orange border border-orange-200 rounded-lg px-3 py-2 text-sm font-semibold"
                   title="Illustrative trading-partner links on the synthetic book; production plugs in CRILC exposures / GST buyer-supplier networks.">
                <Share2 size={16} /> Ecosystem: {rec.eco_flagged} of {rec.eco_partners} trading partners flagged ({rec.eco_red} red)
              </div>
            )}
            {npaEta != null && (
              <div className="flex items-center gap-2 bg-red-50 text-rag-red rounded-lg px-3 py-2 text-sm font-semibold">
                <TriangleAlert size={16} /> Actual outcome: went NPA {npaEta} month{npaEta === 1 ? '' : 's'} after this snapshot
              </div>
            )}
          </div>

          {!series?.length && (
            <div className="bg-white rounded-xl border border-slate-200 p-4 text-sm text-slate-500">
              No month-by-month trajectory available for this account.
            </div>
          )}

          {/* PD timeline */}
          {series?.length > 0 && <>
          <section className="bg-white rounded-xl border border-slate-200 p-4">
            <h3 className="font-bold text-slate-800 text-sm mb-1">Model risk score over time</h3>
            <p className="text-xs text-slate-400 mb-3">
              Both lines are the <b>model's</b> 12-month default-risk score (green = 3-month smoothed, the value officers act on;
              grey = raw monthly, shown for transparency) — <i>not</i> actual outcomes.
              {hasFuture
                ? ' Everything left of the “Today” line is what the officer would see now; the shaded band to its right is the period after Today (the actual outcome is called out in the banner above).'
                : ' This account reaches NPA right after Today, so the score ends at the “Today” line — the actual outcome is in the banner above.'}
            </p>
            <ResponsiveContainer width="100%" height={235}>
              <ComposedChart data={series} margin={{ top: 22, right: 8, left: -18, bottom: 0 }}>
                <defs>
                  <linearGradient id="pdFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#02684F" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#02684F" stopOpacity={0.03} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#eef2f6" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#94a3b8' }} interval={5} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#94a3b8' }} unit="%" />
                <Tooltip formatter={(v, n) => [`${v}%`, n]} labelFormatter={(l) => l} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {hasFuture && <ReferenceArea x1={refMonth} x2={lastDate} fill="#0f172a" fillOpacity={0.07}
                               label={{ value: 'after today →', fontSize: 10, fill: '#64748b', position: 'insideTopRight' }} />}
                <ReferenceLine y={redThr} stroke="#dc2626" strokeDasharray="4 4"
                               label={{ value: 'Red', fontSize: 9, fill: '#dc2626', position: 'insideRight' }} />
                <ReferenceLine y={amberThr} stroke="#d97706" strokeDasharray="4 4"
                               label={{ value: 'Amber', fontSize: 9, fill: '#d97706', position: 'insideRight' }} />
                <ReferenceLine x={refMonth} stroke="#0f172a" strokeWidth={2}
                               label={{ value: `TODAY · ${refMonth}`, fontSize: 11, fontWeight: 700, fill: '#0f172a', position: hasFuture ? 'top' : 'insideTopLeft' }} />
                <Area type="monotone" dataKey="pd" name="Risk score (smoothed)" stroke="#02684F" strokeWidth={2.5} fill="url(#pdFill)" isAnimationActive={false} />
                <Line type="monotone" dataKey="pdRaw" name="Raw monthly score" stroke="#cbd5e1" strokeWidth={1} dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </section>

          {/* signals */}
          <section className="bg-white rounded-xl border border-slate-200 p-4">
            <h3 className="font-bold text-slate-800 text-sm mb-1">Why — the underlying slide</h3>
            <p className="text-xs text-slate-400 mb-3">Cash inflows (indexed to 100 at start) fall while credit-limit use climbs — the leading signals, well before any missed payment.</p>
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={series} margin={{ top: 5, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eef2f6" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#94a3b8' }} interval={5} />
                <YAxis yAxisId="l" tick={{ fontSize: 10, fill: '#94a3b8' }} />
                <YAxis yAxisId="r" orientation="right" domain={[0, 110]} tick={{ fontSize: 10, fill: '#94a3b8' }} unit="%" />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <ReferenceLine x={refMonth} yAxisId="l" stroke="#0f172a" strokeDasharray="5 3" />
                <Line yAxisId="l" type="monotone" dataKey="inflowIdx" name="Bank inflows (index)" stroke="#0ea5e9" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line yAxisId="r" type="monotone" dataKey="util" name="Credit-limit use %" stroke="#FF4D01" strokeWidth={2} dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </section>
          </>}

          {/* reason codes */}
          <section className="bg-white rounded-xl border border-slate-200 p-4">
            <h3 className="font-bold text-slate-800 text-sm mb-3">Why the model flagged this account</h3>
            <div className="space-y-2">
              {(rec.reasons?.length ? rec.reasons : ['No elevated risk signals — account conduct is healthy.']).map((r, i) => (
                <div key={i} className="flex items-center gap-2.5 text-sm">
                  <span className={`w-6 h-6 grid place-items-center rounded-md ${rec.bucket === 'green' ? 'bg-green-50 text-rag-green' : 'bg-amber-50 text-rag-amber'}`}>
                    <TriangleAlert size={14} />
                  </span>
                  <span className="text-slate-700">{r}</span>
                </div>
              ))}
            </div>
          </section>

          {/* auto-drafted memo */}
          {data.memos[accountId] && (
            <section className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="flex items-center gap-2 mb-3">
                <FileText size={16} className="text-idbi-green" />
                <h3 className="font-bold text-slate-800 text-sm flex-1">Auto-drafted early-warning memo</h3>
                <button onClick={copyMemo} className="flex items-center gap-1 text-xs text-slate-500 hover:text-idbi-green">
                  {copied ? <Check size={13} /> : <Copy size={13} />}{copied ? 'Copied' : 'Copy'}
                </button>
              </div>
              <pre className="text-xs text-slate-600 whitespace-pre-wrap font-mono bg-slate-50 rounded-lg p-3 border border-slate-100">
{data.memos[accountId]}
              </pre>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
