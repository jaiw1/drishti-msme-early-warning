import { useState, useEffect } from 'react'
import Kpis from './components/Kpis'
import PortfolioTable from './components/PortfolioTable'
import AccountDetail from './components/AccountDetail'
import Analytics from './components/Analytics'
import PortfolioRisk from './components/PortfolioRisk'
import RealModel from './components/RealModel'
import Guide from './components/Guide'
import { Radar, LayoutGrid, LineChart, PieChart, BadgeCheck, ShieldCheck, Info, Compass, TriangleAlert, RefreshCw } from 'lucide-react'

const NAV = [
  { key: 'portfolio', label: 'Watch-list', short: 'Watch-list', icon: LayoutGrid },
  { key: 'real', label: 'Real-data model', short: 'Real data', icon: BadgeCheck, badge: 'REAL' },
  { key: 'risk', label: 'Portfolio risk', short: 'Risk', icon: PieChart },
  { key: 'analytics', label: 'Model & Metrics', short: 'Model', icon: LineChart },
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
  const [loadError, setLoadError] = useState(false)
  const [guide, setGuide] = useState(false)

  const loadData = () => {
    setLoadError(false)
    const b = import.meta.env.BASE_URL
    fetch(`${b}demo_data.json`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setData)
      .catch(() => setLoadError(true))
    // real-data tab degrades gracefully without this file, so a failure here is non-fatal
    fetch(`${b}real_model.json`).then((r) => r.json()).then(setRealData).catch(() => {})
  }

  useEffect(() => {
    loadData()
    // auto-show on first visit; ?tour=0 suppresses it (screenshots, direct deep-links)
    if (!localStorage.getItem('drishti_seen_guide') && params.get('tour') !== '0') setGuide(true)
  }, [])

  const closeGuide = () => { setGuide(false); localStorage.setItem('drishti_seen_guide', '1') }

  if (loadError) return (
    <div className="min-h-screen grid place-items-center bg-slate-50 px-6">
      <div className="max-w-sm w-full bg-white border border-slate-200 rounded-xl p-6 text-center space-y-3 shadow-sm">
        <TriangleAlert className="mx-auto text-rag-amber" size={30} />
        <div className="font-bold text-slate-800">Couldn’t load the portfolio data</div>
        <p className="text-sm text-slate-500">The connection may have dropped while downloading the demo dataset (~1 MB). Please retry.</p>
        <button onClick={loadData}
          className="inline-flex items-center gap-2 bg-idbi-green text-white text-sm font-semibold rounded-lg px-4 py-2 hover:bg-idbi-green/90 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green focus-visible:ring-offset-2">
          <RefreshCw size={15} /> Retry
        </button>
      </div>
    </div>
  )

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
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70 ${view === n.key ? 'bg-white/15' : 'text-white/70 hover:bg-white/10'}`}>
              <n.icon size={18} /> <span className="flex-1 text-left">{n.label}</span>
              {n.badge && <span className="text-[9px] font-extrabold bg-idbi-orange text-white px-1.5 py-0.5 rounded tracking-wide">{n.badge}</span>}
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
          <div className="md:hidden w-9 h-9 rounded-lg bg-idbi-green text-white grid place-items-center shrink-0" aria-hidden="true">
            <Radar size={18} />
          </div>
          <div>
            <h1 className="text-lg font-extrabold text-slate-900">{TITLES[view][0]}</h1>
            <p className="text-xs text-slate-400">
              {TITLES[view][1]} · book as of {data.meta.reference_month} · {data.meta.n_accounts_scored.toLocaleString('en-IN')} live accounts
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button onClick={() => setGuide(true)}
              className="flex items-center gap-1.5 text-xs font-semibold text-idbi-green bg-idbi-green/10 hover:bg-idbi-green/20 rounded-lg px-3 py-1.5 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green">
              <Compass size={14} /> Tour
            </button>
            <div className="hidden sm:flex items-center gap-2 text-xs text-slate-500 bg-slate-100 rounded-lg px-3 py-1.5">
              <Info size={13} /> Synthetic demo data — sandbox APIs post-shortlisting
            </div>
          </div>
        </header>

        <div className="p-6 space-y-5 pb-24 md:pb-6">
          {view === 'portfolio' && (
            <>
              <button onClick={() => setView('real')}
                className="w-full flex items-center gap-3 bg-gradient-to-r from-idbi-green/10 to-idbi-green/5 border border-idbi-green/30 rounded-xl px-4 py-3 hover:from-idbi-green/15 hover:to-idbi-green/10 transition text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green">
                <BadgeCheck className="text-idbi-green shrink-0" size={22} />
                <div className="flex-1 text-sm leading-snug">
                  <span className="font-bold text-idbi-green">Validated on {realData ? realData.meta.n_companies.toLocaleString('en-IN') : '3,200'} real Indian MSMEs</span>
                  <span className="text-slate-600"> — the same method scores an honest <b>{realData ? realData.metrics.auc : '0.81'} AUC</b> on real credit-rating defaults, not just synthetic data.</span>
                </div>
                <span className="text-idbi-green text-sm font-bold whitespace-nowrap">See the proof →</span>
              </button>
              <Kpis summary={data.portfolio_summary} metrics={data.metrics} />
              <PortfolioTable rows={data.portfolio} spotlight={data.spotlight} onSelect={setSelected} />
            </>
          )}
          {view === 'risk' && <PortfolioRisk data={data} onSelect={setSelected} />}
          {view === 'analytics' && <Analytics data={data} />}
          {view === 'real' && <RealModel data={realData} syntheticAuc={data.metrics.auc} />}
        </div>
      </main>

      {/* mobile bottom nav (sidebar is hidden below md) */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 z-30 bg-idbi-green text-white border-t border-white/10 flex pb-[env(safe-area-inset-bottom)]">
        {NAV.map((n) => (
          <button key={n.key} onClick={() => setView(n.key)}
            className={`flex-1 flex flex-col items-center gap-0.5 py-2 text-[10px] font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-white/70 ${view === n.key ? 'text-white bg-white/15' : 'text-white/60'}`}>
            <n.icon size={18} /> {n.short}
          </button>
        ))}
      </nav>

      {selected && <AccountDetail data={data} accountId={selected} onClose={() => setSelected(null)} />}
      {guide && <Guide setView={setView} setSelected={setSelected} onClose={closeGuide} />}
    </div>
  )
}
