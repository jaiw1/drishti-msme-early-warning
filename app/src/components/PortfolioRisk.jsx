// Where the risk is concentrated, and what acting early is worth.
//
// Three concentration panels, not two: sector, segment, and — the one the mentors asked
// for — **lending portfolio**. A single holistic model across eight products is only a
// claim worth making if you can see it holding per product, so the portfolio panel carries
// each portfolio's own Red-band precision beside its flagged exposure.

import { useMemo, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, LabelList, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import {
  ChevronRight, IndianRupee, Layers, LayoutGrid, PhoneCall, Share2, ShieldCheck, TriangleAlert,
} from 'lucide-react'
import DataTable, { useRovingRows } from './DataTable'
import { inr, pct, RAG } from '../lib/format'
import { byPortfolioList } from '../domain/shapes'

// IDBI's MSME/priority book isn't a single published figure; public disclosures put it
// broadly in the ₹25,000–35,000 cr range, so this is an ADJUSTABLE assumption (slider
// below), not a hard claim. The per-sample numbers are the defensible core.
const DEFAULT_BOOK_CR = 30000

function groupBy(rows, key) {
  const m = {}
  for (const r of rows) {
    const name = r[key]
    if (name == null) continue
    const g = (m[name] ||= { name, total: 0, red: 0, amber: 0, green: 0, flagged: 0, count: 0 })
    const amount = Number(r.sanctioned) || 0
    g.total += amount
    g.count++
    if (g[r.bucket] !== undefined) g[r.bucket] += amount
    if (r.bucket !== 'green') g.flagged++
  }
  return Object.values(m)
    .map((g) => ({ ...g, redCr: g.red / 1e7, amberCr: g.amber / 1e7, pctFlagged: g.total ? (g.red + g.amber) / g.total : 0 }))
    .sort((a, b) => (b.red + b.amber) - (a.red + a.amber))
}

function Slider({ label, value, set, min, max, step, fmt, id }) {
  return (
    <div>
      <div className="mb-1 flex justify-between text-sm">
        <label htmlFor={id} className="text-slate-700">{label}</label>
        <output htmlFor={id} className="font-bold text-idbi-green">{fmt(value)}</output>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => set(+e.target.value)}
        className="w-full cursor-pointer accent-idbi-green"
      />
    </div>
  )
}

/**
 * Per-portfolio Red-band precision, with its confidence interval.
 * A precision of 100% on four accounts is not a strong claim, and the interval is what
 * says so — which is why the n is on the card and not in a footnote.
 */
function PrecisionCard({ entry }) {
  const block = entry.red_band_precision_8m
  const value = typeof block === 'number' ? block : block?.value
  const lo = block?.ci_low ?? block?.ci_lo
  const hi = block?.ci_high ?? block?.ci_hi
  const red = entry.by_band?.find((b) => b.band === 'Red')
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="text-xs font-semibold text-slate-700">{entry.portfolio}</div>
      {value == null ? (
        <>
          <div className="mt-1 text-sm font-semibold text-slate-500">not reported</div>
          <p className="mt-0.5 text-[11px] leading-relaxed text-slate-600">
            This run published no Red-band precision for {entry.portfolio}.
          </p>
        </>
      ) : (
        <>
          <div className="mt-1 text-2xl font-extrabold text-idbi-green">{pct(value, 1)}</div>
          <p className="mt-0.5 text-[11px] leading-relaxed text-slate-600">
            of Red-band accounts reached NPA
            {red ? ` (${red.defaults} of ${red.n})` : ''}
            {lo != null && hi != null && <> · 95% CI {pct(lo, 1)}–{pct(hi, 1)}</>}
          </p>
          {red?.n === 0 && (
            <p className="mt-1 text-[11px] text-rag-ambertx">Red band is empty here — nothing to measure.</p>
          )}
        </>
      )}
    </div>
  )
}

