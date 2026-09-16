// Routes and the app shell.
//
// Every route's `allow` list is copied verbatim from the operation's `x-roles` in
// contracts/openapi.json, so the guard and the server agree by construction. The guard is
// UX, never the access control: a user who types the URL anyway gets <PermissionDenied/>
// here and a 403 from the API either way.

import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import RequireAuth from './auth/RequireAuth'
import RequireRole from './auth/RequireRole'
import { useAuth } from './auth/AuthContext'
import ErrorBoundary from './components/ErrorBoundary'
import RouteAnnouncer from './components/RouteAnnouncer'
import SkipLink from './components/SkipLink'
import StaticDemoBanner from './components/StaticDemoBanner'
import { ToastProvider } from './components/Toasts'
import Empty from './components/states/Empty'
import Loading from './components/states/Loading'
import { PATH_BY_VIEW } from './components/AppShell'
import Admin from './screens/Admin'
import ChangePassword from './screens/ChangePassword'
import DataSources from './screens/DataSources'
import Login from './screens/Login'
import ModelMetrics from './screens/ModelMetrics'
import PortfolioRiskScreen from './screens/PortfolioRiskScreen'
import RealData from './screens/RealData'
import Thresholds from './screens/Thresholds'
import Watchlist from './screens/Watchlist'

/** ?view=risk was how the old tab switcher deep-linked. Keep those links alive. */
function LegacyViewRedirect() {
  const location = useLocation()
  const params = new URLSearchParams(location.search)
  const target = PATH_BY_VIEW[params.get('view')] || '/watchlist'
  params.delete('view')
  const search = params.toString()
  return <Navigate to={{ pathname: target, search: search ? `?${search}` : '' }} replace />
}

export default function App() {
  const { ready, isStatic } = useAuth()

  return (
    <ToastProvider>
      <SkipLink />
      {isStatic && <StaticDemoBanner />}
      <RouteAnnouncer />
      {!ready ? (
        <div className="grid min-h-screen place-items-center bg-slate-100">
          <Loading label="Starting DRISHTi…" inline />
        </div>
      ) : (
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<LegacyViewRedirect />} />
            <Route path="/login" element={<Login />} />
            <Route path="/change-password" element={<RequireAuth><ChangePassword /></RequireAuth>} />

            {/* x-roles: A, M, CO */}
            <Route path="/watchlist" element={<RequireRole allow={['A', 'M', 'CO']}><Watchlist /></RequireRole>} />
            <Route path="/risk" element={<RequireRole allow={['A', 'M', 'CO']}><PortfolioRiskScreen /></RequireRole>} />
            <Route path="/model" element={<RequireRole allow={['A', 'M', 'CO']}><ModelMetrics /></RequireRole>} />

            {/* x-roles: M, A — drishtiThresholdSet */}
            <Route path="/threshold" element={<RequireRole allow={['M', 'A']}><Thresholds /></RequireRole>} />

            {/* x-roles: A, M, CO, RM — meta/sync and meta/provenance */}
            <Route path="/data-sources" element={<RequireAuth><DataSources /></RequireAuth>} />
            <Route path="/real-data" element={<RequireAuth><RealData /></RequireAuth>} />

            {/* x-roles: A */}
            <Route path="/admin" element={<RequireRole allow={['A']}><Admin /></RequireRole>} />

            <Route
              path="*"
              element={
                <main id="main-content" className="grid min-h-screen place-items-center bg-slate-100 px-6">
                  <div className="w-full max-w-md">
                    <Empty
                      title="That page does not exist"
                      hint="The link may be from an older build. Use the sidebar to get back to the watch-list."
                    />
                  </div>
                </main>
              }
            />
          </Routes>
        </ErrorBoundary>
      )}
    </ToastProvider>
  )
}
