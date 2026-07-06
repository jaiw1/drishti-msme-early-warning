import { useState, useEffect } from 'react'
import Kpis from './components/Kpis'
import PortfolioTable from './components/PortfolioTable'
import AccountDetail from './components/AccountDetail'
import Analytics from './components/Analytics'
import PortfolioRisk from './components/PortfolioRisk'
import RealModel from './components/RealModel'
import Guide from './components/Guide'
import { Radar, LayoutGrid, LineChart, PieChart, BadgeCheck, ShieldCheck, Info, Compass } from 'lucide-react'

const NAV = [
  { key: 'portfolio', label: 'Watch-list', icon: LayoutGrid },
  { key: 'risk', label: 'Portfolio risk', icon: PieChart },
  { key: 'analytics', label: 'Model & Metrics', icon: LineChart },
  { key: 'real', label: 'Real-data model', icon: BadgeCheck },
]
const TITLES = {
  portfolio: ['MSME Loan Watch-list', 'Predicting default 12 months ahead'],
  risk: ['Portfolio Risk & Impact', 'Where the risk sits, and what acting early is worth'],
  analytics: ['Model Performance', 'Honest metrics, lead-time and model rigor'],
  real: ['Real-Data Validation', 'The same method, proven on real Indian MSMEs'],
}

export default function App() {
  const params = new URLSearchParams(window.location.search)
  const pv = params.get('view')
  const [view, setView] = useState(['risk', 'analytics', 'real', 'portfolio'].includes(pv) ? pv : 'portfolio')
  const [selected, setSelected] = useState(params.get('account') || null)
  const [data, setData] = useState(null)
  const [realData, setRealData] = useState(null)
  const [guide, setGuide] = useState(false)

  useEffect(() => {
    const b = import.meta.env.BASE_URL
    fetch(`${b}demo_data.json`).then((r) => r.json()).then(setData).catch(() => {})
    fetch(`${b}real_model.json`).then((r) => r.json()).then(setRealData).catch(() => {})
    if (!localStorage.getItem('drishti_seen_guide')) setGuide(true)   // auto-show on first visit
  }, [])

  const closeGuide = () => { setGuide(false); localStorage.setItem('drishti_seen_guide', '1') }

  if (!data) return (
    <div className="min-h-screen grid place-items-center text-slate-400">
      <div className="flex items-center gap-2 text-sm"><Radar size={18} className="animate-spin" /> Loading DRISHTi…</div>
    </div>
  )

  return (
    <div className="min-h-screen flex">
      {/* sidebar */}
      <aside className="w-60 shrink-0 bg-idbi-green text-white flex-col hidden md:flex">
        <div className="px-5 py-5 flex items-center gap-2.5 border-b border-white/10">
          <div className="w-9 h-9 rounded-lg bg-white/15 grid place-items-center"><Radar size={20} /></div>
          <div>
            <div className="font-extrabold leading-tight">DRISHT<span className="text-idbi-orange">i</span></div>
            <div className="text-[10px] text-white/60 leading-tight">MSME Early-Warning</div>
          </div>
        </div>
        <nav className="p-3 space-y-1">
          {NAV.map((n) => (
            <button key={n.key} onClick={() => setView(n.key)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition ${view === n.key ? 'bg-white/15' : 'text-white/70 hover:bg-white/10'}`}>
              <n.icon size={18} /> {n.label}
            </button>
          ))}
        </nav>
        <div className="mt-auto p-4 text-[11px] text-white/50 leading-relaxed border-t border-white/10">
          <div className="flex items-center gap-1.5 mb-1 text-white/70"><ShieldCheck size={13} /> Human-in-the-loop</div>
          The model advises; the credit officer decides. IDBI Innovate 2026 · Track 4.
        </div>
      </aside>

      {/* main */}
      <main className="flex-1 min-w-0">
        <header className="bg-white border-b border-slate-200 px-6 py-3.5 flex items-center gap-3">
          <div>
            <h1 className="text-lg font-extrabold text-slate-900">{TITLES[view][0]}</h1>
            <p className="text-xs text-slate-400">
              {TITLES[view][1]} · book as of {data.meta.reference_month} · {data.meta.n_accounts_scored.toLocaleString('en-IN')} live accounts
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button onClick={() => setGuide(true)}
              className="flex items-center gap-1.5 text-xs font-semibold text-idbi-green bg-idbi-green/10 hover:bg-idbi-green/20 rounded-lg px-3 py-1.5 transition">
              <Compass size={14} /> Tour
            </button>
            <div className="hidden sm:flex items-center gap-2 text-xs text-slate-500 bg-slate-100 rounded-lg px-3 py-1.5">
              <Info size={13} /> Synthetic demo data — sandbox APIs post-shortlisting
            </div>
          </div>
        </header>

        <div className="p-6 space-y-5">
          {view === 'portfolio' && (
            <>
              <Kpis summary={data.portfolio_summary} metrics={data.metrics} />
              <PortfolioTable rows={data.portfolio} spotlight={data.spotlight} onSelect={setSelected} />
            </>
          )}
          {view === 'risk' && <PortfolioRisk data={data} />}
          {view === 'analytics' && <Analytics data={data} />}
          {view === 'real' && <RealModel data={realData} syntheticAuc={data.metrics.auc} />}
        </div>
      </main>

      {selected && <AccountDetail data={data} accountId={selected} onClose={() => setSelected(null)} />}
      {guide && <Guide setView={setView} setSelected={setSelected} onClose={closeGuide} />}
    </div>
  )
}
