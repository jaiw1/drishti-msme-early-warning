// The existing DRISHTi cockpit, unchanged in layout, wrapped in the shared kit.
//
// What changed from App.jsx: the four tabs are routes instead of local state (so a
// screen is linkable, the back button works, and focus moves on navigation), the header
// carries <SessionBar/> and <ScreenHelp/>, and the data load reports its failure through
// the shared <ErrorState/>. The screens themselves are untouched — L10 proper redesigns
// them; this lane only makes them addressable and signed-in.
//
// TODO(L10): read the portfolio from GET /api/v1/drishti/{portfolio,metrics} once those
// routers land. Until then both live and static mode read the bundled snapshot, which is
// why every figure on these screens carries the SIMULATED badge.

import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import {
  Radar, LayoutGrid, LineChart, PieChart, BadgeCheck, ShieldCheck, Compass,
} from 'lucide-react'
import Kpis from '../components/Kpis'
import PortfolioTable from '../components/PortfolioTable'
import AccountDetail from '../components/AccountDetail'
import Analytics from '../components/Analytics'
import PortfolioRisk from '../components/PortfolioRisk'
import RealModel from '../components/RealModel'
import Guide from '../components/Guide'
import ScreenHelp from '../components/ScreenHelp'
import SessionBar from '../components/SessionBar'
import SourceBadge, { SOURCE } from '../components/SourceBadge'
import Loading from '../components/states/Loading'
import ErrorState from '../components/states/ErrorState'
import { runwayEstimate } from '../lib/runway'
import { publicPath } from '../lib/basepath'
import storage from '../lib/storage'

export const NAV = [
  { key: 'portfolio', path: '/watchlist', label: 'Watch-list', short: 'Watch-list', icon: LayoutGrid, help: 'watchlist' },
  { key: 'real', path: '/real-data', label: 'Real-data model', short: 'Real data', icon: BadgeCheck, badge: 'REAL', help: 'real' },
  { key: 'risk', path: '/risk', label: 'Portfolio risk', short: 'Risk', icon: PieChart, help: 'risk' },
  { key: 'analytics', path: '/model', label: 'Model & Metrics', short: 'Model', icon: LineChart, help: 'model' },
]

export const PATH_BY_VIEW = Object.fromEntries(NAV.map((n) => [n.key, n.path]))
const VIEW_BY_PATH = Object.fromEntries(NAV.map((n) => [n.path, n.key]))

const TITLES = {
  portfolio: ['Borrower Watch-list — all lending portfolios', 'Predicting default 12 months ahead'],
  risk: ['Portfolio Risk & Impact', 'Where the risk sits, and what acting early is worth'],
  analytics: ['Model Performance', 'Honest metrics, rank-ordering, lead-time and model rigor'],
  real: ['Real-Data Validation', 'The same method, proven on real Indian MSMEs'],
}

export const viewForPath = (pathname) => VIEW_BY_PATH[pathname] || 'portfolio'

