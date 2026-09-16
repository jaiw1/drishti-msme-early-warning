// The frame every signed-in screen sits in: sidebar, header, mobile nav.
//
// The nav is filtered by the signed-in role against the same `x-roles` lists the backend
// enforces. That is a courtesy, not a control — a credit officer who types /threshold still
// gets <PermissionDenied/> from the route guard and a 403 from the API — but a menu full of
// doors that will not open is a bad screen.

import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  BadgeCheck, Compass, LayoutGrid, LineChart, PieChart, Plug, Radar, ShieldCheck, SlidersHorizontal, Users,
} from 'lucide-react'
import ScreenHelp from './ScreenHelp'
import SessionBar from './SessionBar'
import SourceBadge from './SourceBadge'
import { useAuth } from '../auth/AuthContext'
import { roleMatches } from '../auth/roles'

/** Route table. `roles` is copied verbatim from `contracts/openapi.json` `x-roles`. */
export const NAV = [
  { key: 'portfolio', path: '/watchlist', label: 'Watch-list', short: 'Watch-list', icon: LayoutGrid, help: 'watchlist', roles: ['A', 'M', 'CO'] },
  { key: 'real', path: '/real-data', label: 'Real-data model', short: 'Real data', icon: BadgeCheck, badge: 'REAL', help: 'real', roles: [] },
  { key: 'risk', path: '/risk', label: 'Portfolio risk', short: 'Risk', icon: PieChart, help: 'risk', roles: ['A', 'M', 'CO'] },
  { key: 'analytics', path: '/model', label: 'Model & Metrics', short: 'Model', icon: LineChart, help: 'model', roles: ['A', 'M', 'CO'] },
  { key: 'threshold', path: '/threshold', label: 'Thresholds', short: 'Thresholds', icon: SlidersHorizontal, help: 'threshold', roles: ['M', 'A'] },
  { key: 'sources', path: '/data-sources', label: 'Data sources', short: 'Sources', icon: Plug, help: 'sources', roles: [] },
  { key: 'admin', path: '/admin', label: 'Administration', short: 'Admin', icon: Users, help: 'admin', roles: ['A'] },
]

export const PATH_BY_VIEW = Object.fromEntries(NAV.map((n) => [n.key, n.path]))
const VIEW_BY_PATH = Object.fromEntries(NAV.map((n) => [n.path, n.key]))
export const viewForPath = (pathname) => VIEW_BY_PATH[pathname] || 'portfolio'

export function navFor(role, { isStatic = false } = {}) {
  // The frozen bundle has no session, so it shows what it can actually render.
  if (isStatic) return NAV.filter((n) => !['admin', 'threshold'].includes(n.key))
  return NAV.filter((n) => roleMatches(role, n.roles))
}

export default function AppShell({
  view,
  title,
  subtitle,
  help,
  source,
  sourceDetail,
  sandbox = false,
  actions,
  onTour,
  children,
}) {
  const { role, isStatic } = useAuth()
  const items = useMemo(() => navFor(role, { isStatic }), [role, isStatic])

  const NavLinks = ({ mobile }) => items.map((n) => {
    const current = view === n.key
    return (
      <Link
        key={n.key}
        to={n.path}
        aria-current={current ? 'page' : undefined}
        className={mobile
          ? `flex min-w-[68px] flex-1 shrink-0 flex-col items-center gap-0.5 px-1 py-2 text-center text-[10px] font-semibold leading-tight transition focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-white ${current ? 'bg-white/20 text-white' : 'text-white/80'}`
          : `flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-white ${current ? 'bg-white/20 text-white' : 'text-white/80 hover:bg-white/10 hover:text-white'}`}
      >
        <n.icon size={mobile ? 18 : 18} aria-hidden="true" />
        {mobile ? n.short : <span className="flex-1 text-left">{n.label}</span>}
        {!mobile && n.badge && (
          <span className="rounded bg-idbi-orange px-1.5 py-0.5 text-[9px] font-extrabold tracking-wide text-white">{n.badge}</span>
        )}
      </Link>
    )
  })

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 flex-col bg-idbi-green text-white md:flex">
        <div className="flex items-center gap-2.5 border-b border-white/20 px-5 py-5">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-white/20"><Radar size={20} aria-hidden="true" /></div>
          <div>
            <div className="font-extrabold leading-tight">DRISHT<span className="text-idbi-orangetx">i</span></div>
            <div className="text-[10px] leading-tight text-white/80">MSME Early-Warning</div>
          </div>
        </div>
        <nav className="space-y-1 p-3" aria-label="Sections">
          <NavLinks mobile={false} />
        </nav>
        <div className="mt-auto border-t border-white/20 p-4 text-[11px] leading-relaxed text-white/80">
          <div className="mb-1 flex items-center gap-1.5 text-white"><ShieldCheck size={13} aria-hidden="true" /> Human-in-the-loop</div>
          The model advises; the credit officer decides. IDBI Innovate 2026 · Track 4.
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-3.5 sm:px-6">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-idbi-green text-white md:hidden" aria-hidden="true">
            <Radar size={18} />
          </div>
          <div className="min-w-0">
            <h1 className="text-base font-extrabold text-slate-900 sm:text-lg">{title}</h1>
            {subtitle && <p className="text-xs text-slate-600">{subtitle}</p>}
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {source && <SourceBadge source={source} sandbox={sandbox} detail={sourceDetail} />}
            {actions}
            {help && <ScreenHelp screen={help} />}
            {onTour && (
              <button
                type="button"
                onClick={onTour}
                className="flex items-center gap-1.5 rounded-lg bg-idbi-green/10 px-3 py-1.5 text-xs font-semibold text-idbi-green transition hover:bg-idbi-green/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
              >
                <Compass size={14} aria-hidden="true" /> Tour
              </button>
            )}
            <SessionBar />
          </div>
        </header>

        <main id="main-content" className="space-y-5 p-4 pb-24 sm:p-6 md:pb-6">
          {children}
        </main>
      </div>

      {/* An administrator sees seven sections. Squashing seven labels into 375 px makes
          every one of them unreadable, so the bar scrolls instead of shrinking. */}
      <nav
        className="scroll-thin fixed inset-x-0 bottom-0 z-30 flex overflow-x-auto border-t border-white/20 bg-idbi-green pb-[env(safe-area-inset-bottom)] text-white md:hidden"
        aria-label="Sections"
      >
        <NavLinks mobile />
      </nav>
    </div>
  )
}
