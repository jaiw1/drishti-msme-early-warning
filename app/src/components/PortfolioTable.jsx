import { useState, useMemo } from 'react'
import { inr, pct, RAG } from '../lib/format'
import { Search, ArrowUpDown } from 'lucide-react'

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'red', label: 'Red' },
  { key: 'amber', label: 'Amber' },
  { key: 'green', label: 'Green' },
]

export default function PortfolioTable({ rows, onSelect }) {
  const [filter, setFilter] = useState('red')
  const [sector, setSector] = useState('all')
  const [q, setQ] = useState('')
  const [sortKey, setSortKey] = useState('pd')
  const [asc, setAsc] = useState(false)
  const sectors = useMemo(() => Array.from(new Set(rows.map((r) => r.sector))).sort(), [rows])

  const view = useMemo(() => {
    let r = rows
    if (filter !== 'all') r = r.filter((x) => x.bucket === filter)
    if (sector !== 'all') r = r.filter((x) => x.sector === sector)
    if (q) r = r.filter((x) => x.account_id.toLowerCase().includes(q.toLowerCase()) ||
                                x.sector.toLowerCase().includes(q.toLowerCase()))
    return [...r].sort((a, b) => {
      const va = a[sortKey], vb = b[sortKey]
      const c = typeof va === 'string' ? va.localeCompare(vb) : va - vb
      return asc ? c : -c
    })
  }, [rows, filter, sector, q, sortKey, asc])

  const setSort = (k) => { if (k === sortKey) setAsc(!asc); else { setSortKey(k); setAsc(false) } }
  const Th = ({ k, children, right }) => (
    <th className={`px-3 py-2 font-semibold text-slate-500 ${right ? 'text-right' : 'text-left'} cursor-pointer select-none`}
        onClick={() => setSort(k)}>
      <span className={`inline-flex items-center gap-1 ${right ? 'flex-row-reverse' : ''}`}>{children}<ArrowUpDown size={12} className="opacity-40" /></span>
    </th>
  )

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 p-3 border-b border-slate-100">
        <div className="flex gap-1 bg-slate-100 rounded-lg p-1">
          {FILTERS.map((f) => (
            <button key={f.key} onClick={() => setFilter(f.key)}
              className={`px-3 py-1 text-sm rounded-md font-medium transition ${filter === f.key ? 'bg-white shadow text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}>
              {f.label}
            </button>
          ))}
        </div>
        <select value={sector} onChange={(e) => setSector(e.target.value)}
          className="text-sm border border-slate-200 rounded-lg px-2.5 py-1.5 text-slate-600 bg-white cursor-pointer focus:outline-none focus:ring-2 focus:ring-idbi-green/30">
          <option value="all">All sectors</option>
          {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <div className="text-xs text-slate-400">{view.length} accounts</div>
        <div className="ml-auto relative">
          <Search size={15} className="absolute left-2.5 top-2.5 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search id / sector"
            className="pl-8 pr-3 py-1.5 text-sm border border-slate-200 rounded-lg w-56 focus:outline-none focus:ring-2 focus:ring-idbi-green/30" />
        </div>
      </div>

      <div className="max-h-[540px] overflow-auto scroll-thin">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 sticky top-0 z-10 text-xs">
            <tr>
              <Th k="account_id">Account</Th>
              <Th k="sector">Sector</Th>
              <Th k="pd" right>PD (12-mo)</Th>
              <Th k="first_warning_lead" right>Lead</Th>
              <th className="px-3 py-2 text-right font-semibold text-slate-500 whitespace-nowrap" title="Projected months before the risk trend crosses the next threshold (median error ≈3 mo)">Runway</th>
              <Th k="sanctioned" right>Exposure</Th>
              <th className="px-3 py-2 text-left font-semibold text-slate-500">Top early-warning signal</th>
            </tr>
          </thead>
          <tbody>
            {view.map((r) => {
              const rag = RAG[r.bucket]
              return (
                <tr key={r.account_id} onClick={() => onSelect(r.account_id)}
                    className="border-t border-slate-50 hover:bg-idbi-green/5 cursor-pointer">
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${rag.dot}`} />
                      <span className="font-semibold text-slate-800">{r.account_id}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-slate-500">{r.sector}</td>
                  <td className={`px-3 py-2.5 text-right font-bold ${rag.text}`}>{pct(r.pd)}</td>
                  <td className="px-3 py-2.5 text-right text-slate-600">{r.first_warning_lead ? `${r.first_warning_lead} mo` : '—'}</td>
                  <td className={`px-3 py-2.5 text-right ${r.runway?.months && r.runway.months <= 3 ? 'text-rag-red font-semibold' : 'text-slate-600'}`}>
                    {r.runway?.rising && r.runway.months ? `≈${r.runway.months} mo` : '—'}
                  </td>
                  <td className="px-3 py-2.5 text-right text-slate-600">{inr(r.sanctioned)}</td>
                  <td className="px-3 py-2.5 text-slate-500 max-w-[280px] truncate">
                    {r.reasons?.find((x) => !x.startsWith('Adverse')) || r.reasons?.[0] || '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