export default function PortfolioRisk({ rows, summary, ecosystem, rankOrder, onSelect }) {
  const [cure, setCure] = useState(0.4)
  const [prov, setProv] = useState(0.15)
  const [book, setBook] = useState(DEFAULT_BOOK_CR)

  const bySector = useMemo(() => groupBy(rows, 'sector'), [rows])
  const bySegment = useMemo(() => groupBy(rows, 'segment'), [rows])
  const byPortfolio = useMemo(() => groupBy(rows, 'portfolio'), [rows])
  const precision = useMemo(() => byPortfolioList(rankOrder), [rankOrder])

  const actFirst = useMemo(() =>
    rows.filter((r) => r.bucket !== 'green')
      .map((r) => ({ ...r, atRisk: (r.pd || 0) * (Number(r.sanctioned) || 0) }))
      .sort((a, b) => b.atRisk - a.atRisk)
      .slice(0, 10), [rows])

  const econ = useMemo(() => {
    const flagged = rows.filter((r) => r.bucket !== 'green')
    const expNpa = flagged.reduce((s, r) => s + (r.pd || 0) * (Number(r.sanctioned) || 0), 0)
    const sampleCr = rows.reduce((s, r) => s + (Number(r.sanctioned) || 0), 0) / 1e7
    const scale = sampleCr > 0 ? book / sampleCr : 0
    return {
      expNpa,
      sampleCr,
      scale,
      provSaved: expNpa * prov * cure,
      exposureProtected: expNpa * cure,
      flaggedCount: flagged.length,
    }
  }, [rows, cure, prov, book])

  const topSector = bySector[0]
  const exposureAtRisk = summary?.exposure_at_risk
    ?? rows.filter((r) => r.bucket !== 'green').reduce((s, r) => s + (Number(r.sanctioned) || 0), 0)

  const { bodyRef, rowProps } = useRovingRows(actFirst.length, { onActivate: onSelect })

  return (
    <div className="space-y-5">
      {/* headline impact cards */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="mb-1 flex items-center gap-2 text-rag-redtx">
            <TriangleAlert size={16} aria-hidden="true" />
            <span className="text-xs font-semibold uppercase tracking-wide">Flagged exposure</span>
          </div>
          <div className="text-2xl font-extrabold text-slate-900">{inr(exposureAtRisk)}</div>
          <div className="text-xs text-slate-600">{econ.flaggedCount} watch-list accounts (red + amber)</div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="mb-1 flex items-center gap-2 text-idbi-orangetx">
            <Layers size={16} aria-hidden="true" />
            <span className="text-xs font-semibold uppercase tracking-wide">Most-stressed sector</span>
          </div>
          <div className="text-2xl font-extrabold text-slate-900">{topSector?.name || '—'}</div>
          <div className="text-xs text-slate-600">
            {inr((topSector?.red + topSector?.amber) || 0)} flagged ({Math.round((topSector?.pctFlagged || 0) * 100)}% of its book)
          </div>
        </div>
        <div className="rounded-xl border border-idbi-green/30 bg-idbi-green/5 p-4">
          <div className="mb-1 flex items-center gap-2 text-idbi-green">
            <ShieldCheck size={16} aria-hidden="true" />
            <span className="text-xs font-semibold uppercase tracking-wide">Provisioning saved / yr</span>
          </div>
          <div className="text-2xl font-extrabold text-idbi-green">{inr(econ.provSaved * econ.scale)}</div>
          <div className="text-xs text-slate-600">assumes a ~₹{(book / 1000).toFixed(0)}k cr MSME book (adjustable below)</div>
        </div>
      </div>

      {/* concentration: portfolio, sector, segment */}
      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="mb-1 flex items-center gap-2">
          <LayoutGrid size={16} className="text-idbi-green" aria-hidden="true" />
          <h3 className="font-bold text-slate-800">Where is the risk concentrated? (by lending portfolio)</h3>
        </div>
        <p className="mb-4 mt-1 max-w-3xl text-xs leading-relaxed text-slate-600">
          One model scores all eight products. This is the cut that tests that claim: flagged exposure per portfolio,
          with each portfolio’s own realised Red-band precision underneath. A portfolio whose Red band never goes bad
          would mean the single model is not ranking risk there — so the number is published per product, not only pooled.
        </p>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={byPortfolio} margin={{ top: 6, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#475569' }} interval={0} angle={-18} textAnchor="end" height={52} />
            <YAxis tick={{ fontSize: 10, fill: '#475569' }} unit=" cr" />
            <Tooltip formatter={(v, n) => [`₹${(+v).toFixed(2)} cr`, n]} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="amberCr" name="Amber" stackId="a" fill="#d97706" isAnimationActive={false} />
            <Bar dataKey="redCr" name="Red" stackId="a" fill="#dc2626" radius={[4, 4, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>

        {precision.length > 0 ? (
          <>
            <h4 className="mb-2 mt-5 text-xs font-extrabold uppercase tracking-wide text-idbi-green">
              Red-band precision, per portfolio
            </h4>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {precision.map((entry) => <PrecisionCard key={entry.portfolio} entry={entry} />)}
            </div>
          </>
        ) : (
          <p className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-600">
            This model run published no per-portfolio rank-order exhibit, so no per-portfolio precision is claimed here.
          </p>
        )}
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="font-bold text-slate-800">By sector</h3>
          <p className="mb-4 mt-1 text-xs text-slate-600">Flagged exposure (₹ cr) per sector — a fast read on which pockets of the book are stressed.</p>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={bySector} margin={{ top: 6, right: 8, left: -12, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#475569' }} interval={0} angle={-18} textAnchor="end" height={52} />
              <YAxis tick={{ fontSize: 10, fill: '#475569' }} unit=" cr" />
              <Tooltip formatter={(v, n) => [`₹${(+v).toFixed(2)} cr`, n]} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar dataKey="amberCr" name="Amber" stackId="a" fill="#d97706" isAnimationActive={false} />
              <Bar dataKey="redCr" name="Red" stackId="a" fill="#dc2626" radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="font-bold text-slate-800">By segment</h3>
          <p className="mb-4 mt-1 text-xs text-slate-600">Share of each segment’s book that is flagged — is the stress in Micro, Small or Medium?</p>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={bySegment} margin={{ top: 18, right: 8, left: -12, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#475569' }} />
              <YAxis tick={{ fontSize: 10, fill: '#475569' }} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
              <Tooltip formatter={(v) => [`${(v * 100).toFixed(1)}%`, 'flagged']} />
              <Bar dataKey="pctFlagged" fill="#02684F" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                <LabelList dataKey="pctFlagged" position="top" formatter={(v) => `${(v * 100).toFixed(1)}%`}
                  style={{ fontSize: 11, fill: '#1e293b', fontWeight: 700 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </section>
      </div>

      {/* act-first ranking */}
      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="mb-1 flex items-center gap-2">
          <PhoneCall size={16} className="text-idbi-green" aria-hidden="true" />
          <h3 className="font-bold text-slate-800">Who to call first — top 10 by ₹ at risk</h3>
        </div>
        <p className="mb-3 text-xs leading-relaxed text-slate-600">
          Flagged accounts ranked by expected loss (model PD × sanctioned exposure) — the order that protects the
          most money per officer-hour. Open any row for the full account story.
        </p>
        <div className="overflow-x-auto scroll-thin">
          <DataTable caption="Top ten flagged accounts by rupees at risk">
            <thead>
              <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wide text-slate-600">
                <th scope="col" className="py-2 pr-3 font-semibold">#</th>
                <th scope="col" className="py-2 pr-3 font-semibold">Account</th>
                <th scope="col" className="py-2 pr-3 font-semibold">Portfolio</th>
                <th scope="col" className="py-2 pr-3 text-right font-semibold">Sanctioned</th>
                <th scope="col" className="py-2 pr-3 text-right font-semibold">12-mo PD</th>
                <th scope="col" className="py-2 pr-3 text-right font-semibold">₹ at risk</th>
                <th scope="col" className="hidden py-2 pr-3 font-semibold lg:table-cell">Top early-warning signal</th>
              </tr>
            </thead>
            <tbody ref={bodyRef}>
              {actFirst.map((r, i) => {
                const rag = RAG[r.bucket] || RAG.green
                return (
                  <tr
                    key={r.account_id}
                    {...rowProps(i, r.account_id)}
                    onClick={() => onSelect?.(r.account_id)}
                    aria-label={`${r.account_id}, ${inr(r.atRisk)} at risk`}
                    className="cursor-pointer border-b border-slate-100 hover:bg-slate-50 focus:bg-idbi-green/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-idbi-green"
                  >
                    <td className="py-2 pr-3 font-semibold text-slate-600">{i + 1}</td>
                    <th scope="row" className="py-2 pr-3 text-left">
                      <span className={`mr-2 inline-block h-2 w-2 rounded-full ${rag.dot}`} aria-hidden="true" />
                      <span className="font-semibold text-slate-800">{r.account_id}</span>
                    </th>
                    <td className="py-2 pr-3 text-slate-600">{r.portfolio || r.sector || '—'}</td>
                    <td className="py-2 pr-3 text-right text-slate-700">{inr(r.sanctioned)}</td>
                    <td className={`py-2 pr-3 text-right font-bold ${rag.text}`}>{pct(r.pd)}</td>
                    <td className="py-2 pr-3 text-right font-bold text-slate-900">{inr(r.atRisk)}</td>
                    <td className="hidden max-w-[280px] truncate py-2 pr-3 text-slate-600 lg:table-cell">{r.reasons?.[0] || '—'}</td>
                    <td className="py-2 text-slate-500"><ChevronRight size={15} aria-hidden="true" /></td>
                  </tr>
                )
              })}
            </tbody>
          </DataTable>
        </div>
      </section>

      {/* ecosystem stress (contagion lens) */}
      {ecosystem && (
        <section className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="mb-1 flex items-center gap-2">
            <Share2 size={16} className="text-idbi-orangetx" aria-hidden="true" />
            <h3 className="font-bold text-slate-800">Stress travels through trading networks</h3>
          </div>
          <p className="mb-4 max-w-3xl text-xs leading-relaxed text-slate-600">
            A supplier’s default becomes its buyers’ cash-flow problem — often before their own numbers move. This
            second lens looks one link out from every red account. The model’s PD is untouched; these are accounts
            that deserve a manual look <b>before</b> their own signals turn.
            {ecosystem.linkage && <> Linkage here is <b>{ecosystem.linkage}</b>.</>}
          </p>
          <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-slate-200 p-4">
              <div className="text-2xl font-extrabold text-rag-greentx">{ecosystem.n_green_1link_red ?? '—'}</div>
              <div className="text-sm font-semibold text-slate-700">Green accounts, 1 link from a red</div>
              <div className="text-xs text-slate-600">healthy today — trading beside distress</div>
            </div>
            <div className="rounded-xl border border-slate-200 p-4">
              <div className="text-2xl font-extrabold text-rag-ambertx">{ecosystem.n_amber_1link_red ?? '—'}</div>
              <div className="text-sm font-semibold text-slate-700">Amber accounts, 1 link from a red</div>
              <div className="text-xs text-slate-600">already sliding, network adds pressure</div>
            </div>
            <div className="rounded-xl border border-idbi-orange/30 bg-orange-50/50 p-4">
              <div className="text-2xl font-extrabold text-idbi-orangetx">{inr(ecosystem.exposure_1link_red)}</div>
              <div className="text-sm font-semibold text-slate-700">Exposure within one link of distress</div>
              <div className="text-xs text-slate-600">the contagion-watch book</div>
            </div>
          </div>
          <ul className="flex flex-wrap gap-2">
            {(ecosystem.by_sector || []).map((s) => (
              <li key={s.sector} className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-700">
                {s.sector}: <b>{s.n}</b> accounts · {inr(s.exposure)}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-600">
            Illustrative partner links; in production this lens plugs into CRILC common-exposure data and GST
            buyer–supplier networks — the cockpit is already wired for it.
          </p>
        </section>
      )}

      {/* what-if */}
      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="mb-1 flex items-center gap-2">
          <IndianRupee size={18} className="text-idbi-green" aria-hidden="true" />
          <h3 className="font-bold text-slate-800">What early action is worth — provisioning what-if</h3>
        </div>
        <p className="mb-5 max-w-3xl text-xs leading-relaxed text-slate-600">
          When a loan slips to NPA the bank must set aside provisions (RBI IRAC). If officers act on DRISHTi’s early
          flags and rescue a share of them, that provisioning is avoided. Move the sliders to see the impact.
        </p>
        <div className="grid gap-8 md:grid-cols-2">
          <div className="space-y-5">
            <Slider id="wi-cure" label="Accounts cured by acting early" value={cure} set={setCure} min={0.1} max={0.7} step={0.05} fmt={(v) => `${Math.round(v * 100)}%`} />
            <Slider id="wi-prov" label="Provisioning rate on NPA (IRAC)" value={prov} set={setProv} min={0.1} max={0.4} step={0.05} fmt={(v) => `${Math.round(v * 100)}%`} />
            <Slider id="wi-book" label="Assumed IDBI MSME book size" value={book} set={setBook} min={25000} max={35000} step={1000} fmt={(v) => `₹${(v / 1000).toFixed(0)}k cr`} />
            <p className="text-[11px] leading-relaxed text-slate-600">
              <b>Assumptions (all adjustable):</b> Expected NPA = Σ (model PD × exposure) over the flagged accounts;
              provisioning saved = Expected NPA × provisioning rate × cure rate — computed on this
              ₹{Math.round(econ.sampleCr).toLocaleString('en-IN')} cr sample, then scaled to the full book. The book
              size is an assumption (public disclosures put IDBI’s MSME/priority book broadly at ₹25–35k cr); the
              ₹-sample figures below don’t depend on it.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col justify-center rounded-xl border border-idbi-green/30 bg-idbi-green/5 p-4">
              <div className="text-3xl font-extrabold text-idbi-green">{inr(econ.provSaved * econ.scale)}</div>
              <div className="mt-1 text-sm font-semibold text-slate-700">Provisioning saved / yr</div>
              <div className="text-xs text-slate-600">on full MSME book</div>
            </div>
            <div className="flex flex-col justify-center rounded-xl border border-slate-200 p-4">
              <div className="text-3xl font-extrabold text-slate-900">{inr(econ.exposureProtected * econ.scale)}</div>
              <div className="mt-1 text-sm font-semibold text-slate-700">Exposure kept performing</div>
              <div className="text-xs text-slate-600">loans rescued before NPA</div>
            </div>
            <div className="col-span-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
              On this {Math.round(econ.sampleCr).toLocaleString('en-IN')}-cr sample:
              {' '}<b>{inr(econ.provSaved)}</b> provisioning saved · expected NPA in flagged book <b>{inr(econ.expNpa)}</b>.
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