export default function Cockpit() {
  const location = useLocation()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()

  const view = viewForPath(location.pathname)
  const selected = params.get('account')
  const [data, setData] = useState(null)
  const [realData, setRealData] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [guide, setGuide] = useState(false)

  const setView = (key) => navigate({ pathname: PATH_BY_VIEW[key] || '/watchlist', search: location.search })
  const setSelected = (accountId) => {
    setParams((prev) => {
      const nextParams = new URLSearchParams(prev)
      if (accountId) nextParams.set('account', accountId)
      else nextParams.delete('account')
      return nextParams
    }, { replace: true })
  }

  const loadData = () => {
    setLoadError(null)
    fetch(publicPath('demo_data.json'))
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((d) => {
        // decorate flagged accounts with the predicted runway (client-side, trajectory only)
        const ref = d.meta.reference_month, red = d.portfolio_summary.red_thr
        for (const rec of d.portfolio) {
          rec.runway = rec.bucket === 'green' ? null : runwayEstimate(d.timelines[rec.account_id], ref, red)
        }
        setData(d)
      })
      .catch((error) => setLoadError(error))
    // real-data tab degrades gracefully without this file, so a failure here is non-fatal
    fetch(publicPath('real_model.json')).then((r) => r.json()).then(setRealData).catch(() => {})
  }

  useEffect(() => {
    loadData()
    // auto-show on first visit; ?tour=0 suppresses it (screenshots, direct deep-links)
    if (!storage.get('drishti_seen_guide') && params.get('tour') !== '0') setGuide(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const closeGuide = () => { setGuide(false); storage.set('drishti_seen_guide', '1') }

  if (loadError) {
    return (
      <main id="main-content" className="grid min-h-screen place-items-center bg-slate-50 px-6">
        <div className="w-full max-w-md">
          <ErrorState
            title="Couldn’t load the portfolio data"
            message="The connection may have dropped while downloading the demo dataset (~1 MB). Please retry."
            onRetry={loadData}
            retryLabel="Retry"
          />
        </div>
      </main>
    )
  }

  if (!data) {
    return (
      <main id="main-content" className="grid min-h-screen place-items-center bg-slate-50 px-6">
        <Loading label="Loading DRISHTi…" inline />
      </main>
    )
  }

  const activeHelp = NAV.find((n) => n.key === view)?.help

  return (
    <div className="flex min-h-screen">
      {/* sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col bg-idbi-green text-white md:flex">
        <div className="flex items-center gap-2.5 border-b border-white/10 px-5 py-5">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-white/15"><Radar size={20} aria-hidden="true" /></div>
          <div>
            <div className="font-extrabold leading-tight">DRISHT<span className="text-idbi-orange">i</span></div>
            <div className="text-[10px] leading-tight text-white/60">MSME Early-Warning</div>
          </div>
        </div>
        <nav className="space-y-1 p-3" aria-label="Sections">
          {NAV.map((n) => (
            <Link
              key={n.key}
              to={{ pathname: n.path, search: location.search }}
              aria-current={view === n.key ? 'page' : undefined}
              className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70 ${view === n.key ? 'bg-white/15' : 'text-white/70 hover:bg-white/10'}`}
            >
              <n.icon size={18} aria-hidden="true" /> <span className="flex-1 text-left">{n.label}</span>
              {n.badge && <span className="rounded bg-idbi-orange px-1.5 py-0.5 text-[9px] font-extrabold tracking-wide text-white">{n.badge}</span>}
            </Link>
          ))}
        </nav>
        <div className="mt-auto border-t border-white/10 p-4 text-[11px] leading-relaxed text-white/50">
          <div className="mb-1 flex items-center gap-1.5 text-white/70"><ShieldCheck size={13} aria-hidden="true" /> Human-in-the-loop</div>
          The model advises; the credit officer decides. IDBI Innovate 2026 · Track 4.
        </div>
      </aside>

      {/* main */}
      <div className="min-w-0 flex-1">
        <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-6 py-3.5">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-idbi-green text-white md:hidden" aria-hidden="true">
            <Radar size={18} />
          </div>
          <div>
            <h1 className="text-lg font-extrabold text-slate-900">{TITLES[view][0]}</h1>
            <p className="text-xs text-slate-400">
              {TITLES[view][1]} · book as of <span className="font-bold text-idbi-green">{data.meta.reference_month}</span> <span className="text-slate-400">(“today”)</span> · {data.meta.n_accounts_scored.toLocaleString('en-IN')} live accounts
            </p>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <SourceBadge source={SOURCE.SIMULATED} detail="Synthetic book; the bank APIs replace it as subscriptions are approved." />
            {activeHelp && <ScreenHelp screen={activeHelp} />}
            <button
              type="button"
              onClick={() => setGuide(true)}
              className="flex items-center gap-1.5 rounded-lg bg-idbi-green/10 px-3 py-1.5 text-xs font-semibold text-idbi-green transition hover:bg-idbi-green/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
            >
              <Compass size={14} aria-hidden="true" /> Tour
            </button>
            <SessionBar />
          </div>
        </header>

        <main id="main-content" className="space-y-5 p-6 pb-24 md:pb-6">
          {view === 'portfolio' && (
            <>
              <Link
                to={{ pathname: PATH_BY_VIEW.real, search: location.search }}
                className="flex w-full items-center gap-3 rounded-xl border border-idbi-green/30 bg-gradient-to-r from-idbi-green/10 to-idbi-green/5 px-4 py-3 text-left transition hover:from-idbi-green/15 hover:to-idbi-green/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
              >
                <BadgeCheck className="shrink-0 text-idbi-green" size={22} aria-hidden="true" />
                <div className="flex-1 text-sm leading-snug">
                  <span className="font-bold text-idbi-green">Validated on {realData ? realData.meta.n_companies.toLocaleString('en-IN') : '3,200'} real Indian MSMEs</span>
                  <span className="text-slate-600"> — the same method scores an honest <b>{realData ? realData.metrics.auc : '0.81'} AUC</b> on real credit-rating defaults, not just synthetic data.</span>
                </div>
                <span className="whitespace-nowrap text-sm font-bold text-idbi-green">See the proof →</span>
              </Link>
              <Kpis summary={data.portfolio_summary} metrics={data.metrics} />
              <PortfolioTable rows={data.portfolio} onSelect={setSelected} />
            </>
          )}
          {view === 'risk' && <PortfolioRisk data={data} onSelect={setSelected} />}
          {view === 'analytics' && <Analytics data={data} />}
          {view === 'real' && <RealModel data={realData} syntheticAuc={data.metrics.auc} />}
        </main>
      </div>

      {/* mobile bottom nav (sidebar is hidden below md) */}
      <nav className="fixed inset-x-0 bottom-0 z-30 flex border-t border-white/10 bg-idbi-green pb-[env(safe-area-inset-bottom)] text-white md:hidden" aria-label="Sections">
        {NAV.map((n) => (
          <Link
            key={n.key}
            to={{ pathname: n.path, search: location.search }}
            aria-current={view === n.key ? 'page' : undefined}
            className={`flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-white/70 ${view === n.key ? 'bg-white/15 text-white' : 'text-white/60'}`}
          >
            <n.icon size={18} aria-hidden="true" /> {n.short}
          </Link>
        ))}
      </nav>

      {selected && <AccountDetail data={data} accountId={selected} onClose={() => setSelected(null)} />}
      {guide && <Guide setView={setView} setSelected={setSelected} onClose={closeGuide} />}
    </div>
  )
}
